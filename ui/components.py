"""
V12 PRO MAX — Modular UI Components & Normalized Trade Presentation
Clean separation of presentation layer from data/trading logic.
Dynamic presentation supporting any instrument, direction, and market condition.
"""
from typing import Any, Dict, List, Optional


def _safe_int(val: Any, default: int = 0) -> int:
    """Safely convert a value to int, returning default on NaN/None/error."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default on NaN/None/error."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ──────────────────────────────────────────────────
# 1. NORMALIZED UI TRADE ADAPTER
# ──────────────────────────────────────────────────
def normalize_trade(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes any trade record into a consistent UI presentation model.
    Works dynamically for any instrument (NIFTY, BANKNIFTY, FINNIFTY, etc.),
    any option type (CE, PE, FUT), and any direction (BUY, SELL, LONG, SHORT).
    """
    instrument = str(raw.get("Index") or raw.get("instrument") or "INDEX").upper()
    signal = str(raw.get("Signal") or raw.get("direction") or "BUY").upper()

    # Determine direction and option type
    if "CE" in signal:
        direction = "BUY" if "BUY" in signal else ("SELL" if "SELL" in signal else signal)
        option_type = "CE"
    elif "PE" in signal:
        direction = "BUY" if "BUY" in signal else ("SELL" if "SELL" in signal else signal)
        option_type = "PE"
    else:
        direction = signal
        option_type = str(raw.get("option_type") or "").upper()

    strike = raw.get("Strike") or raw.get("strike") or "ATM"
    ev = _safe_float(raw.get("Entry Price") or raw.get("entry_price"))
    lv = _safe_float(raw.get("Live Price") or raw.get("current_price") or ev)
    sl = _safe_float(raw.get("Stop Loss") or raw.get("stop_loss"))
    tgt = _safe_float(raw.get("Target") or raw.get("target"))
    qty = _safe_int(raw.get("Qty") or raw.get("quantity"))
    spot = raw.get("Spot") or raw.get("spot_price")
    ml = raw.get("Max Loss ₹") or raw.get("max_loss")
    tp = raw.get("Target P&L ₹") or raw.get("target_pnl")
    etime = str(raw.get("Entry Time") or raw.get("entry_time") or "—")
    status = str(raw.get("Status") or raw.get("status") or "OPEN").upper()

    # P&L Calculation (Unrealized or Actual)
    actual_pnl = raw.get("Actual P&L ₹")
    if actual_pnl is not None and status == "CLOSED":
        pnl = _safe_float(actual_pnl)
    else:
        pnl = round((lv - ev) * qty, 2)

    upl_sign = "+" if pnl >= 0 else ""
    upl_arrow = "▲" if pnl >= 0 else "▼"
    pnl_disp = f"{upl_arrow} {upl_sign}₹{abs(pnl):,.0f}" if pnl < 0 else f"{upl_arrow} {upl_sign}₹{pnl:,.0f}"

    # Target Progress Calculation
    try:
        if tgt > ev:
            prog = max(0.0, min(1.0, (lv - ev) / (tgt - ev)))
        elif ev > tgt and tgt > 0:
            prog = max(0.0, min(1.0, (ev - lv) / (ev - tgt)))
        else:
            prog = 0.0
    except Exception:
        prog = 0.0
    progress_pct = round(prog * 100, 1)

    return {
        "raw": raw,
        "instrument": instrument,
        "signal": signal,
        "direction": direction,
        "option_type": option_type,
        "strike": strike,
        "entry_price": ev,
        "live_price": lv,
        "stop_loss": sl,
        "target": tgt,
        "quantity": qty,
        "spot": spot,
        "max_loss": ml,
        "target_pnl": tp,
        "entry_time": etime,
        "status": status,
        "pnl": pnl,
        "pnl_disp": pnl_disp,
        "progress_pct": progress_pct,
    }


