"""
app.py — Portfolio Engine UI.

Design: Refined utilitarian. Monospaced numbers, amber accent, near-black ground.
Every screen answers "what do I do today" before explaining why.

Tab structure:
  🎯 This Month  — action-first: what to invest, what to sell
  📊 Portfolio   — full drift picture for the curious
  🔄 Migration   — STP tracker, LTCG progress
  📈 Journey     — SIP history + 10-year step-up chart
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date

import database as db
from engine.drift import analyze_drift
from engine.allocator import compute_allocation, compute_step_up
from engine.nav_fetcher import fetch_all_navs
from engine.cas_parser import parse_cas_excel, extract_my_funds, CASParseError
from engine.stp import LegacyFund, compute_stp_plan

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Portfolio Engine",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design system ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;700&family=DM+Sans:wght@300;400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

/* ── Metric numbers always mono ── */
[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
}
[data-testid="stMetricLabel"] {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.70rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.09em !important;
    text-transform: uppercase !important;
    opacity: 0.55 !important;
}

/* ── Action card ── */
.action-card {
    background: #0d0f14;
    border: 1px solid #1e2330;
    border-radius: 12px;
    padding: 24px 28px;
    margin-bottom: 16px;
    position: relative;
    overflow: hidden;
}
.action-card::before {
    content: '';
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 3px;
    background: #f59e0b;
    border-radius: 3px 0 0 3px;
}
.action-card.muted::before { background: #374151; }
.action-card .card-eyebrow {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #f59e0b;
    margin-bottom: 10px;
}
.action-card.muted .card-eyebrow { color: #4b5563; }
.action-card .card-amount {
    font-family: 'JetBrains Mono', monospace;
    font-size: 2.2rem;
    font-weight: 700;
    color: #f8fafc;
    letter-spacing: -0.03em;
    line-height: 1;
    margin-bottom: 6px;
}
.action-card .card-sub {
    font-size: 0.82rem;
    color: #64748b;
    font-family: 'DM Sans', sans-serif;
}
.action-card .card-sub b { color: #94a3b8; font-weight: 500; }

/* ── Fund instruction row ── */
.fund-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 11px 0;
    border-bottom: 1px solid #111827;
    gap: 12px;
}
.fund-row:last-child { border-bottom: none; }
.fund-row .fn {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.88rem;
    color: #cbd5e1;
    flex: 1;
    min-width: 0;
}
.fund-row .fa {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.0rem;
    font-weight: 600;
    color: #f1f5f9;
    white-space: nowrap;
}
.fund-row .fa.zero {
    color: #374151;
    text-decoration: line-through;
}
.fund-row .tag {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 100px;
    white-space: nowrap;
}
.tag-paused   { background: #1c1f26; color: #4b5563; border: 1px solid #1f2937; }
.tag-buy      { background: #052e16; color: #4ade80; border: 1px solid #14532d; }
.tag-boosted  { background: #1c1403; color: #fbbf24; border: 1px solid #451a03; }

/* ── LTCG bar ── */
.ltcg-bar-wrap {
    background: #111827;
    border-radius: 100px;
    height: 6px;
    margin: 8px 0 4px;
    overflow: hidden;
}
.ltcg-bar-fill {
    height: 100%;
    border-radius: 100px;
    background: linear-gradient(90deg, #f59e0b, #ef4444);
    transition: width 0.6s ease;
}
.ltcg-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #6b7280;
}

/* ── Section header ── */
.sect-head {
    font-family: 'Syne', sans-serif;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #374151;
    padding: 18px 0 10px;
    border-top: 1px solid #111827;
    margin-top: 4px;
}
.sect-head:first-child { border-top: none; padding-top: 4px; }

/* ── Migration month badge ── */
.month-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #0d0f14;
    border: 1px solid #1e2330;
    border-radius: 8px;
    padding: 6px 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    color: #94a3b8;
    margin-bottom: 16px;
}
.month-badge .mbnum {
    color: #f59e0b;
    font-weight: 700;
    font-size: 0.95rem;
}

/* ── Drift bar ── */
.drift-wrap {
    background: #0d0f14;
    border: 1px solid #1e2330;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
}
.drift-wrap .dname {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.8rem;
    color: #94a3b8;
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
}
.drift-wrap .dname .dval {
    font-family: 'JetBrains Mono', monospace;
    color: #f1f5f9;
    font-weight: 600;
}
.drift-track {
    background: #111827;
    border-radius: 100px;
    height: 8px;
    position: relative;
    margin-bottom: 6px;
}
.drift-fill {
    height: 100%;
    border-radius: 100px;
    position: absolute;
    left: 0; top: 0;
}
.drift-fill.over  { background: #dc2626; }
.drift-fill.under { background: #2563eb; }
.drift-fill.ok    { background: #16a34a; }
.drift-target-line {
    position: absolute;
    top: -3px; bottom: -3px;
    width: 2px;
    background: #f59e0b;
    border-radius: 2px;
}
.drift-bounds {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem;
    color: #374151;
    display: flex;
    justify-content: space-between;
}

/* ── Journey bar item ── */
.journey-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 0;
    border-bottom: 1px solid #0d0f14;
}
.journey-row:last-child { border-bottom: none; }
.journey-row .jlabel {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.8rem;
    color: #6b7280;
    width: 52px;
    flex-shrink: 0;
}
.journey-row .jbar-wrap {
    flex: 1;
    background: #111827;
    border-radius: 100px;
    height: 6px;
    overflow: hidden;
}
.journey-row .jbar-fill {
    height: 100%;
    border-radius: 100px;
    background: #f59e0b;
}
.journey-row .jamt {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    color: #94a3b8;
    white-space: nowrap;
    width: 90px;
    text-align: right;
    flex-shrink: 0;
}

/* ── Plain language callout ── */
.plain-note {
    background: #0a0d13;
    border: 1px solid #1e2330;
    border-radius: 8px;
    padding: 12px 16px;
    font-family: 'DM Sans', sans-serif;
    font-size: 0.83rem;
    color: #64748b;
    line-height: 1.6;
    margin: 12px 0;
}
.plain-note b { color: #94a3b8; font-weight: 500; }
.plain-note .hl { color: #f59e0b; font-weight: 600; }

/* ── Tab styling ── */
[data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 1px solid #1e2330 !important;
}
[data-baseweb="tab"] {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.03em !important;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: #080a0f;
    border-right: 1px solid #111827;
}
</style>
""", unsafe_allow_html=True)

