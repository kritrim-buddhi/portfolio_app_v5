"""
engine/stp.py — LTCG-Aware STP Migration Planner.

One job: given a set of legacy funds you want to exit, compute
a month-by-month redemption schedule that:
  1. Never realises more than Rs.1,25,000 in LTCG per financial year
  2. Exits lower-gain-ratio funds first (maximises rupees moved per tax rupee)
  3. Calculates the correct exit timeline automatically
  4. Produces the monthly D_target = salary_sip + stp_injection for the allocator

Key concepts:

  Gain Ratio = Gain / Current Value
    = the fraction of every rupee redeemed that is taxable gain.
    e.g. Axis ELSS gain ratio = 51.3% means every Rs.100 redeemed
    realises Rs.51.3 of LTCG.

  Annual LTCG Headroom = Rs.1,25,000 per financial year (Apr-Mar).
    We never exceed this. LTCG realised = sum(redemption × gain_ratio)
    across all redemptions in the financial year.

  Optimal order = lowest gain ratio first.
    Edelweiss (40.1%) lets you redeem Rs.3,11,696 before hitting the limit.
    Axis Small Cap (65.4%) only lets you redeem Rs.1,91,131.
    Exiting Edelweiss first moves more money per tax rupee.

  Monthly STP = annual_budget / 12, recalculated each financial year
    as the remaining pool shrinks and blended gain ratio shifts.
"""

from dataclasses import dataclass, field
from datetime import date
from dateutil.relativedelta import relativedelta
from typing import List


LTCG_ANNUAL_LIMIT = 125_000.0   # Rs.1,25,000 — tax-free LTCG per financial year


@dataclass
class LegacyFund:
    """One legacy fund you want to exit."""
    name:          str
    invested:      float   # Cost of acquisition (from CAS "Invested Value")
    current_value: float   # Current market value (from CAS "Current Value")

    @property
    def gain(self) -> float:
        return self.current_value - self.invested

    @property
    def gain_ratio(self) -> float:
        """Fraction of each redeemed rupee that is taxable gain."""
        if self.current_value == 0:
            return 0.0
        return self.gain / self.current_value


@dataclass
class MonthlyInstruction:
    """One row in the STP schedule — what to do in a given month."""
    month_num:        int       # 1, 2, 3 ... N
    calendar_month:   str       # e.g. "Jul 2026"
    financial_year:   str       # e.g. "FY2026-27"
    redemptions:      dict      # { fund_name: rupee_amount }
    total_redemption: float     # sum of all redemptions this month
    ltcg_this_month:  float     # gains realised this month
    ltcg_fy_running:  float     # cumulative LTCG in this financial year
    pool_remaining:   float     # total legacy pool value after this month
    stp_injection:    float     # = total_redemption (cash to inject into target funds)


@dataclass
class STPPlan:
    """Full output of the STP engine."""
    legacy_funds:         List[LegacyFund]
    schedule:             List[MonthlyInstruction]
    total_months:         int
    v_legacy:             float    # starting pool value
    monthly_stp:          float    # approximate monthly injection (varies by FY)
    ltcg_saved:           float    # tax saved vs immediate full redemption
    start_date:           date


def _financial_year(d: date) -> str:
    """Return 'FY2026-27' for any date in that financial year."""
    if d.month >= 4:
        return f"FY{d.year}-{str(d.year + 1)[2:]}"
    else:
        return f"FY{d.year - 1}-{str(d.year)[2:]}"


def _fy_start(d: date) -> date:
    """Return April 1 of the financial year containing date d."""
    if d.month >= 4:
        return date(d.year, 4, 1)
    return date(d.year - 1, 4, 1)