# ──────────────────────────────────────────────────
# 2. TERMINAL HEADER & TICKER
# ──────────────────────────────────────────────────
def render_app_header(is_market_open: bool, is_connected: bool, datetime_str: str) -> str:
    """Renders compact terminal header with status indicators."""
    market_pill = '<span class="pill pill-on">MARKET OPEN</span>' if is_market_open else '<span class="pill pill-off">MARKET CLOSED</span>'
    live_pill = '<span class="pill pill-live">LIVE</span>' if is_connected else '<span class="pill pill-off">DATA DISCONNECTED</span>'

    return f"""
<div class="app-header">
  <div class="app-header-left">
    <h1>V12 <span style="color:var(--indigo);">PRO MAX</span></h1>
    <p>Algorithmic Trading Engine</p>
  </div>
  <div style="text-align: right;">
    <div style="display: flex; gap: 8px; justify-content: flex-end; align-items: center; margin-bottom: 4px;">
      {market_pill}
      {live_pill}
    </div>
    <div class="num" style="font-size: 12px; color: var(--text-1); letter-spacing: 0.02em;">
      {datetime_str}
    </div>
  </div>
</div>"""


def render_market_ticker(ticker_items: List[Dict[str, Any]]) -> str:
    """Renders horizontal market ticker strip from real existing spot prices."""
    if not ticker_items:
        return ""

    chips = []
    for item in ticker_items:
        sym = item.get("symbol", "")
        spot = item.get("spot")
        if spot is not None:
            try:
                spot_disp = f"{round(float(spot), 2):,}"
            except Exception:
                spot_disp = str(spot)
        else:
            spot_disp = "—"

        chips.append(f'<div class="ticker-item"><span class="ticker-symbol">{sym}</span><span class="ticker-val">{spot_disp}</span></div>')

    chips_html = "".join(chips)
    return f'<div class="market-ticker">{chips_html}</div>'


# ──────────────────────────────────────────────────
# 3. SUMMARY KPI SECTION
# ──────────────────────────────────────────────────
def render_open_positions_summary(
    trades_count: int,
    today_pnl: Optional[float],
    max_loss: Optional[float],
    win_rate: Optional[float],
) -> str:
    """
    Renders the 4 dynamic summary KPI cards:
    OPEN TRADES | TODAY P&L | MAX LOSS | WIN RATE.
    If a metric is unavailable, renders 'N/A' (never invents values).
    """
    trades_disp = str(trades_count)

    if today_pnl is not None:
        pnl_sign = "+" if today_pnl >= 0 else ""
        pnl_cls = "c-ce" if today_pnl >= 0 else "c-pe"
        pnl_disp = f"{pnl_sign}₹{today_pnl:,.0f}"
    else:
        pnl_cls = "c-muted"
        pnl_disp = "N/A"

    if max_loss is not None and max_loss > 0:
        max_loss_disp = f"₹{max_loss:,.0f}"
    else:
        max_loss_disp = "N/A"

    if win_rate is not None:
        win_rate_disp = f"{win_rate:.1f}%"
    else:
        win_rate_disp = "N/A"

    return f"""
<div style="margin-bottom: 18px;">
  <div class="label" style="font-size: 11px !important; margin-bottom: 8px; color: #ffffff !important; font-weight: 700;">
    OPEN POSITIONS SUMMARY
  </div>
  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px;">
    <div class="kpi-card">
      <div class="label">OPEN TRADES</div>
      <div class="kpi num">{trades_disp}</div>
    </div>
    <div class="kpi-card">
      <div class="label">TODAY P&L</div>
      <div class="kpi num {pnl_cls}">{pnl_disp}</div>
    </div>
    <div class="kpi-card">
      <div class="label">MAX LOSS</div>
      <div class="kpi num">{max_loss_disp}</div>
    </div>
    <div class="kpi-card">
      <div class="label">WIN RATE</div>
      <div class="kpi num">{win_rate_disp}</div>
    </div>
  </div>
</div>"""