# ── Bootstrap ─────────────────────────────────────────────────────────────────
db.initialize_db()
db.initialize_legacy_funds_table()

# ── Helpers ───────────────────────────────────────────────────────────────────
def inr(v):      return f"₹{v:,.0f}"
def pct(v):      return f"{v*100:.1f}%"
def fdate(d):    return pd.to_datetime(d).strftime("%d %b %Y") if d else "—"

FUND_SHORT = {
    "ICICI Pru BSE Sensex Index Fund":       "BSE Sensex",
    "ICICI Pru Nifty Next 50 Index Fund":    "Nifty Next 50",
    "ICICI Pru Nifty Midcap 150 Index Fund": "Nifty Midcap 150",
    "Invesco India Smallcap Fund":           "Invesco Smallcap",
    "Parag Parikh Flexi Cap Fund":           "PPFAS Flexi Cap",
    "Nippon India Power & Infra Fund":       "Nippon Power & Infra",
    "ICICI Prudential Gold ETF":             "ICICI Gold ETF",
}

SOURCE_MAP = {"cas": "📄 CAS", "auto": "📡 Auto", "manual": "✏️ Manual"}

def short(name): return FUND_SHORT.get(name, name.replace("ICICI Pru ", "").replace(" Index Fund", ""))

def fund_rows_html(orders, stp_injection=0):
    """Render the fund instruction list as clean HTML."""
    rows = ""
    for o in orders:
        fname = short(o.name)
        if o.amount == 0:
            tag   = '<span class="tag tag-paused">Paused — overweight</span>'
            amt   = f'<span class="fa zero">{inr(0)}</span>'
        elif o.is_redirected:
            tag   = '<span class="tag tag-boosted">Extra allocation</span>'
            amt   = f'<span class="fa">{inr(o.amount)}</span>'
        else:
            tag   = '<span class="tag tag-buy">Invest</span>'
            amt   = f'<span class="fa">{inr(o.amount)}</span>'
        rows += f"""
        <div class="fund-row">
            <span class="fn">{fname}</span>
            {tag}
            {amt}
        </div>"""
    return rows

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — data entry only
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### ◈ Portfolio Engine")
    st.caption("20-Year Retirement · Index-First · New Tax Regime")
    st.divider()

    # ── SIP amount ────────────────────────────────────────────────────────────
    current_sip_db = db.get_current_sip()
    st.markdown("**Monthly SIP**")

    # Pause toggle — session-only, never writes to DB
    # Separates "my default SIP" from "am I investing this month"
    sip_paused = st.toggle(
        "Pause SIP this month",
        value=st.session_state.get("sip_paused", False),
        key="sip_paused",
        help="Temporarily skip this month's SIP without changing your saved default. "
             "Resets automatically when you close the app."
    )

    monthly_sip = st.number_input(
        "Default monthly amount (₹)",
        min_value=0, max_value=1_000_000,
        value=int(current_sip_db) if current_sip_db > 0 else 50784,
        step=500,
        disabled=sip_paused,
        help="Your intended monthly SIP. Saved permanently to track step-up history."
    )

    if sip_paused:
        st.caption("⏸ SIP paused this month. Default ₹{:,.0f} unchanged.".format(
            current_sip_db if current_sip_db > 0 else monthly_sip
        ))

    sip_note = st.text_input(
        "Note (optional)", placeholder="e.g. Year 2 step-up",
        label_visibility="collapsed",
        disabled=sip_paused,
    )
    if st.button("Save SIP", use_container_width=True, disabled=sip_paused):
        db.save_sip_entry(monthly_sip, notes=sip_note or None)
        st.success(f"Saved {inr(monthly_sip)}/month")
        st.rerun()

    st.divider()

    # ── CAS import ────────────────────────────────────────────────────────────
    st.markdown("**Import Portfolio Data**")
    st.caption("MF Central → Reports → CAS → Excel")
    uploaded = st.file_uploader("CAS Excel", type=["xlsx"], label_visibility="collapsed")
    if uploaded:
        if st.button("Import", type="primary", use_container_width=True):
            with st.spinner("Reading…"):
                try:
                    result      = parse_cas_excel(uploaded)
                    my_ids      = [f["id"] for f in db.get_funds()]
                    matched, _  = extract_my_funds(result, my_ids)
                    if matched:
                        db.save_cas_import(matched, result.get("all", {}))
                        st.success(f"Imported {len(matched)} funds")
                        st.rerun()
                    else:
                        st.error("No matching funds found.")
                except CASParseError as e:
                    st.error(str(e))

    st.divider()

    # ── Manual fallback — collapsed by default ────────────────────────────────
    with st.expander("Manual entry (fallback)"):
        funds   = db.get_funds()
        cur_h   = db.get_latest_holdings()
        new_u   = {}
        for f in funds:
            new_u[f["id"]] = st.number_input(
                short(f["name"]), min_value=0.0,
                value=float(cur_h.get(f["id"], 0.0)),
                step=0.001, format="%.3f", key=f"u_{f['id']}",
            )
        if st.button("Fetch NAV + Save", use_container_width=True):
            navs = fetch_all_navs(db.get_scheme_map())
            n = 0
            for fid, units in new_u.items():
                if units > 0 and fid in navs:
                    db.update_holdings(fid, units)
                    db.save_auto_snapshot(fid, navs[fid].nav, units)
                    n += 1
            if n: st.success(f"Saved {n} funds"); st.rerun()

        st.markdown("**Or enter rupee values**")
        for f in funds:
            v = st.number_input(short(f["name"]), min_value=0.0, value=0.0,
                                step=100.0, key=f"m_{f['id']}")
        if st.button("Save values", use_container_width=True):
            for f in funds:
                v = st.session_state.get(f"m_{f['id']}", 0.0)
                if v > 0:
                    db.save_manual_snapshot(f["id"], v)
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# DATA LAYER — computed once, shared across all tabs
# ══════════════════════════════════════════════════════════════════════════════
# Respect the pause toggle — session state overrides the DB default.
# sip_paused is True when the toggle is on. In that case active SIP = 0
# for this session only. The DB default is untouched.
_sip_default     = db.get_current_sip() or monthly_sip
_sip_paused      = st.session_state.get("sip_paused", False)
monthly_sip_live = 0.0 if _sip_paused else _sip_default
snapshots        = db.get_latest_snapshot()
total_portfolio  = sum(s["current_value"] for s in snapshots)
drift_results    = analyze_drift(snapshots)
legacy_funds_db  = db.get_legacy_funds()
completed_months = db.get_completed_stp_months()
ltcg_fy          = db.get_ltcg_realised_this_fy()
sip_history      = db.get_sip_history()

