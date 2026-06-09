"""
V12 PRO MAX — Reusable UI components (HTML card builders).
Each function returns an HTML string for st.markdown(unsafe_allow_html=True).
"""


def _safe_int(val, default=0):
    """Safely convert a value to int, returning default on NaN/None/error."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def render_kpi_grid(idx, spot, atm_actual, pcr, bias, support, resistance,
                    secondary_support=None, secondary_resistance=None):
    """Top KPI cards: Spot, ATM, PCR, Bias, Support, Resistance."""
    sr_extra = ""
    if secondary_support and secondary_resistance:
        sr_extra = f"""
  <div class="card"><div class="label">S2</div><div class="kpi" style="font-size:20px;">{secondary_support}</div></div>
  <div class="card"><div class="label">R2</div><div class="kpi" style="font-size:20px;">{secondary_resistance}</div></div>"""

    return f"""
<div class="kpi-grid">
  <div class="card"><div class="label">{idx} SPOT</div><div class="kpi">{round(spot,2)}</div></div>
  <div class="card"><div class="label">ATM</div><div class="kpi">{atm_actual}</div></div>
  <div class="card"><div class="label">PCR</div><div class="kpi">{pcr}</div></div>
  <div class="card"><div class="label">BIAS</div><div class="kpi">{bias}</div></div>
  <div class="card"><div class="label">SUPPORT</div><div class="kpi">{support}</div></div>
  <div class="card"><div class="label">RESISTANCE</div><div class="kpi">{resistance}</div></div>{sr_extra}
</div>"""


def render_filter_grid(in_window, oi_active, spot_vs_vwap, vwap_proxy,
                       pcr_momentum, total_ce_delta, total_pe_delta,
                       sideways_info=None, cooldown_info=None):
    """Filter status cards: Time, OI, VWAP, PCR Momentum, OI Flow + optional sideways/cooldown."""
    tw_c = "#10b981" if in_window else "#ef4444"
    oi_c = "#10b981" if oi_active else "#ef4444"
    vw_c = "#10b981" if spot_vs_vwap == "ABOVE" else "#ef4444"
    pm_c = "#10b981" if pcr_momentum != "FLAT" else "#f59e0b"

    extra_cards = ""
    if sideways_info and sideways_info.get("is_sideways"):
        strength = sideways_info.get("strength", "MILD")
        sw_c = "#ef4444" if strength == "STRONG SIDEWAYS" else "#f59e0b"
        extra_cards += f"""
  <div class="card"><div class="label">⚖️ Sideways</div>
    <div style="color:{sw_c};font-weight:700;font-size:16px;">{strength}</div></div>"""

    if cooldown_info:
        if isinstance(cooldown_info, dict):
            cooldown_allowed = cooldown_info.get("allowed", True)
            cooldown_reason = cooldown_info.get("reason", "ACTIVE")
        elif isinstance(cooldown_info, (tuple, list)) and len(cooldown_info) >= 2:
            cooldown_allowed = cooldown_info[0]
            cooldown_reason = cooldown_info[1]
        else:
            cooldown_allowed = True
            cooldown_reason = ""
        
        if not cooldown_allowed:
            extra_cards += f"""
  <div class="card"><div class="label">⏸️ Cooldown</div>
    <div style="color:#a855f7;font-weight:700;font-size:16px;">{cooldown_reason}</div></div>"""

    return f"""
<div class="filter-grid">
  <div class="card"><div class="label">⏰ Time</div>
    <div style="color:{tw_c};font-weight:700;font-size:16px;">{"✅ IN WINDOW" if in_window else "❌ CLOSED"}</div></div>
  <div class="card"><div class="label">📊 OI Market</div>
    <div style="color:{oi_c};font-weight:700;font-size:16px;">{"✅ ACTIVE" if oi_active else "❌ NO DATA"}</div></div>
  <div class="card"><div class="label">📈 vs VWAP ({vwap_proxy})</div>
    <div style="color:{vw_c};font-weight:700;font-size:16px;">{spot_vs_vwap}</div></div>
  <div class="card"><div class="label">🔄 PCR Momentum</div>
    <div style="color:{pm_c};font-weight:700;font-size:16px;">{pcr_momentum}</div></div>
  <div class="card"><div class="label">📊 OI Flow</div>
    <div style="color:#f59e0b;font-weight:700;font-size:16px;">CE Δ:{_safe_int(total_ce_delta)} PE Δ:{_safe_int(total_pe_delta)}</div></div>{extra_cards}
</div>"""


def render_signal_card(idx, final_signal, final_conf, raw_signal, confidence,
                       pcr, buffer, filter_reason="", confidence_score=0,
                       oi_unusual=False):
    """Main signal display card with confidence bar."""
    cc = "signal-green" if "CE" in final_signal else (
        "signal-red" if "PE" in final_signal else "signal-yellow")

    # Confidence score bar
    bar_class = "conf-bar-high" if confidence_score >= 60 else (
        "conf-bar-medium" if confidence_score >= 35 else "conf-bar-low")
    score_bar = f"""<div class="conf-bar-outer"><div class="conf-bar-inner {bar_class}" style="width:{confidence_score}%;"></div></div>