# ──────────────────────────────────────────────────
# 4. TRADE CARD COMPONENT
# ──────────────────────────────────────────────────
def render_trade_card_html(t: Dict[str, Any]) -> str:
    """
    Renders open trade card using the normalized trade dictionary.
    Dynamic and robust across any instrument, option type, or direction.
    """
    instrument = t["instrument"]
    direction = t["direction"]
    option_type = t["option_type"]
    strike = t["strike"]
    ev = t["entry_price"]
    lv = t["live_price"]
    sl = t["stop_loss"]
    tgt = t["target"]
    qty = t["quantity"]
    spot = t["spot"]
    ml = t["max_loss"]
    tp = t["target_pnl"]
    etime = t["entry_time"]
    pnl_disp = t["pnl_disp"]
    pnl = t["pnl"]
    progress_pct = t["progress_pct"]

    is_ce = "CE" in option_type or "CE" in t["signal"]
    card_cls = "ce-card" if is_ce else "pe-card"
    accent_cls = "c-ce" if is_ce else "c-pe"
    pnl_cls = "pnl-positive" if pnl >= 0 else "pnl-negative"
    fill_cls = "fill-ce" if is_ce else "fill-pe"

    spot_str = f"₹{_safe_float(spot):,.2f}" if spot is not None else "N/A"
    ml_str = f"₹{_safe_float(ml):,.0f}" if ml is not None else "N/A"
    tp_str = f"₹{_safe_float(tp):,.0f}" if tp is not None else "N/A"

    opt_label = f"{strike} {option_type}".strip() if option_type else str(strike)

    return f"""
<div class="trade-card {card_cls}">
  <!-- Card Header -->
  <div class="trade-header">
    <div class="num" style="font-size: 18px; color: #ffffff;">
      <b>{instrument}</b> &nbsp;•&nbsp; <span class="{accent_cls}">{direction} {option_type}</span> &nbsp;•&nbsp; <span>{opt_label}</span>
    </div>
    <div class="num {pnl_cls}" style="font-size: 21px; font-weight: 800;">
      {pnl_disp}
    </div>
  </div>

  <!-- Row 1: Execution Metrics -->
  <div class="trade-grid">
    <div>
      <div class="label">ENTRY</div>
      <div class="kpi-sm num">₹{ev:.2f}</div>
    </div>
    <div>
      <div class="label">LIVE</div>
      <div class="kpi-sm num {pnl_cls}">₹{lv:.2f}</div>
    </div>
    <div>
      <div class="label">STOP LOSS</div>
      <div class="kpi-sm num c-pe">{f'₹{sl:.2f}' if sl > 0 else 'N/A'}</div>
    </div>
    <div>
      <div class="label">TARGET</div>
      <div class="kpi-sm num c-ce">{f'₹{tgt:.2f}' if tgt > 0 else 'N/A'}</div>
    </div>
    <div>
      <div class="label">QUANTITY</div>
      <div class="kpi-sm num">{qty}</div>
    </div>
  </div>

  <!-- Row 2: Secondary Context Strip -->
  <div class="trade-strip">
    <div>Spot <b class="num" style="color:#ffffff;">{spot_str}</b></div>
    <div>Max Loss <b class="num c-pe">{ml_str}</b></div>
    <div>Target P&L <b class="num c-ce">{tp_str}</b></div>
  </div>

  <!-- Row 3: Target Progress -->
  <div style="margin-bottom: 12px;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
      <span class="label" style="margin-bottom: 0;">TARGET PROGRESS</span>
      <span class="num" style="font-size: 11px; color: var(--text-1);">{progress_pct}%</span>
    </div>
    <div class="progress-bar">
      <div class="progress-fill {fill_cls}" style="width: {progress_pct}%;"></div>
    </div>
  </div>

  <!-- Row 4: Entry Time -->
  <div style="font-size: 11px; color: var(--text-2);">
    Entry: <span class="num" style="color: var(--text-1);">{etime}</span>
  </div>
</div>"""


def render_open_trade_detail(trade: Dict[str, Any], *args, **kwargs) -> str:
    """Backwards-compatible wrapper that normalizes the trade and renders the card."""
    norm = normalize_trade(trade)
    return render_trade_card_html(norm)


def render_empty_open_trades() -> str:
    """Empty state for open trades tab."""
    return """
<div class="empty-state">
  <div class="icon">⚡</div>
  <div class="msg">NO OPEN POSITIONS</div>
  <div class="sub">Your trading engine currently has no active positions. Scanning for setups.</div>
</div>"""


