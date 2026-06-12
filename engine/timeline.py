"""
engine/timeline.py — Journey date arithmetic.

Pure functions. No DB. No UI.
Answers: where are you in your 20-year investment journey?
"""

from dataclasses import dataclass
from datetime import date
from dateutil.relativedelta import relativedelta


@dataclass
class JourneyStatus:
    journey_year:        int      # Year 1, Year 2, ...
    journey_month:       int      # Month within current year (1-12)
    total_months:        int      # Total months since journey start
    next_drift_check:    date     # 6 months from last check
    days_to_drift_check: int
    next_stepup_date:    date     # April 1 of next FY
    days_to_stepup:      int
    current_fy:          str      # e.g. "FY2026-27"


def get_journey_status(
    start_date: date,
    last_drift_check: date = None,
) -> JourneyStatus:
    """
    Compute the user's position in their investment journey.

    start_date: when they started their SIP (first entry in sip_history)
    last_drift_check: date of last rebalancing check (None = never checked)
    """
    today        = date.today()
    delta        = relativedelta(today, start_date)
    total_months = delta.years * 12 + delta.months + 1
    journey_year = delta.years + 1
    journey_month = delta.months + 1

    # Next drift check = 6 months after last check, or 6 months from start
    baseline       = last_drift_check or start_date
    next_drift     = baseline + relativedelta(months=6)
    days_to_drift  = (next_drift - today).days

    # Next step-up = April 1 of the next financial year
    if today.month >= 4:
        next_stepup = date(today.year + 1, 4, 1)
    else:
        next_stepup = date(today.year, 4, 1)
    days_to_stepup = (next_stepup - today).days

    # Current FY
    if today.month >= 4:
        current_fy = f"FY{today.year}-{str(today.year + 1)[2:]}"
    else:
        current_fy = f"FY{today.year - 1}-{str(today.year)[2:]}"

    return JourneyStatus(
        journey_year        = journey_year,
        journey_month       = journey_month,
        total_months        = total_months,
        next_drift_check    = next_drift,
        days_to_drift_check = days_to_drift,
        next_stepup_date    = next_stepup,
        days_to_stepup      = days_to_stepup,
        current_fy          = current_fy,
    )
