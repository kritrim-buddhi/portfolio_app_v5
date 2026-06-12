"""
engine/allocator.py — Monthly SIP Router.

Pure functions. No database. No UI.
This is where the 40-20-20-20 logic lives, including drift-aware redirection.

Core question this file answers:
  "Given ₹D_target this month and the current drift state,
   how much exactly goes into each fund?"

Two modes:
  1. NORMAL: No drift → straight 40/20/20/20 split
  2. DRIFT-ADJUSTED: Some funds are over/underweight →
     pause inflows to overweight funds and redistribute
     their share to underweight funds proportionally.
"""

from dataclasses import dataclass
from typing import List
from engine.drift import FundDriftResult


@dataclass
class AllocationOrder:
    fund_id:       int
    name:          str
    asset_class:   str
    target_pct:    float       # What the target is
    adjusted_pct:  float       # What we're actually sending this month (may differ)
    amount:        float       # Rupee amount to invest
    drift_status:  str         # Passed through from drift analysis
    is_redirected: bool        # True if this fund's share was modified due to drift


def compute_allocation(
    base_target: float,
    drift_results: List[FundDriftResult],
) -> List[AllocationOrder]:
    """
    The core routing algorithm.

    Step 1: Identify overweight and underweight funds.
    Step 2: Zero out cash going to overweight funds.
    Step 3: Pool that zeroed-out cash back into the base.
    Step 4: Redistribute the total across underweight (and on-target) funds,
            proportional to their target weights.

    Why proportional redistribution and not equal split?
    Because if Midcap (20%) and Small Cap (20%) are both underweight,
    they should each get the same extra push — proportional to their own targets.
    Forcing equal split would distort the model's intended weights.
    """

    if base_target <= 0:
        # Return zero-amount orders — caller handles the no-investment case
        return [AllocationOrder(
            fund_id=f.fund_id, name=f.name, asset_class=f.asset_class,
            target_pct=f.target_pct, adjusted_pct=0.0, amount=0.0,
            drift_status=f.status, is_redirected=False,
        ) for f in drift_results]

    # Step 1: Classify funds
    overweight  = [f for f in drift_results if f.status == "OVERWEIGHT"]
    not_over    = [f for f in drift_results if f.status != "OVERWEIGHT"]

    # Step 2: How much weight was going to overweight funds?
    # We're zeroing their inflow, so that cash needs to go somewhere.
    redirected_weight = sum(f.target_pct for f in overweight)

    # Step 3: Remaining weight is what non-overweight funds share
    remaining_weight = 1.0 - redirected_weight   # e.g. 0.60 if 40% fund is overweight

    orders = []

    for f in drift_results:
        is_over      = f.status == "OVERWEIGHT"
        is_redirected = is_over or (redirected_weight > 0 and f.status != "OVERWEIGHT")

        if is_over:
            # Zero inflow — but we still show the order so the user sees it
            adjusted_pct = 0.0
            amount       = 0.0
        elif remaining_weight == 0:
            # Edge case: all funds are overweight (shouldn't happen, but guard it)
            adjusted_pct = 0.0
            amount       = 0.0
        else:
            # Redistribute proportionally within non-overweight funds
            # e.g. if Next50 (20%) is overweight and remaining is 60%,
            # Sensex (40%) gets 40/60 = 66.7% of total cash
            adjusted_pct = f.target_pct / remaining_weight
            amount       = base_target * adjusted_pct

        orders.append(AllocationOrder(
            fund_id       = f.fund_id,
            name          = f.name,
            asset_class   = f.asset_class,
            target_pct    = f.target_pct,
            adjusted_pct  = adjusted_pct,
            amount        = round(amount, 2),
            drift_status  = f.status,
            is_redirected = is_redirected and not is_over,
        ))

    # Sanity check: total allocated should equal base_target (within rounding)
    total_allocated = sum(o.amount for o in orders)
    delta = abs(total_allocated - base_target)
    if delta > 1.0:   # 1 rupee tolerance for float rounding
        # Fix rounding residual on the largest non-zero order
        non_zero = [o for o in orders if o.amount > 0]
        if non_zero:
            largest = max(non_zero, key=lambda o: o.amount)
            largest.amount = round(largest.amount + (base_target - total_allocated), 2)

    return orders


def compute_step_up(current_sip: float, step_up_rate: float = 0.10) -> float:
    """Return next year's SIP after applying the 10% annual step-up."""
    return round(current_sip * (1 + step_up_rate), 2)
