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

    # Confidence Score extraction
    conf_score = raw.get("Confidence Score") or raw.get("confidence_score") or raw.get("Score")
    if conf_score is None and isinstance(raw.get("signal_metadata"), dict):
        conf_score = raw["signal_metadata"].get("confidence_score")

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
        "conf_score": conf_score,
    }


# ──────────────────────────────────────────────────
# 2. TERMINAL HEADER & TICKER
# ──────────────────────────────────────────────────
def render_app_header(
    is_market_open: bool,
    is_connected: bool,
    datetime_str: str,
    ws_connected: bool = False,
    ticker_items: Optional[List[Dict[str, Any]]] = None,
    scanner_status: Optional[Dict[str, Any]] = None,
    *args,
    **kwargs,
) -> str:
    """Renders the dashboard's branded header, market strip, and scanner status."""
    if "ws_connected" in kwargs:
        ws_connected = kwargs["ws_connected"]
    scanner_active = kwargs.get("scanner_active", True)
    market_status = "Market open" if is_market_open else "Market closed"
    market_cls = "market-open" if is_market_open else "market-closed"
    feed_cls = "header-indicator-on" if is_connected else "header-indicator-off"
    ws_cls = "header-indicator-on" if ws_connected else "header-indicator-off"
    market_ticker = render_market_ticker(ticker_items or [])
    scan_count = (scanner_status or {}).get("total_scans", 0)
    last_scan = (scanner_status or {}).get("last_scan", "Awaiting first cycle")
    if scanner_active:
        scan_status = f"Auto-scan 3x active · {scan_count:,} cycles · {last_scan}"
        scan_cls = "scanner-active"
    else:
        scan_status = "Auto-scan disabled · Automatic entries are paused."
        scan_cls = "scanner-disabled"

    return f"""
<section class="dashboard-top">
  <div class="app-header">
    <div class="app-header-left">
      <h1><span class="brand-v">V12</span><span class="brand-pro">PRO MAX</span></h1>
      <p>Algorithmic trading engine</p>
    </div>
    <div class="app-header-right">
      <div class="app-header-status">
        <span class="header-indicator header-indicator-purple {ws_cls}" role="img" aria-label="WebSocket {'connected' if ws_connected else 'standby'}" title="WebSocket {'connected' if ws_connected else 'standby'}">⚡</span>
        <span class="header-indicator header-indicator-red {feed_cls}" role="img" aria-label="Market data {'available' if is_connected else 'unavailable'}" title="Market data {'available' if is_connected else 'unavailable'}">◉</span>
        <span class="header-status-divider"></span>
        <span class="market-status {market_cls}"><i></i>{market_status}</span>
      </div>
      <div class="header-datetime">{datetime_str}</div>
    </div>
  </div>
  {market_ticker}
  <div class="scanner-status-line {scan_cls}">
    <span class="scanner-status-icon" aria-hidden="true"></span>
    <span>{scan_status}</span>
  </div>
</section>"""


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
<div class="positions-summary">
  <div class="label positions-summary-heading">OPEN POSITIONS SUMMARY</div>
  <div class="positions-summary-grid">
    <div class="kpi-card positions-summary-card">
      <div class="label">OPEN TRADES</div>
      <div class="kpi num">{trades_disp}</div>
    </div>
    <div class="kpi-card positions-summary-card">
      <div class="label">TODAY P&L</div>
      <div class="kpi num {pnl_cls}">{pnl_disp}</div>
    </div>
    <div class="kpi-card positions-summary-card">
      <div class="label">MAX LOSS</div>
      <div class="kpi num">{max_loss_disp}</div>
    </div>
    <div class="kpi-card positions-summary-card">
      <div class="label">WIN RATE</div>
      <div class="kpi num">{win_rate_disp}</div>
      <div class="win-rate-track"><span style="width:{max(0.0, min(win_rate or 0.0, 100.0)):.1f}%;"></span></div>
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
    direction_label = f"{direction} {option_type}".strip()
    trade_status = str(t.get("status") or "OPEN").upper()
    status_cls = "trade-status-closed" if trade_status == "CLOSED" else "trade-status-open"
    live_label = "Last quote · stale" if t.get("raw", {}).get("_live_price_is_stale") else "Live"

    spot_str = f"₹{_safe_float(spot):,.2f}" if spot is not None else "N/A"
    ml_str = f"₹{_safe_float(ml):,.0f}" if ml is not None else "N/A"
    tp_str = f"₹{_safe_float(tp):,.0f}" if tp is not None else "N/A"
    pnl_sign = "+" if pnl >= 0 else "−"
    pnl_text = f"{pnl_sign}₹{abs(pnl):,.2f}"

    opt_label = f"{strike} {option_type}".strip() if option_type else str(strike)
    progress = max(0.0, min(100.0, _safe_float(progress_pct)))
    low_price = min(value for value in (sl, ev, lv, tgt) if value > 0) if any(
        value > 0 for value in (sl, ev, lv, tgt)
    ) else 0.0
    high_price = max(sl, ev, lv, tgt)
    price_range = high_price - low_price
    if price_range > 0 and all(value > 0 for value in (sl, ev, lv, tgt)):
        sl_position = (sl - low_price) / price_range * 100
        entry_position = (ev - low_price) / price_range * 100
        target_position = (tgt - low_price) / price_range * 100
        live_position = (lv - low_price) / price_range * 100
        track_markup = f"""
  <div class="trade-price-track" aria-label="Stop loss {sl:.2f}, entry {ev:.2f}, live {lv:.2f}, target {tgt:.2f}">
    <div class="trade-track-base"></div>
    <div class="trade-track-risk" style="left:{min(sl_position, entry_position):.2f}%;width:{abs(entry_position - sl_position):.2f}%;"></div>
    <div class="trade-track-reward" style="left:{min(entry_position, target_position):.2f}%;width:{abs(target_position - entry_position):.2f}%;"></div>
    <span class="trade-track-marker trade-marker-sl" style="left:{sl_position:.2f}%;"></span>
    <span class="trade-track-marker trade-marker-entry" style="left:{entry_position:.2f}%;"></span>
    <span class="trade-track-marker trade-marker-live" style="left:{live_position:.2f}%;"></span>
    <span class="trade-track-marker trade-marker-target" style="left:{target_position:.2f}%;"></span>
  </div>
  <div class="trade-track-labels">
    <span class="trade-stop-label">SL <b>₹{sl:.2f}</b></span>
    <span class="trade-entry-label">Entry <b>₹{ev:.2f}</b></span>
    <span class="trade-target-label">Target <b>₹{tgt:.2f}</b></span>
  </div>"""
    else:
        fill_cls = "fill-ce" if is_ce else "fill-pe"
        track_markup = f"""
  <div class="progress-bar trade-progress-fallback">
    <div class="progress-fill {fill_cls}" style="width: {progress}%"></div>
  </div>"""

    return f"""
<div class="trade-card {card_cls}">
  <div class="trade-header">
    <div class="trade-title">
      <span class="trade-instrument">{instrument}</span>
      <span class="trade-direction {accent_cls}">{direction_label}</span>
      <span class="trade-contract">{opt_label}</span>
      <span class="trade-status {status_cls}">{trade_status}</span>
    </div>
    <div class="trade-pnl {pnl_cls}">
      {pnl_text}
    </div>
  </div>
  <div class="trade-live-line">
    <span>{live_label}</span><strong class="{pnl_cls}">₹{lv:.2f}</strong>
  </div>
  {track_markup}
  <div class="trade-detail-row">
    <span>Qty <b>{qty}</b></span>
    <span>Spot <b>{spot_str}</b></span>
    <span>Max loss <b class="c-pe">{ml_str}</b></span>
    <span>Target P&amp;L <b class="c-ce">{tp_str}</b></span>
    <span>Progress <b>{progress:.1f}%</b></span>
    <span>Entry <b>{etime}</b></span>
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
    """Render the index price, bias, and PCR in a compact signal overview."""
    bias_str = str(bias).upper()
    bias_cls = "c-ce" if "BULL" in bias_str else ("c-pe" if "BEAR" in bias_str else "c-amber")
    bias_color = "#00E5A0" if "BULL" in bias_str else ("#FF4D6D" if "BEAR" in bias_str else "#F59E0B")
    bias_icon = "↗" if "BULL" in bias_str else ("↘" if "BEAR" in bias_str else "→")
    pcr_value = _safe_float(pcr)
    pcr_progress = max(0.0, min(pcr_value / 2.0, 1.0))
    gauge_length = 188.5
    gauge_offset = gauge_length * (1.0 - pcr_progress)

    return f"""
