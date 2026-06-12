"""
engine/cas_excel_parser.py — Reads the MF Central Detailed CAS Excel file.

Replaces the PDF/casparser approach entirely. The Excel file is cleaner:
no text extraction, no regex on PDFs, no library bugs.

Structure of the MF Central Excel (confirmed from your actual file):
  Sheet: 'Portfolio Details'
  Row 0-10:  Investor metadata (name, PAN, date range, totals)
  Row 11:    Column headers
  Row 12+:   One fund per row

Columns: Scheme Name | AMC Name | Category | Folio No. |
         Invested Value | Current Value | Returns | Units

Matching strategy:
  The Excel has full fund names. Our DB has abbreviated names.
  We use rapidfuzz.token_set_ratio to fuzzy-match them.
  token_set_ratio is the right scorer here because it ignores word order
  and handles substrings well — so 'BSE Sensex Index Fund' matches
  'ICICI Prudential BSE Sensex Index Fund Direct Plan Growth' correctly.

  Threshold = 80. In testing, correct matches score 93-100.
  Wrong matches (e.g. DSP Small Cap vs DSP ELSS) score below 70.
  80 gives us a safe buffer.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import pandas as pd
from rapidfuzz import fuzz, process


HEADER_ROW    = 11     # 0-indexed row number of the column headers
MATCH_THRESHOLD = 80   # minimum fuzzy score to accept a match


@dataclass
class HoldingData:
    scheme_code:  Optional[int]  # Not in Excel — populated from DB match
    scheme_name:  str            # Full name as it appears in the Excel
    amc:          str
    units:        float
    nav:          float          # Current Value / Units (computed)
    value:        float          # Current Value from Excel
    nav_date:     str            # 'as of' date from Excel header
    isin:         None = None    # Not in Excel


class CASExcelError(Exception):
    """Raised when the Excel file can't be read or doesn't have expected structure."""
    pass


def parse_cas_excel(excel_path: str) -> tuple[dict, str]:
    """
    Read MF Central Detailed CAS Excel and return all non-zero holdings.

    Returns:
        holdings:  { scheme_name (str) : HoldingData } — keyed by full name
        as_of_date: str — the statement date e.g. '08-Jun-2026'

    Why key by name and not scheme_code?
    The Excel has no AMFI scheme codes. We match to our DB funds by name
    in extract_my_funds(), after reading the file.
    """
    excel_path = Path(excel_path)
    if not excel_path.exists():
        raise CASExcelError(f"File not found: {excel_path}")

    try:
        # Read raw first to extract the statement date from metadata rows
        raw = pd.read_excel(str(excel_path), sheet_name='Portfolio Details', header=None)
    except Exception as e:
        raise CASExcelError(f"Could not open Excel file: {e}") from e

    # Verify the sheet has the structure we expect
    if raw.shape[0] < 12 or raw.shape[1] < 8:
        raise CASExcelError(
            "Portfolio Details sheet doesn't have the expected structure. "
            "Make sure this is a Detailed CAS from MF Central, not a Summary."
        )

    # Extract statement date from row 6 ('To Date' field)
    # Row 5 = From Date, Row 6 = To Date
    try:
        as_of_date = str(raw.iloc[6, 1]).strip()
    except Exception:
        as_of_date = "unknown"

    # Now read again with row 11 as the header
    try:
        df = pd.read_excel(
            str(excel_path),
            sheet_name='Portfolio Details',
            header=HEADER_ROW,
        )
    except Exception as e:
        raise CASExcelError(f"Failed to read fund rows: {e}") from e

    # Validate expected columns exist
    required_cols = {'Scheme Name', 'AMC Name', 'Units', 'Current Value'}
    missing = required_cols - set(df.columns)
    if missing:
        raise CASExcelError(
            f"Expected columns not found: {missing}. "
            f"Found: {list(df.columns)}"
        )

    # Filter: keep only rows with numeric Current Value > 0
    # (zero-value rows are old/redeemed funds — we don't care)
    df = df[pd.to_numeric(df['Current Value'], errors='coerce') > 0].copy()
    df['Current Value'] = pd.to_numeric(df['Current Value'])
    df['Units']         = pd.to_numeric(df['Units'], errors='coerce').fillna(0)

    holdings = {}
    for _, row in df.iterrows():
        name  = str(row['Scheme Name']).strip()
        units = float(row['Units'])
        value = float(row['Current Value'])
        amc   = str(row.get('AMC Name', '')).strip()

        if not name or units <= 0:
            continue

        # NAV = Current Value / Units (computed — Excel doesn't have a NAV column)
        nav = round(value / units, 4) if units > 0 else 0.0

        holdings[name] = HoldingData(
            scheme_code = None,    # filled in by extract_my_funds
            scheme_name = name,
            amc         = amc,
            units       = units,
            nav         = nav,
            value       = value,
            nav_date    = as_of_date,
        )

    if not holdings:
        raise CASExcelError(
            "No non-zero holdings found in the Excel file. "
            "Check that Current Value column has data."
        )

    return holdings, as_of_date


def extract_my_funds(
    excel_holdings: dict,
    my_funds: list,
    threshold: int = MATCH_THRESHOLD,
) -> tuple[dict, list]:
    """
    Fuzzy-match our DB fund names against the Excel's full fund names.

    my_funds: list of dicts from database.get_funds()
              each has: id, name, scheme_code, asset_class, target_pct

    Returns:
        matched:   { fund_id: HoldingData } — with scheme_code populated
        unmatched: [ fund dict ] — funds that didn't score above threshold
    """
    excel_names = list(excel_holdings.keys())
    matched   = {}
    unmatched = []

    for fund in my_funds:
        db_name = fund['name']

        # extractOne returns (best_match_string, score, index)
        result = process.extractOne(
            db_name,
            excel_names,
            scorer=fuzz.token_set_ratio,
        )

        if result is None or result[1] < threshold:
            unmatched.append(fund)
            continue

        best_excel_name = result[0]
        score           = result[1]
        holding         = excel_holdings[best_excel_name]

        # Stamp the scheme_code from our DB onto the holding
        holding.scheme_code = fund['scheme_code']

        matched[fund['id']] = holding

    return matched, unmatched
