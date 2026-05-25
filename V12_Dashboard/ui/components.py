"""
V12 PRO MAX — Reusable UI components (HTML card builders).
Each function returns an HTML string for st.markdown(unsafe_allow_html=True).
"""


def render_kpi_grid(idx, spot, atm_actual, pcr, bias, support, resistance,
                    secondary_support=None, secondary_resistance=None):
    """Top KPI cards: Spot, ATM, PCR, Bias, Support, Resistance."""
    sr_extra = ""
    if secondary_support and secondary_resistance:
        sr_extra = f"""
  <div class="card"><div class="label">S2</div><div class="kpi" style="font-size:16px;">{secondary_support}</div></div>
  <div class="card"><div class="label">R2</div><div class="kpi" style="font-size:16px;">{secondary_resistance}</div></div>"""

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
    tw_c = "#34D399" if in_window else "#F87171"
    oi_c = "#34D399" if oi_active else "#F87171"
    vw_c = "#34D399" if spot_vs_vwap == "ABOVE" else "#F87171"
    pm_c = "#34D399" if pcr_momentum != "FLAT" else "#F59E0B"

    extra_cards = ""
    if sideways_info and sideways_info.get("is_sideways"):
        strength = sideways_info.get("strength", "MILD")
        sw_c = "#F87171" if strength == "STRONG SIDEWAYS" else "#F59E0B"
        extra_cards += f"""
  <div class="card" style="padding:10px;"><div class="label">⚖️ Sideways</div>
    <div style="color:{sw_c};font-weight:700;">{strength}</div></div>"""

    if cooldown_info:
        if isinstance(cooldown_info, dict):
            cooldown_allowed = cooldown_info.get("allowed", True)
            cooldown_reason = cooldown_info.get("reason", "ACTIVE")
        else:
            cooldown_allowed = cooldown_info[0]
            cooldown_reason = cooldown_info[1]
        
        if not cooldown_allowed:
            extra_cards += f"""
  <div class="card" style="padding:10px;"><div class="label">⏸️ Cooldown</div>
    <div style="color:#7C3AED;font-weight:700;">{cooldown_reason}</div></div>"""

    return f"""
<div class="filter-grid">
  <div class="card" style="padding:10px;"><div class="label">⏰ Time</div>
    <div style="color:{tw_c};font-weight:700;">{"✅ IN WINDOW" if in_window else "❌ CLOSED"}</div></div>
  <div class="card" style="padding:10px;"><div class="label">📊 OI Market</div>
    <div style="color:{oi_c};font-weight:700;">{"✅ ACTIVE" if oi_active else "❌ NO DATA"}</div></div>
  <div class="card" style="padding:10px;"><div class="label">📈 vs VWAP ({vwap_proxy})</div>
    <div style="color:{vw_c};font-weight:700;">{spot_vs_vwap}</div></div>
  <div class="card" style="padding:10px;"><div class="label">🔄 PCR Momentum</div>
    <div style="color:{pm_c};font-weight:700;">{pcr_momentum}</div></div>
  <div class="card" style="padding:10px;"><div class="label">📊 OI Flow</div>
    <div style="color:#F59E0B;font-weight:700;">CE Δ:{int(total_ce_delta)} PE Δ:{int(total_pe_delta)}</div></div>{extra_cards}
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
<div style="font-size:10px;color:#6B7280;margin-top:2px;">Signal Quality: {confidence_score}/100</div>"""

    unusual_badge = ""
    if oi_unusual:
        unusual_badge = ' <span class="badge badge-warning">⚠ UNUSUAL OI</span>'

    buf_str = ", ".join(buffer[-3:]) if buffer else ""

    return f"""<div class="card {cc}"><h2>{final_signal}</h2>
<p>Confidence: {final_conf}{unusual_badge}</p>
{score_bar}
<p style="font-size:11px;color:#9CA3AF;">{idx} Raw: {raw_signal} ({confidence}) | PCR: {pcr} | Buffer: {buf_str}{' | '+filter_reason if filter_reason else ''}</p></div>"""


def render_trade_entry_card(lbl, atm_actual, ep, sl_p, tgt_p, qty, ml, tp):
    """Trade entry details card shown when signal is active."""
    return f"""
<div style="margin-top:8px;padding:10px;background:#1F2937;border-radius:10px;">
<strong>📌 {lbl} @ {atm_actual}:</strong> {ep} &nbsp;|&nbsp;
<strong>💰 SL:</strong> {sl_p} &nbsp;|&nbsp;<strong>🎯 Tgt:</strong> {tgt_p} &nbsp;|&nbsp;
<strong>📦 Qty:</strong> {qty} (1 Lot) &nbsp;|&nbsp;<strong>🔴 MaxLoss:</strong> ₹{ml} &nbsp;|&nbsp;
<strong>🟢 TgtP&L:</strong> ₹{tp}</div><br>"""


def render_trap_alert(trap):
    """Trap warning banner."""
    return f'<div class="trap-alert">{trap} DETECTED!</div>'