<div style="font-size:11px;color:#a1a1aa;margin-top:4px;font-weight:600;">Signal Quality: <span style="color:white;">{confidence_score}/100</span></div>"""

    unusual_badge = ""
    if oi_unusual:
        unusual_badge = ' <span class="badge badge-warning" style="margin-left:8px;">⚠ UNUSUAL OI</span>'

    buf_str = ", ".join(buffer[-3:]) if buffer else ""

    return f"""<div class="card {cc}">
<h2 class="kpi" style="font-size:36px;margin-bottom:8px;">{final_signal}</h2>
<p style="font-size:16px;font-weight:600;color:#e4e4e7;margin:0 0 12px 0;">Confidence: {final_conf}{unusual_badge}</p>
{score_bar}
<p style="font-size:12px;color:#71717a;margin-top:12px;font-weight:500;">{idx} Raw: {raw_signal} ({confidence}) | PCR: {pcr} | Buffer: {buf_str}{' | '+filter_reason if filter_reason else ''}</p></div>"""


def render_trade_entry_card(lbl, atm_actual, ep, sl_p, tgt_p, qty, ml, tp):
    """Trade entry details card shown when signal is active."""
    return f"""
<div class="card" style="border-left:4px solid #6366f1; background: linear-gradient(135deg, rgba(79, 70, 229, 0.1), rgba(49, 46, 129, 0.2));">
  <div class="label" style="color:#818cf8;margin-bottom:12px;">📌 ACTIVE TRADE CONFIGURATION</div>
  <div style="display:flex;flex-wrap:wrap;gap:24px;align-items:center;">
    <div><div class="label">Signal</div><div style="font-size:18px;font-weight:800;color:white;">{lbl} @ {atm_actual}</div></div>
    <div><div class="label">Entry</div><div style="font-size:18px;font-weight:800;color:white;">₹{ep}</div></div>
    <div><div class="label">Stop Loss</div><div style="font-size:18px;font-weight:800;color:#ef4444;">₹{sl_p}</div></div>
    <div><div class="label">Target</div><div style="font-size:18px;font-weight:800;color:#10b981;">₹{tgt_p}</div></div>
    <div><div class="label">Quantity</div><div style="font-size:18px;font-weight:800;color:#d4d4d8;">{qty} <span style="font-size:12px;color:#a1a1aa;">(1 Lot)</span></div></div>
    <div><div class="label">Max Loss</div><div style="font-size:18px;font-weight:800;color:#ef4444;">₹{ml}</div></div>
    <div><div class="label">Target P&L</div><div style="font-size:18px;font-weight:800;color:#10b981;">₹{tp}</div></div>
  </div>
</div>"""


def render_trap_alert(trap):
    """Trap warning banner."""
    return f'<div class="trap-alert">🚨 {trap} DETECTED! 🚨</div>'


def render_tracker_grid(idx, capital, closed_count, rpnl, rc, prog):
    """P&L tracker cards."""
    pc = "pnl-green" if rpnl >= 0 else "pnl-red"
    return f"""
<div class="tracker-grid">
  <div class="card"><div class="label">Capital</div><div class="kpi" style="font-size:22px;">₹{capital:,}</div></div>
  <div class="card"><div class="label">Closed</div><div class="kpi" style="font-size:22px;">{closed_count}</div></div>
  <div class="card"><div class="label">Realized P&L</div><div class="kpi {pc}" style="font-size:22px;">₹{rpnl:,.0f}</div></div>
  <div class="card"><div class="label">Running Cap</div><div class="kpi" style="font-size:22px;">₹{rc:,.0f}</div></div>
  <div class="card"><div class="label">Daily Progress</div><div class="kpi" style="font-size:22px;">{round(prog*100)}%</div></div>
</div>"""


def render_risk_card(atr_sl=None, cooldown_remaining=0,
                     daily_losses=0, max_daily_losses=3):
    """Risk management status card."""
    items = []
    if atr_sl is not None:
        items.append(f'<div><div class="label">ATR SL</div><div style="color:#f59e0b;font-weight:800;font-size:18px;">₹{atr_sl}</div></div>')
    if cooldown_remaining > 0:
        items.append(f'<div><div class="label">Cooldown</div><div style="color:#a855f7;font-weight:800;font-size:18px;">{cooldown_remaining}s</div></div>')
    items.append(f'<div><div class="label">Daily Losses</div><div style="color:#ef4444;font-weight:800;font-size:18px;">{daily_losses} / {max_daily_losses}</div></div>')

    if not items:
        return ""

    items_html = "\n    ".join(items)
    return f"""
<div class="risk-card">
  <div class="label" style="color:#818cf8;width:100%;margin-bottom:8px;">🛡️ RISK MANAGEMENT HUD</div>
  <div style="display:flex;gap:32px;flex-wrap:wrap;">
    {items_html}
  </div>
