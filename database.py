"""
database.py — All SQLite read/write operations.

Tables:
  funds                — 4 target funds (static config)
  holdings             — unit counts per fund (updated after each SIP)
  portfolio_snapshots  — computed market values (units × NAV)
  legacy_funds         — funds being liquidated via STP
  stp_redemptions      — actual redemptions executed (Priority 1)
  sip_history          — salary SIP amounts over time (Step-Up Planner)
  sip_log              — monthly D_target log
"""

import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).parent / "portfolio.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db():
    """Create all tables. Safe to call on every startup (idempotent)."""
    conn = get_connection()
    cur  = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS funds (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            asset_class TEXT    NOT NULL,
            target_pct  REAL    NOT NULL,
            scheme_code INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS holdings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id     INTEGER NOT NULL REFERENCES funds(id),
            units       REAL    NOT NULL DEFAULT 0.0,
            updated_on  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id       INTEGER NOT NULL REFERENCES funds(id),
            recorded_on   TEXT    NOT NULL,
            current_value REAL    NOT NULL,
            nav           REAL,
            units_at_snap REAL,
            source        TEXT    NOT NULL DEFAULT 'manual'
        );

        CREATE TABLE IF NOT EXISTS legacy_funds (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            invested      REAL    NOT NULL,
            current_value REAL    NOT NULL,
            is_active     INTEGER NOT NULL DEFAULT 1,
            added_on      TEXT    NOT NULL
        );

        -- Priority 1: tracks actual redemptions you've executed at your broker
        CREATE TABLE IF NOT EXISTS stp_redemptions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            executed_on      TEXT    NOT NULL,   -- date you submitted the order
            month_num        INTEGER NOT NULL,   -- which month in the STP plan
            financial_year   TEXT    NOT NULL,   -- e.g. 'FY2026-27'
            fund_name        TEXT    NOT NULL,
            amount_redeemed  REAL    NOT NULL,
            ltcg_realised    REAL    NOT NULL,   -- gain portion = amount × gain_ratio
            notes            TEXT
        );

        -- Salary SIP history: one row per change in SIP amount
        -- This is the source of truth for the Step-Up Planner
        CREATE TABLE IF NOT EXISTS sip_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            effective_from  TEXT    NOT NULL,    -- date this SIP amount became active
            monthly_amount  REAL    NOT NULL,
            notes           TEXT                 -- e.g. 'Year 1 step-up', 'promotion'
        );

        CREATE TABLE IF NOT EXISTS sip_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_on   TEXT    NOT NULL,
            sip_amount  REAL    NOT NULL,
            stp_amount  REAL    NOT NULL DEFAULT 0.0,
            base_target REAL    NOT NULL
        );
    """)

    # Seed funds only if empty
    cur.execute("SELECT COUNT(*) FROM funds")
    if cur.fetchone()[0] == 0:
        seed_funds = [
            ("ICICI Pru BSE Sensex Index Fund",       "Sensex Index",  0.40, 120716),
            ("ICICI Pru Nifty Next 50 Index Fund",    "Nifty Next 50", 0.20, 120684),
            ("ICICI Pru Nifty Midcap 150 Index Fund", "Midcap 150",    0.20, 143492),
            ("DSP Small Cap Fund",                    "Small Cap",     0.20, 108066),
        ]
        cur.executemany(
            "INSERT INTO funds (name, asset_class, target_pct, scheme_code) VALUES (?,?,?,?)",
            seed_funds
        )
        today = str(date.today())
        cur.executemany(
            "INSERT INTO holdings (fund_id, units, updated_on) VALUES (?,?,?)",
            [(i+1, 0.0, today) for i in range(4)]
        )
        cur.executemany(
            """INSERT INTO portfolio_snapshots
               (fund_id, recorded_on, current_value, nav, units_at_snap, source)
               VALUES (?,?,?,?,?,?)""",
            [
                (1, today,  33949.00, None, None, 'manual'),
                (2, today,  61721.87, None, None, 'manual'),
                (3, today,  29086.98, None, None, 'manual'),
                (4, today,    146.89, None, None, 'manual'),
            ]
        )

    conn.commit()
    conn.close()


# ── Fund / Snapshot functions ─────────────────────────────────────────────────

def get_funds() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM funds ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_scheme_map() -> dict:
    return {f["id"]: f["scheme_code"] for f in get_funds()}


def get_latest_holdings() -> dict:
    conn = get_connection()
    rows = conn.execute("""
        SELECT h.fund_id, h.units FROM holdings h
        WHERE h.updated_on = (
            SELECT MAX(h2.updated_on) FROM holdings h2 WHERE h2.fund_id = h.fund_id
        )
    """).fetchall()
    conn.close()
    return {r["fund_id"]: r["units"] for r in rows}


def get_latest_snapshot() -> list:
    conn = get_connection()
    rows = conn.execute("""
        SELECT f.id, f.name, f.asset_class, f.target_pct, f.scheme_code,
               s.current_value, s.recorded_on, s.nav, s.units_at_snap, s.source
        FROM funds f
        JOIN portfolio_snapshots s ON s.fund_id = f.id
        WHERE s.id = (
            SELECT s2.id FROM portfolio_snapshots s2
            WHERE s2.fund_id = f.id
            ORDER BY s2.recorded_on DESC,
                     CASE s2.source WHEN 'cas' THEN 0 WHEN 'auto' THEN 1 ELSE 2 END,
                     s2.id DESC
            LIMIT 1
        )
        ORDER BY f.id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_auto_snapshot(fund_id: int, nav: float, units: float, on_date: str = None):
    on_date = on_date or str(date.today())
    conn    = get_connection()
    conn.execute(
        """INSERT INTO portfolio_snapshots
           (fund_id, recorded_on, current_value, nav, units_at_snap, source)
           VALUES (?,?,?,?,?,'auto')""",
        (fund_id, on_date, round(nav * units, 2), nav, units)
    )
    conn.commit()
    conn.close()