# ──────────────────────────────────────────────────
# 5. INDEX SPECIFIC COMPONENTS (PRESERVED)
# ──────────────────────────────────────────────────
def render_kpi_grid(idx, spot, atm_actual, pcr, bias, support, resistance,
                    secondary_support=None, secondary_resistance=None):
    """Top KPI cards for index tabs."""
    sr_extra = ""
    if secondary_support and secondary_resistance:
        sr_extra = f"""
  <div class="card"><div class="label">S2</div><div class="kpi num">{secondary_support}</div></div>
  <div class="card"><div class="label">R2</div><div class="kpi num">{secondary_resistance}</div></div>"""

    bias_str = str(bias).upper()
    bias_cls = "c-ce" if "BULL" in bias_str else ("c-pe" if "BEAR" in bias_str else "c-amber")

    return f"""
<div class="kpi-grid">
  <div class="card"><div class="label">{idx} SPOT</div><div class="kpi num c-white">{round(spot,2)}</div></div>
  <div class="card"><div class="label">ATM</div><div class="kpi num">{atm_actual}</div></div>
  <div class="card"><div class="label">PCR</div><div class="kpi num">{pcr}</div></div>
  <div class="card"><div class="label">BIAS</div><div class="kpi num {bias_cls}">{bias}</div></div>
  <div class="card"><div class="label">SUPPORT</div><div class="kpi num">{support}</div></div>
  <div class="card"><div class="label">RESISTANCE</div><div class="kpi num">{resistance}</div></div>{sr_extra}
</div>"""


def render_filter_grid(in_window, oi_active, spot_vs_vwap, vwap_proxy,
                       pcr_momentum, total_ce_delta, total_pe_delta,
                       sideways_info=None, cooldown_info=None):
    """Filter status cards for index tabs."""
    tw_c = "#00E5A0" if in_window else "#FF4D6D"
    oi_c = "#00E5A0" if oi_active else "#FF4D6D"
    vw_c = "#00E5A0" if spot_vs_vwap == "ABOVE" else "#FF4D6D"
    pm_c = "#00E5A0" if pcr_momentum != "FLAT" else "#F59E0B"

    extra_cards = ""
    if sideways_info and sideways_info.get("is_sideways"):
        strength = sideways_info.get("strength", "MILD")
        sw_c = "#FF4D6D" if strength == "STRONG SIDEWAYS" else "#F59E0B"
        extra_cards += f"""
  <div class="card"><div class="label">SIDEWAYS</div>
    <div class="num" style="color:{sw_c};font-size:15px;">{strength}</div></div>"""

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
  <div class="card"><div class="label">COOLDOWN</div>
    <div class="num" style="color:#4F46E5;font-size:15px;">{cooldown_reason}</div></div>"""

    return f"""
<div class="filter-grid">
  <div class="card"><div class="label">TIME WINDOW</div>
    <div class="num" style="color:{tw_c};font-size:15px;">{"IN WINDOW" if in_window else "CLOSED"}</div></div>
  <div class="card"><div class="label">OI MARKET</div>
    <div class="num" style="color:{oi_c};font-size:15px;">{"ACTIVE" if oi_active else "NO DATA"}</div></div>
  <div class="card"><div class="label">VS VWAP ({vwap_proxy})</div>
    <div class="num" style="color:{vw_c};font-size:15px;">{spot_vs_vwap}</div></div>
  <div class="card"><div class="label">PCR MOMENTUM</div>
    <div class="num" style="color:{pm_c};font-size:15px;">{pcr_momentum}</div></div>
  <div class="card"><div class="label">OI FLOW (CE Δ / PE Δ)</div>
    <div class="num" style="color:#F59E0B;font-size:15px;"><span class="c-ce">{_safe_int(total_ce_delta)}</span> / <span class="c-pe">{_safe_int(total_pe_delta)}</span></div></div>{extra_cards}
