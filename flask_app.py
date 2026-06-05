import os
import json
import datetime
import threading
from flask import Flask, render_template, jsonify, request
import pandas as pd
import statistics

from config import (
    INDEX_CONFIG, IST, CAPITAL, DAILY_TGT,
    MARKET_OPEN_TIME, MARKET_CLOSE_TIME, AUTO_SQUARE_OFF_TIME,
    NO_NEW_TRADE_TIME, MIN_ENTRY_PRICE, is_expiry_day, MAX_DAILY_LOSSES,
    COOLDOWN_SECONDS, ATR_PERIOD, ATR_SL_MULTIPLIER, LOG_DIR, DAILY_REPORT_TIME
)

from core.signal_engine import SignalEngine
from core.risk_manager import RiskManager
from core.data_fetcher import get_fetcher
from core.trade_manager import TradeManager
from analytics.trade_journal import TradeJournal
from notifications.telegram import TelegramNotifier
from utils.logger import setup_logger

app = Flask(__name__)
logger = setup_logger()

signal_engine = SignalEngine()
risk_mgr = RiskManager()
notifier = TelegramNotifier()
trade_mgr = TradeManager(notifier=notifier, risk_mgr=risk_mgr)
journal = TradeJournal()
fetcher = get_fetcher()

state = {}
state_locks = {}
for idx in INDEX_CONFIG:
    state_locks[idx] = threading.Lock()
    state[idx] = {
        "trade_log": trade_mgr.load_log(idx),
        "last_signal": "WAIT",
        "last_played": "WAIT",
        "signal_buffer": [],
        "pcr_history": [],
        "spot_history": [],
        "prev_df": None,
        "oi_baseline": None,
        "last_sl_time": None
    }