<section class="signal-overview">
  <div class="signal-overview-main">
    <div class="signal-price-block">
      <div class="signal-eyebrow">{idx} <span>·</span> ATM {atm_actual}</div>
      <div class="signal-spot">{round(spot, 2):,.2f}</div>
      <div class="signal-bias {bias_cls}"><span class="signal-bias-icon">{bias_icon}</span>{bias} bias</div>
    </div>
    <div class="pcr-gauge" role="img" aria-label="PCR {pcr_value:.2f}">
      <svg viewBox="0 0 160 100" aria-hidden="true">
        <path class="pcr-gauge-track" d="M 20 80 A 60 60 0 0 1 140 80" />
        <path class="pcr-gauge-value" d="M 20 80 A 60 60 0 0 1 140 80"
          style="stroke:{bias_color};stroke-dasharray:{gauge_length};stroke-dashoffset:{gauge_offset:.2f};" />
      </svg>
      <div class="pcr-gauge-number">{pcr_value:.2f}</div>
      <div class="pcr-gauge-label">PCR</div>
    </div>
  </div>
</section>"""


def render_filter_grid(in_window, oi_active, spot_vs_vwap, vwap_proxy,
                       pcr_momentum, total_ce_delta, total_pe_delta,
                       sideways_info=None, cooldown_info=None,
                       trend_15m=None, trend_15m_ema=0.0):
    """Render primary OI context and collapsible secondary signal diagnostics."""
    tw_c = "#00E5A0" if in_window else "#FF4D6D"
    oi_c = "#00E5A0" if oi_active else "#FF4D6D"
    vw_c = "#00E5A0" if spot_vs_vwap == "ABOVE" else "#FF4D6D"
    pm_c = "#00E5A0" if pcr_momentum != "FLAT" else "#F59E0B"

    extra_cards = ""
    cooldown_card = ""
    if trend_15m and trend_15m != "NEUTRAL":
        t_c = "#00E5A0" if trend_15m == "BULLISH" else "#FF4D6D"
        ema_str = f" ({trend_15m_ema:,.0f})" if trend_15m_ema > 0 else ""
        extra_cards += f"""
  <div class="card"><div class="label">15M TREND (20 EMA)</div>
    <div class="num" style="color:{t_c};font-size:15px;">{trend_15m}{ema_str}</div></div>"""

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
            cooldown_card = f"""
