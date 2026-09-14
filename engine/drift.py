"""
engine/drift.py — Threshold-Based Deviation Checker.

Pure functions only. No database calls. No Streamlit. Just math.
Input: a list of fund dicts (from database.get_latest_snapshot)
Output: the same list, enriched with drift analysis fields.

The 10% Relative Deviation Rule means:
  - For a 40% target: band is 40% ± (40% × 10%) → [36%, 44%]
  - For a 20% target: band is 20% ± (20% × 10%) → [18%, 22%]
"""

from dataclasses import dataclass
from typing import List


DEVIATION_THRESHOLD = 0.05   # 5% relative, not absolute


@dataclass
class FundDriftResult:
    fund_id:        int
    name:           str
    asset_class:    str
    target_pct:     float
    current_value:  float
    actual_pct:     float      # current_value / total_portfolio
    lower_bound:    float      # target - (target * threshold)
    upper_bound:    float      # target + (target * threshold)
    status:         str        # OVERWEIGHT | UNDERWEIGHT | ON_TARGET
    status_label:   str        # The emoji string for display
    deviation_pct:  float      # How far actual is from target, in relative terms


def analyze_drift(fund_snapshots: list) -> List[FundDriftResult]:
    """
    Takes raw snapshot dicts from the database and returns
    a list of FundDriftResult objects with full drift analysis.

    Why a dataclass instead of a plain dict?
    Because fund_result.actual_pct is clearer than fund_result['actual_pct'].
    It also gives you autocomplete in any editor.
    """
    total = sum(f["current_value"] for f in fund_snapshots)
    if total == 0:
        raise ValueError("Total portfolio value is zero — cannot compute allocations.")

    results = []
    for f in fund_snapshots:
        target    = f["target_pct"]
        actual    = f["current_value"] / total
        lower     = target * (1 - DEVIATION_THRESHOLD)
        upper     = target * (1 + DEVIATION_THRESHOLD)

        # Relative deviation: how far is actual from target, as a % of target?
        # e.g. target=0.40, actual=0.45 → deviation = (0.45-0.40)/0.40 = +12.5%
        rel_deviation = (actual - target) / target

        if actual > upper:
            status       = "OVERWEIGHT"
            status_label = "🚨 OVERWEIGHT — REDUCE INFLOWS"
        elif actual < lower:
            status       = "UNDERWEIGHT"
            status_label = "🛍️ UNDERWEIGHT — BUY MORE"
        else:
            status       = "ON_TARGET"
            status_label = "✅ ON TARGET"

        results.append(FundDriftResult(
            fund_id       = f["id"],
            name          = f["name"],
            asset_class   = f["asset_class"],
            target_pct    = target,
            current_value = f["current_value"],
            actual_pct    = actual,
            lower_bound   = lower,
            upper_bound   = upper,
            status        = status,
            status_label  = status_label,
            deviation_pct = rel_deviation,
        ))

    return results