def _safe_int(val, default=0):
    """Safely convert a value to int, returning default on NaN/None/error."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/close_trade", methods=["POST"])
def close_trade():
    data = request.json
    if not data:
        return jsonify({"error": "Missing request body"}), 400
    idx = data.get("idx")
    entry_time = data.get("entryTime")
    strike = data.get("strike")
    signal = data.get("signal")
    lp = data.get("livePrice")
    if not all([idx, entry_time, strike, signal]) or lp is None:
        return jsonify({"error": "Missing required fields: idx, entryTime, strike, signal, livePrice"}), 400
    if idx not in state:
        return jsonify({"error": f"Invalid index: {idx}"}), 400
    
    with state_locks[idx]:
        tlog = state[idx]["trade_log"]
        for t in tlog:
            if t["Entry Time"] == entry_time and str(t["Strike"]) == str(strike) and t["Signal"] == signal and t["Status"] == "OPEN":
                trade_mgr.close_manually(idx, t, lp)
                trade_mgr.save_log(idx, tlog)
                journal.update_trade(
                    t.get("_journal_id", ""),
                    {
                        "Exit Time": t.get("Exit Time"),
                        "Exit Price": t.get("Exit Price"),
                        "Actual P&L ₹": t.get("Actual P&L ₹"),
                        "Status": "CLOSED",
                        "Result": "🟡 MANUAL",
                    },
                    t
                )
                break
            
    return jsonify({"success": True})

@app.route("/api/reset/<idx>", methods=["POST"])
def reset_idx(idx):
    if idx not in state:
        return jsonify({"error": "Invalid index"}), 400
    with state_locks[idx]:
        state[idx]["trade_log"] = []
        state[idx]["last_signal"] = "WAIT"
        state[idx]["last_played"] = "WAIT"
        state[idx]["signal_buffer"] = []
        state[idx]["oi_baseline"] = None
        state[idx]["prev_df"] = None
        f = os.path.join(LOG_DIR, f"trade_log_{idx}_{datetime.datetime.now(IST).strftime('%Y-%m-%d')}.csv")
        if os.path.exists(f):
            os.remove(f)
    return jsonify({"success": True})

@app.route("/api/test_alert/<idx>", methods=["POST"])
def test_alert(idx):
    if idx not in INDEX_CONFIG:
        return jsonify({"error": "Invalid index"}), 400
    now_t = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
    notifier.send(
        f"🧪 *V12 {idx} TEST ALERT*\n🟢 SIGNAL: BUY CE\n"
        f"📍 Strike: `TEST` | Spot: `TEST`\n"
        f"⏰ Time: `{now_t}` ← TEST"
    )
    return jsonify({"success": True})

@app.route("/api/send_report", methods=["POST"])
def send_report():
    current_date = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    total_pnl = 0
    total_trades = 0
    wins = 0
    losses = 0
    report_lines = [f"📊 *DAILY P&L REPORT — {current_date}* (Manual)\n"]

    for idx in INDEX_CONFIG:
        tlog = state[idx].get("trade_log", [])
        if not tlog:
            continue
        df = pd.DataFrame(tlog)
        closed = df[df["Status"] == "CLOSED"] if not df.empty else pd.DataFrame()
        if closed.empty:
            continue
        pnl_s = closed["Actual P&L ₹"].apply(pd.to_numeric, errors="coerce")
        idx_pnl = pnl_s.sum()
        idx_trades = len(closed)
        idx_wins = (pnl_s > 0).sum()
        idx_losses = (pnl_s <= 0).sum()
        total_pnl += idx_pnl
        total_trades += idx_trades
        wins += idx_wins
        losses += idx_losses
        emoji = "🟢" if idx_pnl >= 0 else "🔴"
        report_lines.append(f"{emoji} *{idx}*: ₹{idx_pnl:,.0f} ({idx_wins}W/{idx_losses}L)")

    report_lines.append(f"\n📈 *TOTAL TRADES*: {total_trades} ({wins}W / {losses}L)")
    final_emoji = "🟢" if total_pnl >= 0 else "🔴"
    report_lines.append(f"{final_emoji} *NET P&L*: ₹{total_pnl:,.0f}")

    if total_trades > 0:
        notifier.send_daily_report(report_lines)
        return jsonify({"success": True, "message": "Report sent"})
    return jsonify({"success": False, "message": "No closed trades to report"})

@app.route("/api/analytics")
def get_analytics():
    stats = journal.get_analytics(days=7)
    stats["all_trades"] = journal.get_all_trades()
    return jsonify(stats)

@app.route("/api/refresh/<idx>")
def refresh_idx(idx):
    if idx not in INDEX_CONFIG:
        return jsonify({"error": "Invalid index"}), 400
    
    cfg = INDEX_CONFIG[idx]
    now_ist = datetime.datetime.now(IST)
    now_time = now_ist.time()
    in_window = MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME
    
    data = fetcher.fetch_option_chain(idx)
    if not data:
        return jsonify({"error": "Data unavailable"})
    
    records = data["records"]["data"]
    spot = data["records"]["underlyingValue"]
    
    step = cfg["step"]
    rng = cfg["rng"]
    atm = round(spot / step) * step
    
    rows = []
    for item in records:
        s = item.get("strikePrice", 0)
        if abs(s - atm) <= rng:
            ce = item.get("CE") or {}
            pe = item.get("PE") or {}
            rows.append({
                "Strike": s,
                "CE LTP": ce.get("lastPrice", 0),
                "CE OI": ce.get("openInterest", 0),
                "CE OI Δ": 0,
                "PE LTP": pe.get("lastPrice", 0),
                "PE OI": pe.get("openInterest", 0),
                "PE OI Δ": 0,
            })
    df = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)
    if df.empty:
        return jsonify({"error": "No data"})

    with state_locks[idx]:
        md = signal_engine.compute_market_data(
            df, spot, step, idx, 
            state[idx]["spot_history"], 
            state[idx]["pcr_history"], 
            state[idx]["prev_df"], 
            state[idx]["oi_baseline"]
        )

        if md is None:
            return jsonify({"error": "No market data available"})
        
        state[idx]["prev_df"] = md["prev_df"]
        state[idx]["oi_baseline"] = md["oi_baseline"]
        state[idx]["pcr_history"] = md["pcr_history"]
        state[idx]["spot_history"] = md["spot_history"]

        signal, confidence, filter_reason = signal_engine.generate_signal(md, in_window)
        trap = signal_engine.detect_trap(spot, md["support"], md["resistance"], md["total_ce_delta"], md["total_pe_delta"])
        
        buf = state[idx]["signal_buffer"]
        final_signal, final_conf, updated_buf = signal_engine.confirm_signal(signal, confidence, buf)
        state[idx]["signal_buffer"] = updated_buf

        conf_score = signal_engine.compute_confidence_score(md, signal, trap)
        
        events = trade_mgr.update_live_prices(idx, state[idx]["trade_log"], records, now_ist)
        if events:
            trade_mgr.save_log(idx, state[idx]["trade_log"])
            for ev in events:
                if ev["type"] == "SL_HIT":
                    state[idx]["last_sl_time"] = now_ist
                state[idx]["last_signal"] = "WAIT"
                journal.update_trade(ev["trade"].get("_journal_id", ""), {
                    "Exit Time": ev["trade"].get("Exit Time"),
                    "Exit Price": ev["trade"].get("Exit Price"),
                    "Actual P&L ₹": ev["trade"].get("Actual P&L ₹"),
                    "Status": ev["trade"].get("Status"),
                    "Result": ev["trade"].get("Result"),
                }, ev["trade"])
            
        open_exists = any(t.get("Status") == "OPEN" for t in state[idx]["trade_log"])
        if open_exists and final_signal in ("BUY CE", "BUY PE"):
            final_signal = "WAIT"
            final_conf = "LOW"
            
        cooldown_info = risk_mgr.should_allow_trade(idx, state[idx]["trade_log"], now_ist)
        daily_limits = risk_mgr.check_daily_limits(state[idx]["trade_log"])
        trade_allowed = cooldown_info.get("allowed", True) if isinstance(cooldown_info, dict) else cooldown_info[0]
        daily_allowed = daily_limits.get("allowed", True) if isinstance(daily_limits, dict) else daily_limits[0]
        
        ce_price = round(float(md["atm_row"]["CE LTP"]), 2)
        pe_price = round(float(md["atm_row"]["PE LTP"]), 2)
        
        too_late = now_ist.time() >= NO_NEW_TRADE_TIME
        expiry_today = is_expiry_day(idx)
        ep = ce_price if final_signal == "BUY CE" else pe_price
        price_too_low = ep < MIN_ENTRY_PRICE and not expiry_today
        oi_unusual = md.get("oi_unusual_activity", False)
        
        can_enter = not too_late and not price_too_low and not oi_unusual and conf_score > 20
        
        if (final_signal in ("BUY CE", "BUY PE") and final_conf in ("HIGH", "MEDIUM") 
            and final_signal != state[idx]["last_signal"] 
            and trade_allowed and daily_allowed and can_enter):
            
            lot = cfg["lot"]
            qty, sl_p, tgt_p, ml, tp = risk_mgr.calc_trade_with_atr(ep, lot, md["spot_history"])
            now_str = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
            
            trade_entry = {
                "Entry Time": now_str, "Exit Time": None,
                "Index": idx, "Signal": final_signal,
                "Spot": round(spot, 2), "Strike": md["atm_actual"],
                "Entry Price": ep, "Live Price": ep,
                "Exit Price": None, "Stop Loss": sl_p,
                "Target": tgt_p, "Qty": qty,
                "Max Loss ₹": ml, "Target P&L ₹": tp,
                "Actual P&L ₹": None, "Status": "OPEN",
                "Result": "⏳ OPEN",
            }
            state[idx]["trade_log"].insert(0, trade_entry)
            trade_mgr.save_log(idx, state[idx]["trade_log"])
            state[idx]["last_signal"] = final_signal

            journal_id = journal.record_trade(trade_entry, {
                "pcr": md["pcr"], "vwap": md["vwap_proxy"],
                "oi_delta_ce": md["total_ce_delta"],
                "oi_delta_pe": md["total_pe_delta"],
                "confidence_score": conf_score,
                "pcr_momentum": md["pcr_momentum"],
                "trap": trap, "buffer_state": updated_buf[-3:],
            })
            trade_entry["_journal_id"] = journal_id
            
            trade_mgr.notifier.send_signal_alert(
                idx=idx, signal=final_signal, strike=md["atm_actual"], spot=round(spot, 2),
                entry=ep, sl=sl_p, tgt=tgt_p, qty=qty, ml=ml, tp=tp,
                conf=final_conf, score=conf_score, time_str=now_str,
            )
        elif final_signal == "WAIT" and state[idx]["last_signal"] != "WAIT" and not open_exists:
            state[idx]["last_signal"] = "WAIT"
            state[idx]["last_played"] = "WAIT"

        sideways_is, sideways_strength = signal_engine.detect_sideways(md["spot_history"], md["pcr"])
        
        closed_trades = [t for t in state[idx]["trade_log"] if t.get("Status") == "CLOSED"]
        consec_losses = 0
        idx_pnl = sum(float(t.get("Actual P&L ₹") or 0) for t in closed_trades)
        
        for t in closed_trades:
            if "LOSS" in str(t.get("Result", "")):
                consec_losses += 1
            else:
                break
                
        atr_sl_display = None
        if len(md["spot_history"]) >= 14:
            diffs = [abs(md["spot_history"][i] - md["spot_history"][i-1]) for i in range(1, len(md["spot_history"]))]
            if len(diffs) >= ATR_PERIOD:
                atr_val = statistics.mean(diffs[-ATR_PERIOD:])
                atr_sl_display = round(atr_val * ATR_SL_MULTIPLIER, 2)
                
        cooldown_remaining = 0
        closed_trades_idx = [t for t in state[idx]["trade_log"] if t.get("Status") == "CLOSED" and t.get("Result", "")]
        if closed_trades_idx:
            last_closed = closed_trades_idx[0]
            if "LOSS" in str(last_closed.get("Result", "")):
                exit_time_str = last_closed.get("Exit Time", "")
                if exit_time_str:
                    try:
                        exit_time = datetime.datetime.strptime(exit_time_str, "%I:%M:%S %p").replace(
                            year=now_ist.year, month=now_ist.month, day=now_ist.day, tzinfo=IST)
                        if exit_time > now_ist:
                            exit_time -= datetime.timedelta(days=1)
                        elapsed = (now_ist - exit_time).total_seconds()
                        if elapsed < COOLDOWN_SECONDS:
                            cooldown_remaining = int(COOLDOWN_SECONDS - elapsed)
                    except Exception:
                        pass

        option_chain = md["df"].drop(columns=["dist"], errors="ignore").to_dict(orient="records")

    return jsonify({
        "spot": float(spot),
        "pcr": float(md["pcr"]),
        "atm": float(md["atm_actual"]),
        "bias": str(md["bias"]),
        "support": float(md["support"]) if md.get("support") else None,
        "resistance": float(md["resistance"]) if md.get("resistance") else None,
        "secondary_support": float(md.get("secondary_support")) if pd.notnull(md.get("secondary_support")) else None,
        "secondary_resistance": float(md.get("secondary_resistance")) if pd.notnull(md.get("secondary_resistance")) else None,
        "signal": str(final_signal),
        "confidence": str(final_conf),
        "conf_score": float(conf_score),
        "trap": str(trap),
        "trade_log": state[idx]["trade_log"],
        "option_chain": option_chain,
        "signal_buffer": [str(s) for s in updated_buf],
        "filter_reason": str(filter_reason),
        "oi_unusual_activity": bool(md.get("oi_unusual_activity", False)),
        "idx_pnl": float(idx_pnl),
        "closed_count": int(len(closed_trades)),
        "filters": {
            "in_window": bool(in_window),
            "oi_active": bool(md.get("oi_active", True)),
            "spot_vs_vwap": str(md["spot_vs_vwap"]),
            "vwap_proxy": float(md["vwap_proxy"]),
            "pcr_momentum": str(md["pcr_momentum"]),
            "total_ce_delta": _safe_int(md["total_ce_delta"]),
            "total_pe_delta": _safe_int(md["total_pe_delta"]),
            "sideways_is": bool(sideways_is),
            "sideways_strength": str(sideways_strength)
        },
        "risk": {
            "daily_losses": int(consec_losses),
            "max_daily_losses": int(MAX_DAILY_LOSSES),
            "daily_tgt": float(DAILY_TGT),
            "capital": float(CAPITAL),
            "atr_sl": float(atr_sl_display) if atr_sl_display is not None else None,
            "cooldown_remaining": int(cooldown_remaining)
        }
    })

if __name__ == "__main__":
    app.run(port=5000, debug=True, use_reloader=False)