</div>"""


def render_signal_card(idx, final_signal, final_conf, raw_signal, confidence,
                       pcr, buffer, filter_reason="", confidence_score=0,
                       oi_unusual=False, spot=None, atm=None):
    """Signal display card + mobile sticky signal bar."""
    if "CE" in final_signal:
        card_class = "sc-ce"
        signal_color = "#00E5A0"
        bar_fill_cls = "conf-bar-high"
        state_badge = '<span class="badge badge-ce">BULLISH CE</span>'
    elif "PE" in final_signal:
        card_class = "sc-pe"
        signal_color = "#FF4D6D"
        bar_fill_cls = "conf-bar-low"
        state_badge = '<span class="badge badge-pe">BEARISH PE</span>'
    else:
        card_class = "sc-wait"
        signal_color = "#F59E0B"
        bar_fill_cls = "conf-bar-medium"
        state_badge = '<span class="badge badge-amber">WAIT / NEUTRAL</span>'

    score_bar = f"""
<div class="conf-bar-outer"><div class="conf-bar-inner {bar_fill_cls}" style="width:{confidence_score}%;"></div></div>
<div style="font-size:11px;color:var(--text-2);margin-top:4px;display:flex;justify-content:space-between;align-items:center;">
  <span>CONFIDENCE SCORE: <b class="num" style="color:#ffffff;">{confidence_score}/100</b></span>
  <span>{final_conf}</span>
</div>"""

    unusual_badge = ""
    if oi_unusual:
        unusual_badge = ' <span class="badge badge-warning" style="margin-left:6px;">UNUSUAL OI</span>'

    buf_str = ", ".join(buffer[-3:]) if buffer else ""
    filter_txt = f" | {filter_reason}" if filter_reason else ""

    spot_str = f"{round(float(spot), 2):,}" if spot is not None else ""
    atm_str = f"ATM {atm}" if atm is not None else ""

    sticky_bar = f"""
<div class="mobile-signal-bar">
  <div>
    <div style="font-size:10px;font-weight:700;color:var(--text-2);">{idx} {state_badge}</div>
    <div style="font-family:'Space Grotesk',sans-serif;font-size:17px;font-weight:800;color:{signal_color};display:flex;align-items:center;gap:6px;">
      <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:{signal_color};"></span>
      {final_signal}
    </div>
  </div>
  <div style="text-align:right;">
    <div class="num" style="font-size:14px;color:#ffffff;">{spot_str}</div>
    <div style="font-size:10px;color:var(--text-2);">{atm_str} • {final_conf}</div>
  </div>
</div>"""

    return f"""{sticky_bar}
<div class="signal-card {card_class}">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;margin-bottom:8px;">
    <div>
      <div class="label">{idx} SIGNAL</div>
      <h2 class="signal-hero">{final_signal}</h2>
    </div>
    <div style="text-align:right;">
      {state_badge}{unusual_badge}
    </div>
  </div>
  {score_bar}
  <div style="font-size:11px;color:var(--text-2);margin-top:12px;letter-spacing:0.02em;">
    RAW: <span style="color:var(--text-1);font-weight:600;">{raw_signal} ({confidence})</span> | PCR: <span class="num" style="color:var(--text-1);">{pcr}</span> | BUFFER: <span style="color:var(--text-1);">{buf_str}</span>{filter_txt}
  </div>
</div>
{sticky_bar}"""


def render_trade_entry_card(lbl, atm_actual, ep, sl_p, tgt_p, qty, ml, tp):
    """Trade entry details card shown when signal is active."""
    return f"""
<div class="card" style="border-left:4px solid var(--indigo);background:var(--indigo-dim);">
  <div class="label" style="color:#818cf8;margin-bottom:12px;">ACTIVE TRADE CONFIGURATION</div>
  <div style="display:flex;flex-wrap:wrap;gap:20px 28px;align-items:center;">
    <div><div class="label">SIGNAL</div><div class="num" style="font-size:17px;color:#ffffff;">{lbl} @ {atm_actual}</div></div>
    <div><div class="label">ENTRY</div><div class="num" style="font-size:17px;color:#ffffff;">₹{ep}</div></div>
    <div><div class="label">STOP LOSS</div><div class="num c-pe" style="font-size:17px;">₹{sl_p}</div></div>
    <div><div class="label">TARGET</div><div class="num c-ce" style="font-size:17px;">₹{tgt_p}</div></div>
    <div><div class="label">QUANTITY</div><div class="num" style="font-size:17px;color:#ffffff;">{qty} <span style="font-size:11px;color:var(--text-2);">(1 Lot)</span></div></div>
    <div><div class="label">MAX LOSS</div><div class="num c-pe" style="font-size:17px;">₹{ml}</div></div>
    <div><div class="label">TARGET P&L</div><div class="num c-ce" style="font-size:17px;">₹{tp}</div></div>
  </div>
