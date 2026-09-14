"""
engine/cas_parser.py — Parses MF Central CAS Excel export.

V2 change (Priority 2):
  parse_cas_excel() now returns ALL holdings found in the Excel,
  not just the 4 target funds. The caller decides what to do with each.

  This allows save_cas_import() to also refresh legacy fund market values
  from the same CAS data — no second parse, no extra upload.

Matching strategy for target funds:
  We match your 4 target funds by substring + AMC filter.
  All other funds are returned as-is, keyed by their scheme name.
  The database layer matches these against legacy fund names.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union
import pandas as pd


FUND_MATCH_STRINGS = {
    1: "BSE Sensex Index Fund",
    2: "Nifty Next 50 Index Fund",
    3: "Nifty Midcap 150 Index Fund",
    4: "Invesco India Smallcap",
    5: "Parag Parikh Flexi Cap",
    6: "Nippon India Power & Infra",
    # fund 7 (ICICI Gold ETF) is exchange-traded via demat — not present in MF Central CAS
}

FUND_AMC_FILTER = {
    2: "ICICI",
    3: "ICICI",
    4: "Invesco",
    5: "PPFAS",
}


@dataclass
class HoldingData:
    fund_id:       Optional[int]   # set for target funds, None for others
    scheme_name:   str
    amc:           str
    units:         float
    current_value: float
    nav:           float
    nav_date:      str


class CASParseError(Exception):
    pass


def parse_cas_excel(excel_source: Union[str, object]) -> dict:
    """
    Read an MF Central CAS Excel file.

    Returns:
        {
          "target":  { fund_id: HoldingData }   — your 4 matched funds
          "all":     { scheme_name: HoldingData } — every non-zero fund in CAS
        }

    Why return both?
      "target" goes to portfolio_snapshots + holdings (existing logic).
      "all"    goes to legacy_funds value refresh (Priority 2).

    excel_source: either a file path string or a Streamlit UploadedFile object.
    pandas read_excel handles both.
    """
    try:
        df = pd.read_excel(
            excel_source,
            sheet_name="Portfolio Details",
            header=None,
        )
    except Exception as e:
        raise CASParseError(f"Could not read Excel file: {e}") from e

    # Find header row dynamically
    header_row_idx = None
    for i, row in df.iterrows():
        if str(row.iloc[0]).strip() == "Scheme Name":
            header_row_idx = i
            break

    if header_row_idx is None:
        raise CASParseError(
            "Could not find 'Scheme Name' column in this file. "
            "Make sure you're uploading the Portfolio Details export from MF Central."
        )

    # Extract statement date from row 6
    try:
        nav_date = str(df.iloc[6, 1]).strip()
    except Exception:
        nav_date = str(date.today())

    data = df.iloc[header_row_idx + 1:].copy()
    data.columns = df.iloc[header_row_idx].tolist()
    data = data.reset_index(drop=True)

    for col in ["Current Value", "Units", "Invested Value"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    data = data.dropna(subset=["Scheme Name", "Current Value"])
    data = data[data["Current Value"] > 0]
    data["Scheme Name"] = data["Scheme Name"].astype(str).str.strip()
    data["AMC Name"]    = data["AMC Name"].astype(str).str.strip()

    # ── Build full holdings dict (all non-zero funds) ─────────────────────────
    all_holdings: dict[str, HoldingData] = {}
    for _, row in data.iterrows():
        units = float(row["Units"]) if pd.notna(row["Units"]) else 0.0
        value = float(row["Current Value"])
        nav   = round(value / units, 4) if units > 0 else 0.0
        all_holdings[str(row["Scheme Name"])] = HoldingData(
            fund_id       = None,
            scheme_name   = str(row["Scheme Name"]),
            amc           = str(row["AMC Name"]),
            units         = round(units, 3),
            current_value = round(value, 2),
            nav           = nav,
            nav_date      = nav_date,
        )

    # ── Match target funds ────────────────────────────────────────────────────
    target_holdings: dict[int, HoldingData] = {}
    for fund_id, match_str in FUND_MATCH_STRINGS.items():
        amc_filter = FUND_AMC_FILTER.get(fund_id)
        mask = data["Scheme Name"].str.contains(match_str, case=False, na=False)
        if amc_filter:
            mask = mask & data["AMC Name"].str.contains(amc_filter, case=False, na=False)
        matches = data[mask]
        if matches.empty:
            continue

        if len(matches) > 1:
            total_units = matches["Units"].sum()
            total_value = matches["Current Value"].sum()
            row         = matches.iloc[0]
        else:
            row         = matches.iloc[0]
            total_units = float(row["Units"])
            total_value = float(row["Current Value"])

        nav = round(total_value / total_units, 4) if total_units > 0 else 0.0
        holding = HoldingData(
            fund_id       = fund_id,
            scheme_name   = str(row["Scheme Name"]),
            amc           = str(row["AMC Name"]),
            units         = round(total_units, 3),
            current_value = round(total_value, 2),
            nav           = nav,
            nav_date      = nav_date,
        )
        target_holdings[fund_id] = holding

    if not target_holdings and not all_holdings:
        raise CASParseError(
            "No holdings found in this file. "
            "Make sure it is a Portfolio Details export from MF Central."
        )

    return {"target": target_holdings, "all": all_holdings}


def extract_my_funds(
    cas_result: dict,
    my_fund_ids: list[int],
) -> tuple[dict, list]:
    """
    Split target holdings into matched and unmatched.
    cas_result: the dict returned by parse_cas_excel()
    """
    target    = cas_result.get("target", {})
    matched   = {fid: target[fid] for fid in my_fund_ids if fid in target}
    unmatched = [fid for fid in my_fund_ids if fid not in target]
    return matched, unmatched


from datetime import date  # needed for nav_date fallback