</div>"""


def render_open_trade_detail(trade, idx_color, sc, uc, upl, pnl_disp, upl_arrow):
    """Single open trade card for the Open Trades tab."""
    idx = trade.get("Index", "")
    sig = trade.get("Signal", "")
    strk = trade.get("Strike", "")
    spot = trade.get("Spot", "")
    ev = float(trade.get("Entry Price") or 0)
    lv = float(trade.get("Live Price") or ev)
    sl = trade.get("Stop Loss", "")
    tgt = trade.get("Target", "")
    qty = int(trade.get("Qty") or 0)
    ml = trade.get("Max Loss ₹", "")
    tp = trade.get("Target P&L ₹", "")
    etime = trade.get("Entry Time", "")

    return f"""<div class="card" style="border-left:4px solid {sc};">
<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:20px;">
  <div style="display:flex;align-items:center;gap:12px;">
    <span style="background:rgba(255,255,255,0.05);color:white;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:800;border:1px solid rgba(255,255,255,0.1);">{idx}</span>
    <span style="color:{sc};font-size:24px;font-weight:800;letter-spacing:-0.02em;">{sig}</span>
    <span style="color:#a1a1aa;font-size:13px;font-weight:600;">Strike: <b style="color:#e4e4e7;">{strk}</b></span>
    <span style="color:#a1a1aa;font-size:13px;font-weight:600;">Spot: <b style="color:#e4e4e7;">{spot}</b></span>
  </div>
  <div style="color:{uc};font-size:28px;font-weight:800;letter-spacing:-0.02em;text-shadow:0 0 20px {uc}40;">{upl_arrow} {pnl_disp}</div>
</div>
<div style="display:flex;gap:32px;flex-wrap:wrap;background:rgba(0,0,0,0.2);padding:16px;border-radius:12px;border:1px solid rgba(255,255,255,0.03);">
  <div><div class="label">Entry</div><div class="kpi" style="font-size:20px;">₹{ev}</div></div>
  <div><div class="label">Live</div><div class="kpi" style="font-size:20px;color:{uc};-webkit-text-fill-color:{uc};">₹{lv}</div></div>
  <div><div class="label">Stop Loss</div><div class="kpi" style="font-size:20px;color:#ef4444;-webkit-text-fill-color:#ef4444;">₹{sl}</div></div>
  <div><div class="label">Target</div><div class="kpi" style="font-size:20px;color:#10b981;-webkit-text-fill-color:#10b981;">₹{tgt}</div></div>
  <div><div class="label">Qty</div><div class="kpi" style="font-size:20px;">{qty}</div></div>
  <div><div class="label">Max Loss</div><div class="kpi" style="font-size:20px;color:#ef4444;-webkit-text-fill-color:#ef4444;">₹{ml}</div></div>
  <div><div class="label">Target P&L</div><div class="kpi" style="font-size:20px;color:#10b981;-webkit-text-fill-color:#10b981;">₹{tp}</div></div>
  <div><div class="label" style="margin-bottom:0;">Entry Time</div><div style="font-size:13px;color:#71717a;font-weight:600;margin-top:6px;">{etime}</div></div>
</div>
</div>"""


def render_expander_open_trade(trade, sc):
    """Open trade card inside the per-index expander."""
    ev = float(trade.get("Entry Price") or 0)
    lv = float(trade.get("Live Price") or ev)
    qv = int(trade.get("Qty") or 0)
    upl = round((lv - ev) * qv, 2)
    uc = "#10b981" if upl >= 0 else "#ef4444"

    return f"""<div class="card" style="border-left:4px solid {sc};padding:14px 20px;">
<div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center;">
  <div><div class="label">Signal</div><div class="kpi" style="font-size:18px;color:{sc};-webkit-text-fill-color:{sc};">{trade.get('Signal')}</div></div>
  <div><div class="label">Strike</div><div class="kpi" style="font-size:18px;">{trade.get('Strike')}</div></div>
  <div><div class="label">Entry</div><div class="kpi" style="font-size:18px;">₹{ev}</div></div>
  <div><div class="label">Live</div><div class="kpi" style="font-size:18px;color:{uc};-webkit-text-fill-color:{uc};">₹{lv}</div></div>
  <div><div class="label">SL</div><div class="kpi" style="font-size:18px;color:#ef4444;-webkit-text-fill-color:#ef4444;">₹{trade.get('Stop Loss')}</div></div>
  <div><div class="label">Target</div><div class="kpi" style="font-size:18px;color:#10b981;-webkit-text-fill-color:#10b981;">₹{trade.get('Target')}</div></div>
  <div><div class="label">Qty</div><div class="kpi" style="font-size:18px;">{qv}</div></div>
  <div style="margin-left:auto;"><div class="label">Unrealized P&L</div><div class="kpi" style="font-size:22px;color:{uc};-webkit-text-fill-color:{uc};">₹{upl:,.0f}</div></div>
</div>
</div>"""


def render_empty_open_trades():
    """Empty state for open trades tab."""
    return """
<div style="text-align:center;padding:80px 20px;">
  <div style="font-size:56px;opacity:0.8;">📭</div>
  <div style="color:#e4e4e7;font-size:20px;font-weight:700;margin-top:16px;">No open trades right now</div>
  <div style="color:#71717a;font-size:14px;font-weight:500;margin-top:8px;">Waiting for a high-probability signal to enter the market.</div>
</div>"""