<div class="card cooldown-notice"><div class="label">TRADE PAUSE</div>
  <div class="num" style="color:#a5b4fc;font-size:13px;">{cooldown_reason}</div></div>"""

    return f"""
<div class="signal-context-row">
  <div class="signal-context-stat">
    <span class="signal-overview-label">OI market</span>
    <strong class="signal-overview-value" style="color:{oi_c};">{"Active" if oi_active else "No data"}</strong>
  </div>
  <div class="signal-context-divider"></div>
  <div class="signal-context-stat">
    <span class="signal-overview-label">OI flow · CE Δ / PE Δ</span>
    <strong class="signal-overview-value"><span class="c-ce">{_safe_int(total_ce_delta)}</span> / <span class="c-pe">{_safe_int(total_pe_delta)}</span></strong>
  </div>
</div>
{cooldown_card}
<details class="signal-diagnostics">
  <summary>Signal diagnostics</summary>
  <div class="filter-grid">
    <div class="card"><div class="label">TIME WINDOW</div>
      <div class="num" style="color:{tw_c};font-size:15px;">{"IN WINDOW" if in_window else "CLOSED"}</div></div>
    <div class="card"><div class="label">VS VWAP ({vwap_proxy})</div>
      <div class="num" style="color:{vw_c};font-size:15px;">{spot_vs_vwap}</div></div>
    <div class="card"><div class="label">PCR MOMENTUM</div>
      <div class="num" style="color:{pm_c};font-size:15px;">{pcr_momentum}</div></div>{extra_cards}
  </div>