def save_manual_snapshot(fund_id: int, value: float, on_date: str = None):
    on_date = on_date or str(date.today())
    conn    = get_connection()
    conn.execute(
        """INSERT INTO portfolio_snapshots
           (fund_id, recorded_on, current_value, nav, units_at_snap, source)
           VALUES (?,?,?,NULL,NULL,'manual')""",
        (fund_id, on_date, value)
    )
    conn.commit()
    conn.close()


def update_holdings(fund_id: int, units: float, on_date: str = None):
    on_date = on_date or str(date.today())
    conn    = get_connection()
    conn.execute(
        "INSERT INTO holdings (fund_id, units, updated_on) VALUES (?,?,?)",
        (fund_id, units, on_date)
    )
    conn.commit()
    conn.close()


def save_cas_import(target_matches: dict, all_cas_holdings: dict = None, on_date: str = None):
    """
    Write CAS data for target funds AND update legacy fund market values.

    target_matches:  { fund_id: HoldingData } — your 4 target funds
    all_cas_holdings: { fund_id or name: HoldingData } — full CAS, used to
                      refresh legacy fund values (Priority 2)
    """
    on_date = on_date or str(date.today())
    conn    = get_connection()

    try:
        # ── Update target portfolio funds ─────────────────────────────────────
        for fund_id, holding in target_matches.items():
            conn.execute(
                "INSERT INTO holdings (fund_id, units, updated_on) VALUES (?,?,?)",
                (fund_id, holding.units, on_date)
            )
            conn.execute(
                """INSERT INTO portfolio_snapshots
                   (fund_id, recorded_on, current_value, nav, units_at_snap, source)
                   VALUES (?,?,?,?,?,'cas')""",
                (fund_id, on_date, holding.current_value, holding.nav, holding.units)
            )

        # ── Priority 2: update legacy fund market values from CAS ─────────────
        # Match by substring: if a legacy fund name appears in any CAS scheme name
        # we update its current_value. Invested value never changes — it's your
        # original cost basis, which doesn't move.
        if all_cas_holdings:
            legacy_funds = conn.execute(
                "SELECT id, name FROM legacy_funds WHERE is_active=1"
            ).fetchall()

            for lf in legacy_funds:
                lf_name_lower = lf["name"].lower()
                for cas_name, holding in all_cas_holdings.items():
                    # Match if either string contains a significant substring of the other
                    # Use first 20 chars of legacy fund name as the key — robust enough
                    key = lf_name_lower[:20]
                    if key in cas_name.lower():
                        conn.execute(
                            "UPDATE legacy_funds SET current_value=? WHERE id=?",
                            (holding.current_value, lf["id"])
                        )
                        break   # found match, move to next legacy fund

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# ── Legacy Fund functions ─────────────────────────────────────────────────────

