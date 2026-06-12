"""
engine/nav_fetcher.py — Fetches live NAV from mfapi.in (which mirrors AMFI daily data).

Pure function. No database. No UI.
One job: given a scheme code, return today's NAV as a float.

How it works:
  mfapi.in wraps AMFI's daily NAV flat file into a clean JSON API.
  AMFI publishes NAV once per business day, typically by 9-11 PM IST.
  So "today's NAV" after market close = the official end-of-day price.
  Before that, it's the previous business day's NAV — which is fine,
  because MF units are priced at end-of-day anyway.

The URL structure:
  https://api.mfapi.in/mf/{scheme_code}
  Returns: { "meta": {...}, "data": [{"date": "07-06-2026", "nav": "123.45"}, ...] }
  data[0] is always the most recent date.
"""

import urllib.request
import urllib.error
import json
from dataclasses import dataclass
from typing import Optional


MFAPI_BASE = "https://api.mfapi.in/mf"
TIMEOUT_SECONDS = 10


@dataclass
class NAVResult:
    scheme_code: int
    fund_name: str      # as returned by the API (good for verification)
    nav: float
    nav_date: str       # date string from API e.g. "07-06-2026"
    source: str         # "api" or "fallback"


class NAVFetchError(Exception):
    """Raised when NAV cannot be fetched — lets the caller decide what to do."""
    pass


def fetch_nav(scheme_code: int) -> NAVResult:
    """
    Fetch the most recent NAV for a given AMFI scheme code.

    Raises NAVFetchError if the API is unreachable or returns bad data.
    The caller (app.py) should catch this and fall back to manual entry.

    Why not silently return None?
    Because silent failures in financial calculations are worse than loud errors.
    You want to KNOW if the NAV didn't update, not silently multiply by None.
    """
    url = f"{MFAPI_BASE}/{scheme_code}"

    try:
        req = urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS)
        raw = req.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise NAVFetchError(f"Network error fetching scheme {scheme_code}: {e}") from e
    except Exception as e:
        raise NAVFetchError(f"Unexpected error for scheme {scheme_code}: {e}") from e

    try:
        payload = json.loads(raw)
        latest = payload["data"][0]           # index 0 = most recent date
        nav_value = float(latest["nav"])
        nav_date  = latest["date"]
        fund_name = payload["meta"]["scheme_name"]
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
        raise NAVFetchError(f"Malformed API response for scheme {scheme_code}: {e}") from e

    return NAVResult(
        scheme_code = scheme_code,
        fund_name   = fund_name,
        nav         = nav_value,
        nav_date    = nav_date,
        source      = "api",
    )


def fetch_all_navs(scheme_map: dict) -> dict:
    """
    Fetch NAVs for multiple funds.

    scheme_map: { fund_id: scheme_code }  e.g. { 1: 120716, 2: 120684, ... }
    Returns:    { fund_id: NAVResult }  — only for funds that succeeded.

    Funds that fail (network error, etc.) are excluded from the result dict.
    The caller checks which fund_ids are missing and handles them.
    """
    results = {}
    for fund_id, scheme_code in scheme_map.items():
        try:
            results[fund_id] = fetch_nav(scheme_code)
        except NAVFetchError:
            pass   # Caller handles missing fund_ids
    return results