</details>"""


def render_signal_card(idx, final_signal, final_conf, raw_signal, confidence,
                       pcr, buffer, filter_reason="", confidence_score=0,
                       oi_unusual=False, spot=None, atm=None):
    """Signal display card + mobile sticky signal bar."""
    signal_text = str(final_signal).upper()
    if "CE" in signal_text:
        card_class = "sc-ce"
        signal_color = "#00E5A0"
        state_label = "Bullish"
        action_label = "Sell" if "SELL" in signal_text else "Buy"
    elif "PE" in signal_text:
        card_class = "sc-pe"
        signal_color = "#FF4D6D"
        state_label = "Bearish"
        action_label = "Sell" if "SELL" in signal_text else "Buy"
    else:
        card_class = "sc-wait"
        signal_color = "#F59E0B"
        state_label = "Neutral"
        action_label = "Wait"

    unusual_badge = ""
    if oi_unusual:
        unusual_badge = '<span class="badge badge-warning">UNUSUAL OI</span>'

    try:
        score = max(0, min(100, int(float(confidence_score))))
    except (TypeError, ValueError):
        score = 0
    score_ring = f"conic-gradient({signal_color} {score}%, rgba(148, 163, 184, 0.16) {score}% 100%)"

    recent_buffer = [str(item) for item in buffer[-3:]] if buffer else []
    buffer_bars = "".join(
        f'<span class="signal-buffer-bar {("signal-buffer-active" if item.upper() not in ("WAIT", "NEUTRAL", "") else "signal-buffer-muted")}" title="{item}"></span>'
        for item in recent_buffer
    )
    buffer_bars = buffer_bars or '<span class="signal-buffer-bar signal-buffer-muted"></span>' * 3

    spot_str = f"{round(float(spot), 2):,}" if spot is not None else ""
    atm_str = f"ATM {atm}" if atm is not None else ""
    filter_text = str(filter_reason or "").strip()
    outside_hours = "outside trading hours" in filter_text.lower()
    market_notice = ""
    if outside_hours:
        market_notice = f'<div class="signal-market-notice"><span aria-hidden="true">◉</span><span>{filter_text}</span></div>'
    elif filter_text:
        market_notice = f'<div class="signal-filter-note">{filter_text}</div>'

    sticky_bar = f"""
