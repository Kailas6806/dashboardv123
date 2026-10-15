"""
V12 PRO MAX — Signal Audit & Rejection Intelligence Renderer
Displays real-time and historical multi-factor evaluations for every setup,
showing Rule Scores, AI Conviction, OI Deltas, exact rejection reasons,
and actionable insights to continuously refine trading strategies.
"""
import streamlit as st
import pandas as pd
import datetime
import textwrap
from typing import Any, Dict, List, Optional

try:
    from config import INDEX_CONFIG, IST, AI_MIN_CONVICTION
except ImportError:
    INDEX_CONFIG = {}
    IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    AI_MIN_CONVICTION = 60


def render_audit_tab(auditor: Any = None, fetcher: Any = None, copilot: Any = None) -> None:
    st.markdown("<h3 style='color:#38bdf8; margin-bottom:4px;'>🎯 Signal Audit & Rejection Intelligence</h3>", unsafe_allow_html=True)
    st.caption("Live timeline of all scanned setups, rule scores, AI conviction ratings, and exact rejection rationale.")

    if not auditor:
        from core.signal_audit import get_signal_auditor
        auditor = get_signal_auditor()

    # Fetch audit recent log (up to 2000 entries across sessions)
    raw_logs = auditor.get_audit_log(limit=2000)

    # Discover available dates (YYYY-MM-DD)
    available_dates = []
    for r in raw_logs:
        d = r.get("date") or (str(r.get("timestamp", ""))[:10] if r.get("timestamp") else "")
        if d and len(d) == 10 and d not in available_dates:
            available_dates.append(d)
    available_dates.sort(reverse=True)
    date_options = ["ALL DATES"] + available_dates

    # Active date from session state (allows reactive KPI calculation)
    active_date = st.session_state.get("audit_date_filter", "ALL DATES")
    date_param = active_date if active_date != "ALL DATES" else None
    stats = auditor.get_audit_stats(date_str=date_param)

    # ─────────────────────────────────────────────────────────────
    # 1. TOP KPI DASHBOARD
    # ─────────────────────────────────────────────────────────────
    tot_setups = stats.get("total_setups", 0)
    executed = stats.get("executed", 0)
    rejected = stats.get("rejected", 0)
    neutral = stats.get("neutral_wait", 0)

    rejection_pct = round((rejected / tot_setups * 100), 1) if tot_setups > 0 else 0.0
    date_subtext = f"Date: {active_date}" if active_date != "ALL DATES" else "All recorded history"

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)

    with kpi1:
        st.markdown(textwrap.dedent(f"""
        <div style="background:#111421; border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:12px; text-align:center;">
            <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; font-weight:700;">Evaluated Setups</div>
            <div style="font-size:24px; font-weight:800; color:#38bdf8; margin-top:4px;">{tot_setups:,}</div>
            <div style="font-size:10px; color:#64748b;">{date_subtext}</div>
        </div>
        """).strip(), unsafe_allow_html=True)

    with kpi2:
        st.markdown(textwrap.dedent(f"""
        <div style="background:#111421; border:1px solid rgba(0,229,160,0.25); border-radius:10px; padding:12px; text-align:center;">
            <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; font-weight:700;">Executed Trades</div>
            <div style="font-size:24px; font-weight:800; color:#00e5a0; margin-top:4px;">{executed}</div>
            <div style="font-size:10px; color:#00e5a0;">All rules & AI approved</div>
        </div>
        """).strip(), unsafe_allow_html=True)

    with kpi3:
        st.markdown(textwrap.dedent(f"""
        <div style="background:#111421; border:1px solid rgba(255,77,109,0.25); border-radius:10px; padding:12px; text-align:center;">
            <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; font-weight:700;">Filtered / Blocked</div>
            <div style="font-size:24px; font-weight:800; color:#ff4d6d; margin-top:4px;">{rejected}</div>
            <div style="font-size:10px; color:#ff4d6d;">{rejection_pct}% Rejection rate</div>
        </div>
        """).strip(), unsafe_allow_html=True)

    with kpi4:
        breakdown = stats.get("rejection_breakdown", {})
        top_reason = max(breakdown.items(), key=lambda x: x[1])[0] if breakdown else "None"
        clean_top_reason = top_reason.replace("_", " ")
        st.markdown(textwrap.dedent(f"""
        <div style="background:#111421; border:1px solid rgba(245,158,11,0.25); border-radius:10px; padding:12px; text-align:center;">
            <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; font-weight:700;">Top Guard Blocker</div>
            <div style="font-size:16px; font-weight:800; color:#f59e0b; margin-top:8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="{clean_top_reason}">{clean_top_reason}</div>
            <div style="font-size:10px; color:#94a3b8;">Primary filter cause</div>
        </div>
        """).strip(), unsafe_allow_html=True)

    st.markdown("<hr style='border:none; border-top:1px solid rgba(255,255,255,0.07); margin:16px 0 12px 0;'>", unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────
    # 2. FILTER & SEARCH CONTROLS
    # ─────────────────────────────────────────────────────────────
    f_date, f_idx, f_status, f_search = st.columns([1.6, 1.3, 1.5, 2.4])
    with f_date:
        cur_date_idx = 0
        if active_date in date_options:
            cur_date_idx = date_options.index(active_date)
        selected_date = st.selectbox("📅 Filter Date", date_options, index=cur_date_idx, key="audit_date_filter")
    with f_idx:
        selected_idx = st.selectbox("Filter Index", ["ALL", "NIFTY", "BANKNIFTY", "FINNIFTY"], key="audit_idx_filter")
    with f_status:
        selected_status = st.selectbox(
            "Filter Outcome",
            ["ALL", "EXECUTED", "REJECTED", "NEUTRAL_WAIT"],
            key="audit_status_filter"
        )
    with f_search:
        search_query = st.text_input("🔍 Search Keyword / Strike / Reason", placeholder="e.g. 24500, conviction, sideways", key="audit_search_box")

    # Apply filters
    filtered_logs = list(raw_logs)
    if selected_date != "ALL DATES":
        filtered_logs = [r for r in filtered_logs if (r.get("date") or str(r.get("timestamp", ""))[:10]) == selected_date]
    if selected_idx != "ALL":
        filtered_logs = [r for r in filtered_logs if r.get("idx") == selected_idx]
    if selected_status != "ALL":
        filtered_logs = [r for r in filtered_logs if r.get("status") == selected_status]
    if search_query:
        sq = search_query.lower()
        filtered_logs = [
            r for r in filtered_logs
            if sq in str(r.get("rejection_detail", "")).lower()
            or sq in str(r.get("rejection_code", "")).lower()
            or sq in str(r.get("ai_reasoning", "")).lower()
            or sq in str(r.get("atm", "")).lower()
            or sq in str(r.get("idx", "")).lower()
            or sq in str(r.get("date", "")).lower()
        ]

    # ─────────────────────────────────────────────────────────────
    # 3. CSV EXPORT BUTTON
    # ─────────────────────────────────────────────────────────────
    if filtered_logs:
        export_df = pd.DataFrame(filtered_logs)
        csv_data = export_df.to_csv(index=False).encode("utf-8")
        date_slug = selected_date.replace("-", "") if selected_date != "ALL DATES" else "all_dates"
        st.download_button(
            label=f"📥 Export Signal Audit Log to CSV ({len(filtered_logs)} records)",
            data=csv_data,
            file_name=f"signal_audit_{date_slug}_{datetime.datetime.now(IST).strftime('%H%M%S')}.csv",
            mime="text/csv",
            width="stretch",
        )
    st.write("")

    if not filtered_logs:
        st.info("ℹ️ No signal audit events recorded matching current filters. The scanner will record snapshots as the market runs.")
        return

    # ─────────────────────────────────────────────────────────────
    # 4. SIGNAL AUDIT TIMELINE CARDS
    # ─────────────────────────────────────────────────────────────
    for item in filtered_logs[:100]:
        idx_name = item.get("idx", "")
        entry_date = item.get("date") or (str(item.get("timestamp", ""))[:10] if item.get("timestamp") else "")
        time_part = item.get("time_str", "") or item.get("timestamp", "")
        if entry_date and entry_date not in time_part:
            display_time = f"{entry_date} {time_part}"
        else:
            display_time = time_part or item.get("timestamp", "")
        spot = item.get("spot", 0.0)
        atm = item.get("atm", 0)
        pcr = item.get("pcr", 1.0)
        pcr_mom = item.get("pcr_mom", "FLAT")
        vwap = item.get("vwap", 0.0)
        spot_vs_vwap = item.get("spot_vs_vwap", "")
        support = item.get("support", 0)
        resistance = item.get("resistance", 0)
        ce_delta = item.get("ce_delta", 0)
        pe_delta = item.get("pe_delta", 0)
        tot_ce = item.get("tot_ce", 0)
        tot_pe = item.get("tot_pe", 0)
        final_sig = item.get("final_signal", "WAIT")
        rule_score = item.get("rule_score", 0)
        ai_score = item.get("ai_conviction")
        status = item.get("status", "WAIT")
        rej_code = item.get("rejection_code", "")
        rej_detail = item.get("rejection_detail", "")
        ai_reason = item.get("ai_reasoning", "")

        # Style mapping
        if status == "EXECUTED":
            badge_color = "#00e5a0"
            badge_bg = "rgba(0,229,160,0.15)"
            badge_icon = "🟢"
            badge_text = f"EXECUTED: {final_sig}"
            card_border = "1.5px solid rgba(0,229,160,0.4)"
        elif status == "REJECTED":
            badge_color = "#ff4d6d"
            badge_bg = "rgba(255,77,109,0.15)"
            badge_icon = "🔴"
            clean_code = rej_code.replace("_", " ")
            badge_text = f"REJECTED: {clean_code}"
            card_border = "1.5px solid rgba(255,77,109,0.3)"
        else:
            badge_color = "#94a3b8"
            badge_bg = "rgba(255,255,255,0.06)"
            badge_icon = "⚪"
            badge_text = "NEUTRAL WAIT"
            card_border = "1px solid rgba(255,255,255,0.08)"

        ai_score_label = f"{ai_score}/100" if ai_score is not None else "N/A"
        ai_score_color = "#00e5a0" if (ai_score or 0) >= AI_MIN_CONVICTION else ("#ff4d6d" if ai_score is not None else "#94a3b8")

        card_html = textwrap.dedent(f"""
        <div style="background:#0f1322; border:{card_border}; border-radius:10px; padding:14px 18px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="display:flex; align-items:center; gap:10px;">
                    <span style="font-size:16px; font-weight:800; color:#f8fafc;">{idx_name}</span>
                    <span style="font-size:12px; color:#38bdf8; font-weight:600;">₹{spot:,.2f}</span>
                    <span style="font-size:11px; color:#64748b;">(ATM {atm})</span>
                </div>
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-size:11px; color:#94a3b8;">⏰ {display_time}</span>
                    <span style="color:{badge_color}; background:{badge_bg}; padding:3px 9px; border-radius:5px; font-weight:700; font-size:11px;">
                        {badge_icon} {badge_text}
                    </span>
                </div>
            </div>
            <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:8px; margin:12px 0 10px 0; background:#161b2e; padding:8px 12px; border-radius:6px; font-size:11px;">
                <div>📊 <b>PCR:</b> <span style="color:#f8fafc;">{pcr:.2f} ({pcr_mom})</span></div>
                <div>📍 <b>VWAP:</b> <span style="color:#f8fafc;">₹{vwap:,.2f} ({spot_vs_vwap})</span></div>
                <div>🧱 <b>Walls:</b> <span style="color:#00e5a0;">S {support}</span> | <span style="color:#ff4d6d;">R {resistance}</span></div>
                <div>📈 <b>OI Deltas:</b> CE {ce_delta:+,} | PE {pe_delta:+,}</div>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; margin-bottom:8px;">
                <span style="color:#cbd5e1;">Rule Engine Confidence: <b style="color:#38bdf8;">{rule_score}/100</b></span>
                <span style="color:#cbd5e1;">AI Copilot Conviction: <b style="color:{ai_score_color};">{ai_score_label}</b> (Threshold: {AI_MIN_CONVICTION})</span>
            </div>
            <div style="background:#1a1f35; border-left:3px solid {badge_color}; padding:8px 12px; border-radius:4px; font-size:12px; color:#e2e8f0;">
                <b>Why this outcome?</b> {rej_detail}
            </div>
        </div>
        """).strip()
        st.markdown(card_html, unsafe_allow_html=True)

        # Expandable AI Reasoning Inspector if available
        if ai_reason:
            with st.expander(f"🧠 Detailed AI Synthesized Reasoning for {idx_name} @ {display_time}"):
                st.markdown(f"<div style='font-size:12px; color:#cbd5e1; line-height:1.5;'>{ai_reason}</div>", unsafe_allow_html=True)