def render_tracker_grid(idx, capital, closed_count, rpnl, rc, prog):
    """P&L tracker cards."""
    pc = "pnl-green" if rpnl >= 0 else "pnl-red"
    return f"""
<div class="tracker-grid">
  <div class="card"><div class="label">Capital</div><div class="kpi">₹{capital:,}</div></div>
  <div class="card"><div class="label">Closed</div><div class="kpi">{closed_count}</div></div>
  <div class="card"><div class="label">Realized P&L</div><div class="kpi {pc}">₹{rpnl:,.0f}</div></div>
  <div class="card"><div class="label">Running Cap</div><div class="kpi">₹{rc:,.0f}</div></div>
  <div class="card"><div class="label">Daily Progress</div><div class="kpi">{round(prog*100)}%</div></div>
</div>"""


def render_risk_card(atr_sl=None, cooldown_remaining=0,
                     daily_losses=0, max_daily_losses=3):
    """Risk management status card."""
    items = []
    if atr_sl is not None:
        items.append(f'<div><div class="label">ATR SL</div><div style="color:#F59E0B;font-weight:700;">₹{atr_sl}</div></div>')
    if cooldown_remaining > 0:
        items.append(f'<div><div class="label">Cooldown</div><div style="color:#7C3AED;font-weight:700;">{cooldown_remaining}s</div></div>')
    items.append(f'<div><div class="label">Daily Losses</div><div style="color:#F87171;font-weight:700;">{daily_losses}/{max_daily_losses}</div></div>')

    if not items:
        return ""

    items_html = "\n    ".join(items)
    return f"""
<div class="risk-card">
  <div style="display:flex;gap:24px;flex-wrap:wrap;">
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

    return f"""<div class="card" style="border-left:5px solid {sc};margin-bottom:12px;">
<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
<div style="display:flex;align-items:center;gap:10px;">
<span style="background:{idx_color};color:white;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700;">{idx}</span>
<span style="color:{sc};font-size:20px;font-weight:800;">{sig}</span>
<span style="color:#9CA3AF;font-size:12px;">Strike: <b style="color:white;">{strk}</b></span>
<span style="color:#9CA3AF;font-size:12px;">Spot: <b style="color:white;">{spot}</b></span>
</div>
<div style="color:{uc};font-size:22px;font-weight:800;">{upl_arrow} {pnl_disp}</div>
</div>
<div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:10px;">
<div><div class="label">Entry Price</div><div style="color:white;font-weight:700;">₹{ev}</div></div>
<div><div class="label">Live Price</div><div style="color:{uc};font-weight:700;">₹{lv}</div></div>
<div><div class="label">Stop Loss</div><div style="color:#F87171;font-weight:700;">₹{sl}</div></div>
<div><div class="label">Target</div><div style="color:#34D399;font-weight:700;">₹{tgt}</div></div>
<div><div class="label">Qty</div><div style="color:white;font-weight:700;">{qty}</div></div>
<div><div class="label">Max Loss</div><div style="color:#F87171;font-weight:700;">₹{ml}</div></div>
<div><div class="label">Target P&L</div><div style="color:#34D399;font-weight:700;">₹{tp}</div></div>
<div><div class="label">Entry Time</div><div style="color:#9CA3AF;font-weight:700;">{etime}</div></div>
</div>
</div>"""


def render_expander_open_trade(trade, sc):
    """Open trade card inside the per-index expander."""
    ev = float(trade.get("Entry Price") or 0)
    lv = float(trade.get("Live Price") or ev)
    qv = int(trade.get("Qty") or 0)
    upl = round((lv - ev) * qv, 2)
    uc = "#34D399" if upl >= 0 else "#F87171"

    return f"""<div class="card" style="border-left:4px solid {sc};">
<div style="display:flex;gap:20px;flex-wrap:wrap;">
<div><div class="label">Signal</div><div class="kpi" style="color:{sc};">{trade.get('Signal')}</div></div>
<div><div class="label">Strike</div><div class="kpi">{trade.get('Strike')}</div></div>
<div><div class="label">Entry</div><div class="kpi">₹{ev}</div></div>
<div><div class="label">Live</div><div class="kpi">₹{lv}</div></div>
<div><div class="label">SL</div><div class="kpi pnl-red">₹{trade.get('Stop Loss')}</div></div>
<div><div class="label">Target</div><div class="kpi pnl-green">₹{trade.get('Target')}</div></div>
<div><div class="label">Qty</div><div class="kpi">{qv}</div></div>
<div><div class="label">Unrealized P&L</div><div class="kpi" style="color:{uc};">₹{upl:,.0f}</div></div>
</div>
</div>"""


def render_empty_open_trades():
    """Empty state for open trades tab."""
    return """
<div style="text-align:center;padding:60px 20px;">
  <div style="font-size:48px;">📭</div>
  <div style="color:#9CA3AF;font-size:18px;margin-top:12px;">No open trades right now</div>
  <div style="color:#6B7280;font-size:13px;margin-top:6px;">Waiting for a signal...</div>
</div>"""