def initialize_legacy_funds_table():
    """Idempotent — safe to call every startup."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS legacy_funds (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            invested      REAL    NOT NULL,
            current_value REAL    NOT NULL,
            is_active     INTEGER NOT NULL DEFAULT 1,
            added_on      TEXT    NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def get_legacy_funds() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM legacy_funds WHERE is_active=1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_legacy_fund(name: str, invested: float, current_value: float):
    conn = get_connection()
    conn.execute(
        "INSERT INTO legacy_funds (name, invested, current_value, added_on) VALUES (?,?,?,?)",
        (name, invested, current_value, str(date.today()))
    )
    conn.commit()
    conn.close()


def update_legacy_fund(fund_id: int, current_value: float):
    conn = get_connection()
    conn.execute(
        "UPDATE legacy_funds SET current_value=? WHERE id=?",
        (current_value, fund_id)
    )
    conn.commit()
    conn.close()


def delete_legacy_fund(fund_id: int):
    conn = get_connection()
    conn.execute("UPDATE legacy_funds SET is_active=0 WHERE id=?", (fund_id,))
    conn.commit()
    conn.close()


# ── Priority 1: STP Redemption Logging ───────────────────────────────────────

def log_stp_redemption(
    month_num:       int,
    financial_year:  str,
    fund_name:       str,
    amount_redeemed: float,
    ltcg_realised:   float,
    executed_on:     str  = None,
    notes:           str  = None,
):
    """
    Record an actual redemption executed at your broker.
    This is the mechanism that advances the STP plan from Month N to Month N+1.
    """
    executed_on = executed_on or str(date.today())
    conn        = get_connection()
    conn.execute(
        """INSERT INTO stp_redemptions
           (executed_on, month_num, financial_year, fund_name,
            amount_redeemed, ltcg_realised, notes)
           VALUES (?,?,?,?,?,?,?)""",
        (executed_on, month_num, financial_year, fund_name,
         amount_redeemed, ltcg_realised, notes)
    )
    conn.commit()
    conn.close()


def get_completed_stp_months() -> int:
    """
    Return the count of distinct month_nums that have been fully executed.
    This tells the STP engine how many months to skip in the schedule.

    Why distinct month_num?
    A single month may have redemptions from multiple funds (multiple rows).
    We count months, not rows.
    """
    conn  = get_connection()
    row   = conn.execute(
        "SELECT COUNT(DISTINCT month_num) as cnt FROM stp_redemptions"
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_ltcg_realised_this_fy() -> float:
    """
    Return total LTCG actually realised in the current financial year.
    Financial year = April 1 to March 31.
    This is the actual number to pass to compute_stp_plan() — not theoretical.
    """
    today    = date.today()
    fy_start = date(today.year, 4, 1) if today.month >= 4 else date(today.year - 1, 4, 1)

    conn = get_connection()
    row  = conn.execute(
        """SELECT COALESCE(SUM(ltcg_realised), 0) as total
           FROM stp_redemptions
           WHERE executed_on >= ?""",
        (str(fy_start),)
    ).fetchone()
    conn.close()
    return float(row["total"])


def get_stp_redemption_history() -> list:
    """Full redemption log, newest first."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM stp_redemptions ORDER BY executed_on DESC, id DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Salary SIP History ────────────────────────────────────────────────────────

def save_sip_entry(monthly_amount: float, effective_from: str = None, notes: str = None):
    """
    Record a new SIP amount. Call this when your salary SIP changes —
    either at start, or after each annual step-up.
    effective_from defaults to today if not provided.
    """
    effective_from = effective_from or str(date.today())
    conn           = get_connection()
    conn.execute(
        "INSERT INTO sip_history (effective_from, monthly_amount, notes) VALUES (?,?,?)",
        (effective_from, monthly_amount, notes)
    )
    conn.commit()
    conn.close()


def get_current_sip() -> float:
    """
    Return the most recently recorded monthly SIP amount.
    Returns 0.0 if no SIP has been recorded yet.
    """
    conn = get_connection()
    row  = conn.execute(
        "SELECT monthly_amount FROM sip_history ORDER BY effective_from DESC, id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return float(row["monthly_amount"]) if row else 0.0


def get_sip_history() -> list:
    """Full SIP history, oldest first — used by the Step-Up Planner."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM sip_history ORDER BY effective_from ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_sip(sip_amount: float, stp_amount: float = 0.0):
    conn = get_connection()
    conn.execute(
        "INSERT INTO sip_log (logged_on, sip_amount, stp_amount, base_target) VALUES (?,?,?,?)",
        (str(date.today()), sip_amount, stp_amount, sip_amount + stp_amount)
    )
    conn.commit()
    conn.close()