def compute_stp_plan(
    legacy_funds: List[LegacyFund],
    salary_sip: float,
    start_date: date = None,
    ltcg_already_realised_this_fy: float = 0.0,
) -> STPPlan:
    """
    Compute the full LTCG-aware STP schedule.

    Args:
        legacy_funds:                  List of funds to exit.
        salary_sip:                    Your monthly salary SIP (for D_target context).
        start_date:                    First STP month. Defaults to today.
        ltcg_already_realised_this_fy: Gains already booked this financial year.
                                       User said Rs.0, but kept as a parameter
                                       so the app can ask in future years.

    Returns:
        STPPlan with full month-by-month schedule.

    Algorithm:
        Each month:
          1. Sort remaining funds by gain_ratio ascending (lowest first).
          2. Calculate LTCG headroom left this financial year.
          3. Compute max redemption for this month = monthly budget.
          4. Redeem from funds in order until monthly budget is exhausted
             or all funds are drained.
          5. Advance to next month. If April 1, reset FY LTCG counter.
    """
    if start_date is None:
        start_date = date.today().replace(day=1)

    # Work on mutable copies — we drain these as we simulate
    pool = [
        LegacyFund(f.name, f.invested, f.current_value)
        for f in sorted(legacy_funds, key=lambda x: x.gain_ratio)
    ]

    v_legacy           = sum(f.current_value for f in pool)
    total_gain_if_now  = sum(f.gain for f in pool)
    tax_if_exit_now    = max(0, total_gain_if_now - LTCG_ANNUAL_LIMIT) * 0.125

    schedule: List[MonthlyInstruction] = []
    month_num          = 0
    current_date       = start_date
    ltcg_fy            = ltcg_already_realised_this_fy   # running total for current FY
    current_fy         = _financial_year(current_date)

    while any(f.current_value > 0.01 for f in pool):
        month_num    += 1
        cal_month     = current_date.strftime("%b %Y")
        fy_label      = _financial_year(current_date)

        # Reset LTCG counter on new financial year (April)
        if fy_label != current_fy:
            ltcg_fy   = 0.0
            current_fy = fy_label

        # How much LTCG headroom remains this financial year?
        fy_headroom   = max(0.0, LTCG_ANNUAL_LIMIT - ltcg_fy)

        # Blended gain ratio of what's left in the pool
        pool_value    = sum(f.current_value for f in pool if f.current_value > 0)
        pool_gain     = sum(f.gain for f in pool if f.current_value > 0)

        if pool_value <= 0:
            break

        blended_ratio = pool_gain / pool_value if pool_value > 0 else 0

        # Monthly budget: annual headroom ÷ months remaining in this FY
        # Months remaining = April to March, counting from current month
        fy_start      = _fy_start(current_date)
        fy_end        = date(fy_start.year + 1, 3, 31)
        months_left_in_fy = max(1, (fy_end.year - current_date.year) * 12
                                   + fy_end.month - current_date.month + 1)

        if fy_headroom <= 0:
            # No headroom left this FY — pause redemptions until April
            monthly_budget = 0.0
        else:
            # Spread remaining FY headroom evenly across remaining months
            # Then convert LTCG budget → redemption budget
            monthly_ltcg_budget   = fy_headroom / months_left_in_fy
            monthly_redeem_budget = (monthly_ltcg_budget / blended_ratio
                                     if blended_ratio > 0 else 0)
            monthly_budget        = min(monthly_redeem_budget, pool_value)

        # Redeem from funds in gain_ratio order (lowest first)
        redemptions       = {}
        budget_remaining  = monthly_budget
        ltcg_this_month   = 0.0

        for fund in sorted(pool, key=lambda x: x.gain_ratio):
            if fund.current_value <= 0.01 or budget_remaining <= 0.01:
                continue

            redeem = min(fund.current_value, budget_remaining)

            # Proportional cost: redeeming X from a fund means
            # cost basis removed = X × (invested / current_value)
            cost_fraction   = fund.invested / fund.current_value if fund.current_value > 0 else 0
            cost_removed    = redeem * cost_fraction
            gain_realised   = redeem - cost_removed

            redemptions[fund.name]  = round(redeem, 2)
            fund.current_value     -= redeem
            fund.invested          -= cost_removed    # reduce cost basis proportionally
            fund.invested           = max(0, fund.invested)

            ltcg_this_month  += gain_realised
            budget_remaining -= redeem

        ltcg_fy         += ltcg_this_month
        pool_remaining   = sum(f.current_value for f in pool)

        schedule.append(MonthlyInstruction(
            month_num        = month_num,
            calendar_month   = cal_month,
            financial_year   = fy_label,
            redemptions      = redemptions,
            total_redemption = round(sum(redemptions.values()), 2),
            ltcg_this_month  = round(ltcg_this_month, 2),
            ltcg_fy_running  = round(ltcg_fy, 2),
            pool_remaining   = round(pool_remaining, 2),
            stp_injection    = round(sum(redemptions.values()), 2),
        ))

        current_date = (current_date + relativedelta(months=1)).replace(day=1)

        # Safety valve — shouldn't hit 120 months but prevents infinite loops
        if month_num >= 120:
            break

    # Tax saved = what you'd have paid vs what you'll pay
    total_ltcg_realised = sum(r.ltcg_this_month for r in schedule)
    tax_saved           = tax_if_exit_now - max(0, total_ltcg_realised - LTCG_ANNUAL_LIMIT) * 0.125

    return STPPlan(
        legacy_funds   = legacy_funds,
        schedule       = schedule,
        total_months   = month_num,
        v_legacy       = round(v_legacy, 2),
        monthly_stp    = round(v_legacy / month_num, 2) if month_num > 0 else 0,
        ltcg_saved     = round(tax_saved, 2),
        start_date     = start_date,
    )