<div class="mobile-signal-bar">
  <div>
    <div style="font-size:10px;font-weight:700;color:var(--text-2);">{idx} {state_label}</div>
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
  <div class="signal-card-topline">
    <div class="signal-card-eyebrow"><span></span>{idx} signal</div>
    <span class="signal-state-pill">{state_label}</span>
  </div>
  <div class="signal-card-main">
    <div class="signal-card-primary">
      <h2 class="signal-hero">{final_signal}</h2>
      <div class="signal-action-switch" aria-label="Signal action">
        <span class="signal-action-option {("signal-action-selected" if action_label == "Sell" else "")}">Sell</span>
        <span class="signal-action-option {("signal-action-selected" if action_label == "Wait" else "")}">Wait</span>
        <span class="signal-action-option {("signal-action-selected" if action_label == "Buy" else "")}">Buy</span>
      </div>
    </div>
    <div class="signal-confidence" role="img" aria-label="Confidence {score} out of 100, {final_conf}">
      <div class="signal-confidence-ring" style="background:{score_ring};">
        <div class="signal-confidence-inner">
          <strong>{score}</strong>
          <span>{final_conf}</span>
        </div>
      </div>
    </div>
  </div>
  <div class="signal-data-grid">
    <div class="signal-data-cell"><span>Raw</span><strong>{raw_signal} <small>{confidence}</small></strong></div>
    <div class="signal-data-cell"><span>PCR</span><strong>{pcr}</strong></div>
    <div class="signal-data-cell"><span>Buffer</span><div class="signal-buffer-bars">{buffer_bars}</div></div>
  </div>
  {unusual_badge}
  {market_notice}
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
                     daily_losses=0, max_daily_losses=3,
                     trades_today=0, max_trades_today=3):
    """Risk HUD card."""
    items = []
    trade_cls = "c-pe" if trades_today >= max_trades_today else "c-white"
    items.append(f'<div><div class="label">TRADES TODAY</div><div class="num {trade_cls}" style="font-size:17px;">{trades_today} / {max_trades_today}</div></div>')
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


def render_account_capital_hud(portfolio_stats: dict) -> str:
    """Render the account summary in a compact equity-first layout."""
    equity = portfolio_stats.get("total_equity", 0.0)
    cash = portfolio_stats.get("cash_balance", 0.0)
    margin_avail = portfolio_stats.get("available_margin", 0.0)
    margin_used = portfolio_stats.get("margin_used", 0.0)
    rpnl = portfolio_stats.get("realized_pnl", 0.0)
    upnl = portfolio_stats.get("unrealized_pnl", 0.0)
    base = portfolio_stats.get("base_capital", 60000.0)

    equity_color = "#10b981" if equity >= base else "#ef4444"
    rpnl_color = "#10b981" if rpnl >= 0 else "#ef4444"
    upnl_color = "#10b981" if upnl >= 0 else "#ef4444"
    equity_change = equity - base
    equity_change_color = "#10b981" if equity_change >= 0 else "#ef4444"
    equity_change_sign = "+" if equity_change >= 0 else "−"

    return f"""
<section class="account-overview">
  <div class="account-overview-top">
    <span class="account-brand">V12 <small>PRO MAX</small></span>
    <span class="account-cloud-status">● SUPABASE PERSISTED</span>
  </div>
  <div class="account-equity-label">Live net equity</div>
  <div class="account-equity-line">
    <strong class="account-equity" style="color:{equity_color};">₹{equity:,.2f}</strong>
    <span class="account-equity-change" style="color:{equity_change_color};">
      {equity_change_sign}₹{abs(equity_change):,.2f}
    </span>
  </div>
  <div class="account-capital-note">Base ₹{base:,.0f} <span>·</span> Cash ₹{cash:,.2f}</div>
  <div class="account-margin-row">
    <div><span class="account-overview-label">Available margin</span><strong>₹{margin_avail:,.2f}</strong></div>
    <div><span class="account-overview-label">Margin in trades</span><strong class="c-amber">₹{margin_used:,.2f}</strong></div>
    <div><span class="account-overview-label">Floating P&amp;L</span><strong style="color:{upnl_color};">{'+' if upnl >= 0 else '−'}₹{abs(upnl):,.2f}</strong></div>
  </div>
  <span class="account-realized-note">Cumulative realized P&amp;L: <b style="color:{rpnl_color};">{'+' if rpnl >= 0 else '−'}₹{abs(rpnl):,.2f}</b></span>
</section>"""