stp_plan      = None
stp_injection = 0.0
this_month_stp = None

if legacy_funds_db:
    legacy_objs   = [LegacyFund(f["name"], f["invested"], f["current_value"])
                     for f in legacy_funds_db]
    stp_plan      = compute_stp_plan(legacy_objs, monthly_sip_live,
                                     ltcg_already_realised_this_fy=ltcg_fy)
    idx = completed_months
    if stp_plan.schedule and idx < len(stp_plan.schedule):
        this_month_stp = stp_plan.schedule[idx]
        stp_injection  = this_month_stp.stp_injection

base_target  = monthly_sip_live + stp_injection
alloc_orders = compute_allocation(base_target, drift_results)

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab_today, tab_port, tab_mig, tab_journey = st.tabs([
    "🎯  This Month",
    "📊  Portfolio",
    "🔄  Migration",
    "📈  Journey",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — THIS MONTH (action-first)
# ─────────────────────────────────────────────────────────────────────────────
with tab_today:

    # ── Invest card ──────────────────────────────────────────────────────────
    migration_note = (f"<b>{inr(monthly_sip_live)}</b> salary "
                      f"+ <b>{inr(stp_injection)}</b> from legacy fund sale"
                      if stp_injection > 0
                      else f"<b>{inr(monthly_sip_live)}</b> salary SIP")

    any_over  = any(d.status == "OVERWEIGHT" for d in drift_results)
    any_under = any(d.status == "UNDERWEIGHT" for d in drift_results)

    if any_over:
        drift_note = "Some funds are over-invested — their share is being redirected to the ones that need it. No selling required."
    else:
        drift_note = "All funds are balanced. Your portfolio is tracking its target allocation as planned."

    if monthly_sip_live == 0 and stp_injection > 0:
        # Migration-only phase: SIP paused, only STP injection being invested
        step1_eyebrow = "Step 1 — Invest migration proceeds"
        step1_sub     = (f"Salary SIP is paused. Investing <b>{inr(stp_injection)}</b> "
                         f"from legacy fund sale into your target portfolio.")
    elif monthly_sip_live == 0 and stp_injection == 0:
        # Nothing to invest this month
        step1_eyebrow = "No investment this month"
        step1_sub     = "Both SIP and migration are inactive. Set your SIP in the sidebar when ready."
    else:
        step1_eyebrow = "Step 1 — Invest this month"
        step1_sub     = migration_note

    st.markdown(f"""
    <div class="action-card{' muted' if base_target == 0 else ''}">
        <div class="card-eyebrow">{step1_eyebrow}</div>
        <div class="card-amount">{inr(base_target) if base_target > 0 else '—'}</div>
        <div class="card-sub">{step1_sub}</div>
    </div>
    """, unsafe_allow_html=True)

    # Fund breakdown — only show if there is money to allocate
    if base_target > 0:
        st.markdown('<div class="sect-head">Send it here</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div style="background:#0d0f14;border:1px solid #1e2330;border-radius:10px;padding:4px 20px 12px;">'
            f'{fund_rows_html(alloc_orders, stp_injection)}</div>',
            unsafe_allow_html=True
        )

    if any_over:
        st.markdown(
            '<div class="plain-note">💡 <b>Why are some funds paused?</b> '
            'When a fund grows faster than the others, it becomes a bigger slice of '
            'your portfolio than intended. Instead of selling (which triggers tax), '
            'we simply stop adding money to it until the others catch up.</div>',
            unsafe_allow_html=True
        )

    # ── Sell card (only if migration active) ─────────────────────────────────
    if this_month_stp:
        st.markdown('<div class="sect-head">Step 2 — Sell from old funds</div>',
                    unsafe_allow_html=True)

        sell_fund_name = list(this_month_stp.redemptions.keys())[0] \
                         if this_month_stp.redemptions else "—"
        sell_short     = sell_fund_name[:45]

        headroom_left = max(0, 125_000 - this_month_stp.ltcg_fy_running)
        ltcg_pct_used = min(this_month_stp.ltcg_fy_running / 125_000, 1.0)
        ltcg_pct_str  = f"{ltcg_pct_used*100:.0f}"

        st.markdown(f"""
        <div class="action-card">
            <div class="card-eyebrow">Month {this_month_stp.month_num} of {stp_plan.total_months} · {this_month_stp.calendar_month}</div>
            <div class="card-amount">{inr(this_month_stp.total_redemption)}</div>
            <div class="card-sub">Redeem from <b>{sell_short}</b><br>
            Proceeds go straight into Step 1 above</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        <div class="plain-note">
            <span class="hl">Tax impact: ₹0</span> — 
            India allows ₹1,25,000 in annual investment profits tax-free.
            This redemption uses <b>{inr(this_month_stp.ltcg_this_month)}</b> of that allowance.
            <div class="ltcg-bar-wrap" style="margin-top:10px;">
                <div class="ltcg-bar-fill" style="width:{ltcg_pct_str}%;"></div>
            </div>
            <div class="ltcg-label">{inr(this_month_stp.ltcg_fy_running)} used · 
            {inr(headroom_left)} remaining this year</div>
        </div>
        """, unsafe_allow_html=True)

        # Mark as done form
        with st.expander("✅ Mark this month as done"):
            st.caption("After you submit the redemption at your broker, record it here.")
            with st.form("exec_today"):
                exec_date  = st.date_input("Date executed", date.today())
                exec_notes = st.text_input("Notes (optional)",
                                           placeholder="e.g. done via Kuvera")
                actual_amts = {}
                st.caption("Confirm amounts (edit if broker rounded differently):")
                for fname, amt in this_month_stp.redemptions.items():
                    if amt > 0:
                        actual_amts[fname] = st.number_input(
                            fname[:50], min_value=0.0,
                            value=float(amt), step=10.0,
                            key=f"ex_{fname[:12]}"
                        )
                if st.form_submit_button("Confirm execution", type="primary"):
                    for fname, amount in actual_amts.items():
                        if amount <= 0: continue
                        lf = next((f for f in legacy_funds_db
                                   if fname[:15].lower() in f["name"].lower()), None)
                        gr = ((lf["current_value"] - lf["invested"]) / lf["current_value"]
                              if lf and lf["current_value"] > 0 else 0.52)
                        db.log_stp_redemption(
                            month_num       = this_month_stp.month_num,
                            financial_year  = this_month_stp.financial_year,
                            fund_name       = fname,
                            amount_redeemed = amount,
                            ltcg_realised   = round(amount * gr, 2),
                            executed_on     = str(exec_date),
                            notes           = exec_notes or None,
                        )
                    st.success(f"Month {this_month_stp.month_num} recorded. See Migration tab for full history.")
                    st.rerun()

    elif legacy_funds_db and completed_months >= len(stp_plan.schedule if stp_plan else []):
        st.markdown("""
        <div class="action-card muted">
            <div class="card-eyebrow">Migration complete</div>
            <div class="card-amount" style="font-size:1.4rem;color:#4b5563;">All legacy funds exited</div>
            <div class="card-sub">No more selling required. Just invest monthly.</div>
        </div>
        """, unsafe_allow_html=True)

    # ── Portfolio summary strip ───────────────────────────────────────────────
    st.markdown('<div class="sect-head">Portfolio at a glance</div>',
                unsafe_allow_html=True)
    g1, g2, g3 = st.columns(3)
    g1.metric("Total Portfolio",   inr(total_portfolio))
    sip_display = ("⏸ Paused" if _sip_paused
                   else inr(monthly_sip_live) if monthly_sip_live > 0
                   else "Not set")
    g2.metric("Monthly SIP", sip_display,
              delta=f"Default: {inr(_sip_default)}" if _sip_paused else None,
              delta_color="off")
    sources = set(s["source"] for s in snapshots)
    src_label = "Registrar data" if "cas" in sources else \
                "Auto-fetched" if sources == {"auto"} else "Manual entry"
    g3.metric("Data Source", src_label)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — PORTFOLIO (full drift picture)
# ─────────────────────────────────────────────────────────────────────────────
with tab_port:
    st.markdown(f"### Portfolio — {fdate(str(date.today()))}")
    st.caption("The full picture. Each fund's actual weight vs its target.")

    # ── Drift visualiser ──────────────────────────────────────────────────────
    # Shared scale across all funds so target markers and fills are
    # comparable bar-to-bar — a 25% target sits further right than a 5%
    # target. A per-fund scale would cancel target_pct out of the target
    # marker's position, making every marker land at the same spot.
    # Scale must cover the largest of either target or actual — basing it on
    # target alone clips any fund whose actual weight overshoots target×1.5
    # (common right after a reallocation), making it indistinguishable from
    # a fund that's even more overweight.
    max_target_w = max(dr.target_pct for dr in drift_results) * 100
    max_actual_w = max(dr.actual_pct for dr in drift_results) * 100
    shared_scale = max(max_target_w, max_actual_w) * 1.2

    for d in drift_results:
        snap      = next(s for s in snapshots if s["id"] == d.fund_id)
        fname     = short(d.name)
        actual_w  = d.actual_pct * 100
        target_w  = d.target_pct * 100
        lower_w   = d.lower_bound * 100
        upper_w   = d.upper_bound * 100

        fill_w    = min(actual_w / shared_scale * 100, 100)
        target_x  = target_w / shared_scale * 100

        fill_cls  = "over" if d.status == "OVERWEIGHT" else \
                    "under" if d.status == "UNDERWEIGHT" else "ok"

        units_str = f"{snap['units_at_snap']:.3f} units" \
                    if snap.get("units_at_snap") else ""
        nav_str   = f"NAV ₹{snap['nav']:.2f}" if snap.get("nav") else ""
        src_str   = SOURCE_MAP.get(snap["source"], "")

        status_plain = {
            "OVERWEIGHT":  "Over target — SIP paused",
            "UNDERWEIGHT": "Under target — getting extra",
            "ON_TARGET":   "On target",
        }.get(d.status, d.status)

        st.markdown(f"""
        <div class="drift-wrap">
            <div class="dname">
                <span>{fname} <small style="color:#4b5563;font-size:0.75em">
                    {units_str} · {nav_str} · {src_str}
                </small></span>
                <span class="dval">{inr(d.current_value)}</span>
            </div>
            <div class="drift-track">
                <div class="drift-fill {fill_cls}" style="width:{fill_w:.1f}%;"></div>
                <div class="drift-target-line" style="left:{target_x:.1f}%;"></div>
            </div>
            <div class="drift-bounds">
                <span>Low {lower_w:.1f}%</span>
                <span style="color:#f59e0b;">Target {target_w:.0f}% — 
                    Actual <b>{actual_w:.1f}%</b> — {status_plain}</span>
                <span>High {upper_w:.1f}%</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # ── Allocation table ──────────────────────────────────────────────────────
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown("**This month's allocation detail**")
        tbl = [{
            "Fund":          short(o.name),
            "Target":        pct(o.target_pct),
            "Actual":        pct(d.actual_pct),
            "This month":    inr(o.amount),
            "Status":        {
                "OVERWEIGHT":  "Paused",
                "UNDERWEIGHT": "Getting extra",
                "ON_TARGET":   "Normal",
            }.get(o.drift_status, o.drift_status),
        } for o, d in zip(alloc_orders, drift_results)]
        st.dataframe(pd.DataFrame(tbl), use_container_width=True, hide_index=True)

    with c2:
        st.markdown("**Totals**")
        st.metric("Portfolio Value",  inr(total_portfolio))
        st.metric("Base Target",      inr(base_target))
        st.metric("Total Allocated",  inr(sum(o.amount for o in alloc_orders)))


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — MIGRATION
# ─────────────────────────────────────────────────────────────────────────────
with tab_mig:
    st.markdown("### Legacy Fund Migration")
    st.caption(
        "Exiting old funds slowly over ~3 years to stay within "
        "India's ₹1,25,000 annual tax-free profit limit."
    )

    if not legacy_funds_db:
        st.info("No legacy funds added. Use the form below to add funds you want to exit.")
    else:
        # ── Progress ──────────────────────────────────────────────────────────
        if stp_plan:
            total_months = stp_plan.total_months
            done_pct     = completed_months / total_months if total_months > 0 else 0
            total_gain   = sum(f["current_value"] - f["invested"] for f in legacy_funds_db)
            tax_if_now   = max(0, total_gain - 125_000) * 0.125

            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Legacy Pool",         inr(stp_plan.v_legacy))
            p2.metric("Exit Progress",
                      f"{completed_months} / {total_months} months",
                      delta=f"{done_pct*100:.0f}% complete",
                      delta_color="off")
            p3.metric("Tax Saved",           inr(tax_if_now),
                      delta="vs immediate exit",
                      delta_color="normal")
            p4.metric("LTCG Used This FY",   inr(ltcg_fy),
                      delta=f"{inr(max(0, 125_000-ltcg_fy))} headroom left",
                      delta_color="off")

            # Progress bar
            st.progress(done_pct, text=f"Month {completed_months} of {total_months} complete")

        st.divider()

        # ── Legacy pool table ──────────────────────────────────────────────────
        st.markdown("**Funds being exited** (sorted by exit priority)")
        sorted_lf = sorted(
            legacy_funds_db,
            key=lambda x: (x["current_value"]-x["invested"])/x["current_value"]
            if x["current_value"] > 0 else 0
        )
        lf_rows = []
        for i, f in enumerate(sorted_lf):
            gain = f["current_value"] - f["invested"]
            gr   = gain / f["current_value"] if f["current_value"] > 0 else 0
            lf_rows.append({
                "Exit order":    f"#{i+1}",
                "Fund":          f["name"][:45],
                "Invested":      inr(f["invested"]),
                "Current value": inr(f["current_value"]),
                "Profit":        inr(gain),
                "Profit %":      pct(gr),
            })
        st.dataframe(pd.DataFrame(lf_rows), use_container_width=True, hide_index=True)

        st.markdown(
            '<div class="plain-note">💡 <b>Why this order?</b> '
            'Funds with a lower profit percentage exit first. This lets you move '
            'more money out each year while staying under the tax limit.</div>',
            unsafe_allow_html=True
        )

        st.divider()

        # ── Full schedule ──────────────────────────────────────────────────────
        if stp_plan:
            st.markdown("**Full exit schedule**")
            fy_groups: dict = {}
            for r in stp_plan.schedule:
                fy_groups.setdefault(r.financial_year, []).append(r)

            for fy, months in fy_groups.items():
                done_in = sum(1 for m in months if m.month_num <= completed_months)
                fy_ltcg = sum(m.ltcg_this_month for m in months)
                fy_rdm  = sum(m.total_redemption for m in months)
                with st.expander(
                    f"{fy}  ·  Sell {inr(fy_rdm)}  ·  "
                    f"Tax-free profit {inr(fy_ltcg)} / ₹1,25,000  ·  "
                    f"{done_in}/{len(months)} months done"
                ):
                    rows = [{
                        "Month":   ("✅ " if r.month_num <= completed_months else "")
                                   + r.calendar_month,
                        "Sell":    inr(r.total_redemption),
                        "Profit":  inr(r.ltcg_this_month),
                        "FY Total":inr(r.ltcg_fy_running),
                        "Pool":    inr(r.pool_remaining),
                        **{n[:18]: inr(a) for n,a in r.redemptions.items() if a > 0}
                    } for r in months]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Redemption history ────────────────────────────────────────────────────
    history = db.get_stp_redemption_history()
    if history:
        st.divider()
        st.markdown("**What you've sold so far**")
        hist_rows = [{
            "Date":    fdate(r["executed_on"]),
            "Month":   r["month_num"],
            "Fund":    r["fund_name"][:38],
            "Sold":    inr(r["amount_redeemed"]),
            "Profit":  inr(r["ltcg_realised"]),
            "Notes":   r["notes"] or "—",
        } for r in history]
        st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)

    st.divider()

    # ── Add / remove legacy fund ───────────────────────────────────────────────
    with st.expander("➕ Add a fund to exit"):
        ca, cb, cc = st.columns([3, 1, 1])
        nn  = ca.text_input("Fund name", placeholder="e.g. Axis ELSS Tax Saver Fund")
        ni  = cb.number_input("Amount invested (₹)", min_value=0.0, step=100.0, key="ni")
        nv  = cc.number_input("Current value (₹)", min_value=0.0, step=100.0, key="nv")
        if st.button("Add fund"):
            if nn and ni > 0 and nv > 0:
                db.save_legacy_fund(nn, ni, nv)
                st.success(f"Added: {nn}")
                st.rerun()
            else:
                st.warning("Fill in all three fields.")

    with st.expander("Remove a fund"):
        st.caption("Type the name exactly to confirm.")
        rem = st.text_input("Fund name", key="rem_inp")
        for f in legacy_funds_db:
            if rem.strip().lower() == f["name"].strip().lower():
                if st.button(f"Confirm: remove {f['name'][:40]}"):
                    db.delete_legacy_fund(f["id"])
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — JOURNEY
# ─────────────────────────────────────────────────────────────────────────────
with tab_journey:
    st.markdown("### Investment Journey")
    st.caption("Your SIP history and where you're headed.")

    # ── Actual history ────────────────────────────────────────────────────────
    if sip_history:
        st.markdown("**What you've invested so far**")
        hist_rows = [{
            "From":        fdate(r["effective_from"]),
            "Monthly SIP": inr(r["monthly_amount"]),
            "Annual SIP":  inr(r["monthly_amount"] * 12),
            "Note":        r["notes"] or "—",
        } for r in sip_history]
        st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)

        if len(sip_history) > 1:
            prev  = sip_history[-2]["monthly_amount"]
            curr  = sip_history[-1]["monthly_amount"]
            delta = (curr - prev) / prev * 100
            st.caption(f"Last step-up: {delta:+.1f}% · {inr(prev)} → {inr(curr)}/month")
    else:
        st.info("Save your current SIP in the sidebar to start tracking history.")

    st.divider()

    # ── 10-year projection chart ──────────────────────────────────────────────
    st.markdown("**10-year contribution projection** — 10% annual step-up")
    base    = monthly_sip_live or monthly_sip
    data    = []
    cur_sip = base
    cum     = 0
    max_ann = 0
    for yr in range(1, 11):
        ann   = cur_sip * 12
        cum  += ann
        max_ann = max(max_ann, ann)
        data.append({"yr": yr, "label": f"Yr {yr}",
                     "monthly": cur_sip, "annual": ann, "cum": cum})
        cur_sip = compute_step_up(cur_sip)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[d["label"] for d in data],
        y=[d["annual"] for d in data],
        name="Annual SIP",
        marker_color="#f59e0b",
        marker_line_width=0,
        hovertemplate="<b>%{x}</b><br>Annual: ₹%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=[d["label"] for d in data],
        y=[d["cum"] for d in data],
        name="Total contributed",
        line=dict(color="#60a5fa", width=2),
        yaxis="y2",
        hovertemplate="<b>%{x}</b><br>Total: ₹%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans"),
        xaxis=dict(showgrid=False,
                   tickfont=dict(family="JetBrains Mono", size=11, color="#6b7280")),
        yaxis=dict(showgrid=True, gridcolor="#111827", zeroline=False,
                   tickfont=dict(family="JetBrains Mono", size=10, color="#4b5563"),
                   tickprefix="₹", tickformat=",.0f"),
        yaxis2=dict(overlaying="y", side="right", showgrid=False, zeroline=False,
                    tickfont=dict(family="JetBrains Mono", size=10, color="#3b82f6"),
                    tickprefix="₹", tickformat=",.0f"),
        legend=dict(font=dict(color="#6b7280", size=11),
                    bgcolor="rgba(0,0,0,0)", orientation="h",
                    yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=30, b=10, l=10, r=10),
        height=280,
        bargap=0.3,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Journey bars ──────────────────────────────────────────────────────────
    st.markdown("**Year by year**")
    rows_html = ""
    for d in data:
        bar_w = d["annual"] / max_ann * 100
        rows_html += f"""
        <div class="journey-row">
            <span class="jlabel">{d['label']}</span>
            <div class="jbar-wrap">
                <div class="jbar-fill" style="width:{bar_w:.1f}%;"></div>
            </div>
            <span class="jamt">{inr(d['monthly'])}/mo</span>
        </div>"""

    st.markdown(
        f'<div style="background:#0d0f14;border:1px solid #1e2330;'
        f'border-radius:10px;padding:12px 20px;">{rows_html}</div>',
        unsafe_allow_html=True
    )

    st.divider()
    st.caption(
        "By Year 10 you'll have contributed "
        f"**{inr(sum(d['annual'] for d in data))}** in total. "
        "Corpus projection with market returns is the next module."
    )
    st.caption(
        "Rules: No ELSS · No active large-cap · No calendar rebalancing · "
        "No sell orders · Debt ban first 15 years · New Tax Regime only."
    )
