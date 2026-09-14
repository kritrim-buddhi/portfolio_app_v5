# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
streamlit run app.py
```

Install dependencies first: `pip install -r requirements.txt`

## Architecture

This is a personal India mutual fund portfolio tracker. It answers one question per monthly SIP cycle: "what do I invest this month, and what do I sell?"

**Entry point:** `app.py` — Streamlit single-page app with 4 tabs (This Month / Portfolio / Migration / Journey). All data is loaded once at the top of the module and shared across tabs.

**Database:** `database.py` — SQLite (`portfolio.db`) via raw `sqlite3`. All reads and writes go through functions here. The schema seeds 7 hardcoded target funds on first run (15/20/15/15/25/5/5 allocation: BSE Sensex / Nifty Next 50 / Nifty Midcap 150 / Invesco Smallcap / PPFAS Flexi Cap / Nippon Power & Infra / Gold Savings Fund).

**Engine modules** (`engine/`) are pure functions with no database calls and no Streamlit imports. They take plain Python objects and return dataclasses:

| Module | Key function | Input → Output |
|--------|-------------|----------------|
| `drift.py` | `analyze_drift()` | snapshot dicts → `List[FundDriftResult]` |
| `allocator.py` | `compute_allocation()` | monthly target + drift results → `List[AllocationOrder]` |
| `stp.py` | `compute_stp_plan()` | legacy funds + salary SIP → `STPPlan` with month-by-month schedule |
| `nav_fetcher.py` | `fetch_all_navs()` | scheme code map → NAV results from `mfapi.in` |
| `cas_parser.py` | `parse_cas_excel()` | MF Central Excel upload → target + all holdings |
| `timeline.py` | `get_journey_status()` | start date → dates for next drift check / step-up (not yet wired into app.py) |

`cas_excel_parser.py` is an alternative parser using `rapidfuzz` fuzzy matching. It is **not** imported by the app — `cas_parser.py` (substring matching) is the active one.

## Data flow

```
Portfolio data entry (3 paths, priority order in get_latest_snapshot):
  1. CAS import (MF Central Excel → cas_parser → save_cas_import)     ← most authoritative
  2. Auto-fetch (mfapi.in NAV × stored units → save_auto_snapshot)
  3. Manual rupee entry (sidebar → save_manual_snapshot)

Every tab session:
  get_latest_snapshot() → analyze_drift() → compute_allocation()
                                          → compute_stp_plan() (if legacy funds exist)
```

## Key domain concepts

- **Financial year**: April 1 – March 31. LTCG headroom resets on April 1.
- **LTCG limit**: ₹1,25,000 tax-free long-term capital gains per FY. The STP engine never exceeds this.
- **STP (Systematic Transfer Plan)**: Monthly redemption from legacy (old/active-managed) funds. Proceeds are injected into the target portfolio alongside the salary SIP. Tracked via `stp_redemptions` table; `get_completed_stp_months()` advances the schedule.
- **Drift rule**: 10% *relative* deviation triggers status change. A 40% target fund drifts if actual allocation moves outside [36%, 44%]. Overweight funds receive zero inflows; their share is redistributed proportionally to non-overweight funds.
- **SIP pause toggle**: Session-only state (`st.session_state["sip_paused"]`). Never writes to DB. Lets users skip a month without changing their saved default.

## Adding a new fund

The 7 target funds are hardcoded in two places:
1. `database.py:initialize_db()` — seeds `funds` table and initial snapshots
2. `engine/cas_parser.py` — `FUND_MATCH_STRINGS` and `FUND_AMC_FILTER` dicts for CAS matching

To change allocations, update `target_pct` in the seed data and re-initialize (or run a migration query directly on `portfolio.db`).