</div>"""


def render_trap_alert(trap):
    """Trap warning banner."""
    return f'<div class="trap-alert">🚨 TRAP ALERT: {trap} DETECTED</div>'


def render_tracker_grid(idx, capital, closed_count, rpnl, rc, prog):
    """P&L tracker cards."""
    pc = "c-ce" if rpnl >= 0 else "c-pe"
    return f"""
<div class="tracker-grid">
  <div class="card"><div class="label">CAPITAL</div><div class="kpi num">₹{capital:,}</div></div>
  <div class="card"><div class="label">CLOSED TRADES</div><div class="kpi num">{closed_count}</div></div>
  <div class="card"><div class="label">REALIZED P&L</div><div class="kpi num {pc}">₹{rpnl:,.0f}</div></div>
  <div class="card"><div class="label">RUNNING CAP</div><div class="kpi num">₹{rc:,.0f}</div></div>
  <div class="card"><div class="label">DAILY PROGRESS</div><div class="kpi num">{round(prog*100)}%</div></div>
</div>"""


def render_risk_card(atr_sl=None, cooldown_remaining=0,
                     daily_losses=0, max_daily_losses=3):
    """Risk HUD card."""
    items = []
    if atr_sl is not None:
        items.append(f'<div><div class="label">ATR SL</div><div class="num c-amber" style="font-size:17px;">₹{atr_sl}</div></div>')
    if cooldown_remaining > 0:
        items.append(f'<div><div class="label">COOLDOWN</div><div class="num c-indigo" style="font-size:17px;">{cooldown_remaining}s</div></div>')
    items.append(f'<div><div class="label">DAILY LOSSES</div><div class="num c-pe" style="font-size:17px;">{daily_losses} / {max_daily_losses}</div></div>')

    if not items:
        return ""

    items_html = "\n    ".join(items)
    return f"""
<div class="card" style="border-left:4px solid var(--indigo);">
  <div class="label" style="color:#818cf8;width:100%;margin-bottom:8px;">RISK HUD</div>
  <div style="display:flex;gap:24px 32px;flex-wrap:wrap;">
    {items_html}
  </div>
</div>"""


def render_expander_open_trade(trade, sc):
    """Open trade card inside per-index expander."""
    norm = normalize_trade(trade)
    sig_c = "#00E5A0" if "CE" in norm["option_type"] else "#FF4D6D"
    upl_c = "#00E5A0" if norm["pnl"] >= 0 else "#FF4D6D"

    return f"""
<div class="card" style="border-left:4px solid {sig_c};padding:12px 14px;">
  <div style="display:flex;gap:18px 24px;flex-wrap:wrap;align-items:center;">
    <div><div class="label">SIGNAL</div><div class="num" style="font-size:16px;color:{sig_c};">{norm['signal']}</div></div>
    <div><div class="label">STRIKE</div><div class="num" style="font-size:16px;">{norm['strike']}</div></div>
    <div><div class="label">ENTRY</div><div class="num" style="font-size:16px;">₹{norm['entry_price']:.2f}</div></div>
    <div><div class="label">LIVE</div><div class="num" style="font-size:16px;color:{upl_c};">₹{norm['live_price']:.2f}</div></div>
    <div><div class="label">SL</div><div class="num c-pe" style="font-size:16px;">₹{norm['stop_loss']}</div></div>
    <div><div class="label">TARGET</div><div class="num c-ce" style="font-size:16px;">₹{norm['target']}</div></div>
    <div><div class="label">QTY</div><div class="num" style="font-size:16px;">{norm['quantity']}</div></div>
    <div style="margin-left:auto;"><div class="label">UNREALIZED P&L</div><div class="num" style="font-size:20px;color:{upl_c};">{norm['pnl_disp']}</div></div>
  </div>
</div>"""
