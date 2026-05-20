import streamlit as st
import pandas as pd
import datetime, os, requests
import plotly.express as px
from jugaad_data.nse import NSELive

# ── TELEGRAM ──
def send_telegram(msg):
    try:
        token   = st.secrets.get("TELEGRAM_TOKEN","")
        chat_id = st.secrets.get("TELEGRAM_CHAT_ID","")
        if not token or not chat_id: return
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id":chat_id,"text":msg,"parse_mode":"Markdown"},timeout=5)
    except: pass

st.set_page_config(page_title="V12 PRO MAX", page_icon="🧠", layout="wide")
st.markdown("""
<style>
*{box-sizing:border-box;}
.card{padding:12px;border-radius:12px;background:#111827;color:white;
      box-shadow:0 4px 14px rgba(0,0,0,.3);margin-bottom:8px;}
.kpi{font-size:20px;font-weight:700;word-break:break-word;}
.label{color:#9CA3AF;font-size:11px;text-transform:uppercase;letter-spacing:.05em;}
.signal-green{background:linear-gradient(135deg,#064E3B,#065F46);}
.signal-red{background:linear-gradient(135deg,#7F1D1D,#991B1B);}
.signal-yellow{background:linear-gradient(135deg,#78350F,#92400E);}
.trap-alert{background:#DC2626;color:white;font-weight:bold;padding:10px;
            border-radius:8px;text-align:center;margin-bottom:12px;font-size:13px;}
.pnl-green{color:#34D399;font-weight:700;}
.pnl-red{color:#F87171;font-weight:700;}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;margin-bottom:8px;}
.filter-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-bottom:8px;}
.tracker-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-bottom:8px;}
/* Hide loading overlay so refresh is invisible (silent background update) */
[data-testid="stStatusWidget"] {visibility:hidden !important;}
div[data-stale="true"] {opacity:1 !important;}
.stSpinner {display:none !important;}
@media(max-width:640px){
  .kpi{font-size:16px;}.kpi-grid,.filter-grid,.tracker-grid{grid-template-columns:repeat(2,1fr);}
  .card{padding:8px;}[data-testid="stDataFrame"]{font-size:11px;}
}
</style>
""", unsafe_allow_html=True)



# ── CONFIG ──
CAPITAL   = 20_000
MAX_LOSS  = 500
DAILY_TGT = 1_000
IST       = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

INDEX_CONFIG = {
    "NIFTY":     {"step":50,  "lot":65,  "rng":300},
    "BANKNIFTY": {"step":100, "lot":30,  "rng":600},
    "FINNIFTY":  {"step":50,  "lot":60,  "rng":300},
}

LOG_COLS = ["Entry Time","Exit Time","Index","Signal","Spot","Strike",
            "Entry Price","Live Price","Exit Price",
            "Stop Loss","Target","Qty","Max Loss ₹","Target P&L ₹",
            "Actual P&L ₹","Status","Result"]

st.title("🧠 V12 PRO MAX — TRADER DASHBOARD")

# ── FETCH (no cache — always fresh on every autorefresh) ──
def get_data(idx_name):
    try:
        d = NSELive().index_option_chain(idx_name)
        if d and "records" in d and d["records"].get("data"):
            return d
    except Exception as e:
        st.warning(f"⚠️ {idx_name} fetch error: {e}")
    return None

# ── CALC TRADE ──
def calc_trade(ep, lot):
    sl_u  = round(ep*0.25,2); tgt_u = round(ep*1.0,2)
    sl_p  = round(ep-sl_u,2); tgt_p = round(ep+tgt_u,2)
    qty   = max(lot,(int(MAX_LOSS/sl_u)//lot)*lot) if sl_u>0 else lot
    if ep*qty>CAPITAL: qty=max(lot,(int(CAPITAL/ep)//lot)*lot)
    return qty, sl_p, tgt_p, round(sl_u*qty,2), round(tgt_u*qty,2)

# ── PER-INDEX SESSION KEYS ──
def sk(idx, key): return f"{idx}_{key}"

def init_state(idx):
    for k,v in [("trade_log",[]  ),("last_signal","WAIT"),("last_played","WAIT"),
                ("signal_buffer",[]  ),("pcr_history",[]  ),("spot_history",[]  ),
                ("prev_df",None),("oi_baseline",None)]:
        if sk(idx,k) not in st.session_state:
            st.session_state[sk(idx,k)] = v

def load_log(idx):
    f = f"trade_log_{idx}_{datetime.datetime.now().strftime('%Y-%m-%d')}.csv"
    if os.path.exists(f):
        df = pd.read_csv(f)
        for c in LOG_COLS:
            if c not in df.columns: df[c]=None
        return df[LOG_COLS].to_dict("records")
    return []

def save_log(idx):
    log = st.session_state[sk(idx,"trade_log")]
    if log:
        f = f"trade_log_{idx}_{datetime.datetime.now().strftime('%Y-%m-%d')}.csv"
        pd.DataFrame(log)[LOG_COLS].to_csv(f,index=False)

# Init all indices
for idx in INDEX_CONFIG:
    init_state(idx)
    if not st.session_state[sk(idx,"trade_log")]:
        st.session_state[sk(idx,"trade_log")] = load_log(idx)

# ── LIVE PRICE UPDATER (runs every refresh for ALL indices with open trades) ──
def get_atm_prices(idx_name):
    """Lightweight fetch — returns (ce_ltp, pe_ltp, spot) for the ATM strike."""
    try:
        step = INDEX_CONFIG[idx_name]["step"]
        d = NSELive().index_option_chain(idx_name)
        if not d or "records" not in d: return None, None, None
        records = d["records"]["data"]
        spot    = d["records"]["underlyingValue"]
        atm     = round(spot / step) * step
        best_dist = float("inf"); ce_ltp = pe_ltp = 0
        for item in records:
            s = item.get("strikePrice", 0)
            dist = abs(s - atm)
            if dist < best_dist:
                best_dist = dist
                ce_ltp = item.get("CE", {}).get("lastPrice", 0)
                pe_ltp = item.get("PE", {}).get("lastPrice", 0)
        return round(float(ce_ltp), 2), round(float(pe_ltp), 2), spot
    except:
        return None, None, None

def update_open_trade_prices():
    """Fetch fresh prices for every index that has an open trade."""
    now_str = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
    for idx in INDEX_CONFIG:
        tlog = st.session_state.get(sk(idx, "trade_log"), [])
        has_open = any(t.get("Status") == "OPEN" for t in tlog)
        if not has_open:
            continue
        ce_ltp, pe_ltp, _ = get_atm_prices(idx)
        if ce_ltp is None:
            continue
        changed = False
        for trade in tlog:
            if trade.get("Status") != "OPEN":
                continue
            lp     = ce_ltp if trade.get("Signal") == "BUY CE" else pe_ltp
            ep_t   = float(trade.get("Entry Price") or 0)
            qty_t  = int(trade.get("Qty") or 0)
            sl     = float(trade.get("Stop Loss") or 0)
            tgt    = float(trade.get("Target") or 0)
            trade["Live Price"] = lp
            if lp <= sl:
                trade.update({"Status": "CLOSED", "Result": "🔴 LOSS",
                              "Exit Price": lp, "Exit Time": now_str,
                              "Actual P&L ₹": round((lp - ep_t) * qty_t, 2)})
                st.session_state[sk(idx, "last_signal")] = "WAIT"
                send_telegram(f"🔴 *SL HIT — {idx} {trade.get('Signal')}*\n"
                              f"📍 Strike: `{trade.get('Strike')}` | Exit: `{lp}`\n"
                              f"💸 P&L: `₹{trade['Actual P&L ₹']:,.0f}` | Time: `{now_str}`")
                changed = True
            elif lp >= tgt:
                trade.update({"Status": "CLOSED", "Result": "🟢 WIN",
                              "Exit Price": lp, "Exit Time": now_str,
                              "Actual P&L ₹": round((lp - ep_t) * qty_t, 2)})
                st.session_state[sk(idx, "last_signal")] = "WAIT"
                send_telegram(f"🟢 *TARGET HIT — {idx} {trade.get('Signal')}*\n"
                              f"📍 Strike: `{trade.get('Strike')}` | Exit: `{lp}`\n"
                              f"💸 P&L: `₹{trade['Actual P&L ₹']:,.0f}` | Time: `{now_str}`")
                changed = True
        if changed:
            save_log(idx)

# Run price updater on every refresh (before tabs)
update_open_trade_prices()

# ── MAIN RENDER FUNCTION ──
def render_index(idx):
    cfg   = INDEX_CONFIG[idx]
    lot   = cfg["lot"]; step = cfg["step"]; rng = cfg["rng"]
    tlog_key = sk(idx,"trade_log")

    data = get_data(idx)
    if data is None:
        st.error(f"❌ {idx} data unavailable. Retrying..."); return

    records = data["records"]["data"]
    spot    = data["records"]["underlyingValue"]
    atm     = round(spot/step)*step

    rows=[]
    for item in records:
        s=item.get("strikePrice",0)
        if abs(s-atm)<=rng:
            ce=item.get("CE",{}); pe=item.get("PE",{})
            rows.append({"Strike":s,"CE LTP":ce.get("lastPrice",0),"CE OI":ce.get("openInterest",0),
                         "PE LTP":pe.get("lastPrice",0),"PE OI":pe.get("openInterest",0)})
    df=pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)
    if df.empty: st.warning(f"No {idx} data. Market may be closed."); return

    df["dist"]=(df["Strike"]-spot).abs()
    atm_actual=int(df.loc[df["dist"].idxmin(),"Strike"])
    atm_row=df[df["Strike"]==atm_actual].iloc[0]

    # ── OI Delta (compare with previous snapshot, use baseline for first run) ──
    prev=st.session_state[sk(idx,"prev_df")]
    baseline=st.session_state[sk(idx,"oi_baseline")]

    if prev is not None:
        m=pd.merge(df,prev,on="Strike",how="left",suffixes=("","_p"))
        df["CE OI Δ"]=(m["CE OI"]-m["CE OI_p"]).fillna(0)
        df["PE OI Δ"]=(m["PE OI"]-m["PE OI_p"]).fillna(0)
    elif baseline is not None:
        # Use baseline from session start
        m=pd.merge(df,baseline,on="Strike",how="left",suffixes=("","_b"))
        df["CE OI Δ"]=(m["CE OI"]-m["CE OI_b"]).fillna(0)
        df["PE OI Δ"]=(m["PE OI"]-m["PE OI_b"]).fillna(0)
    else:
        df["CE OI Δ"]=0; df["PE OI Δ"]=0
        # Save first snapshot as baseline
        st.session_state[sk(idx,"oi_baseline")]=df[["Strike","CE OI","PE OI"]].copy()

    st.session_state[sk(idx,"prev_df")]=df[["Strike","CE OI","PE OI"]].copy()

    tot_ce=df["CE OI"].sum(); tot_pe=df["PE OI"].sum()
    pcr=round(tot_pe/tot_ce,2) if tot_ce else 0
    bias="Bullish" if pcr>1.2 else ("Bearish" if pcr<0.8 else "Neutral")
    resistance=int(df.loc[df["CE OI"].idxmax(),"Strike"])
    support=int(df.loc[df["PE OI"].idxmax(),"Strike"])

    # Guard against empty delta columns
    ce_delta_idx = df["CE OI Δ"].idxmax() if df["CE OI Δ"].max() > 0 else df["CE OI"].idxmax()
    pe_delta_idx = df["PE OI Δ"].idxmax() if df["PE OI Δ"].max() > 0 else df["PE OI"].idxmax()
    ce_build=int(df.loc[ce_delta_idx,"Strike"])
    pe_build=int(df.loc[pe_delta_idx,"Strike"])
    total_ce_delta=df["CE OI Δ"].sum(); total_pe_delta=df["PE OI Δ"].sum()

    # ── FILTERS ──
    now_ist=datetime.datetime.now(IST); now_time=now_ist.time()
    in_window=datetime.time(9,15)<=now_time<=datetime.time(15,30)

    # OI activity: use ABSOLUTE total OI (not just delta) to determine market activity
    # Also flag as active if cumulative delta from session start shows meaningful movement
    oi_active = (tot_ce > 0 and tot_pe > 0)  # market has OI = active

    # OI momentum from session baseline (much lower threshold)
    oi_momentum_bullish = total_pe_delta > total_ce_delta  # more PE being added = bullish underlying
    oi_momentum_bearish = total_ce_delta > total_pe_delta  # more CE being added = bearish underlying

    ph=st.session_state[sk(idx,"pcr_history")]
    ph.append(pcr); ph=ph[-5:]
    st.session_state[sk(idx,"pcr_history")]=ph
    pcr_momentum="FLAT"
    if len(ph)>=3:
        if ph[-1]>ph[-3]+0.02: pcr_momentum="RISING"
        elif ph[-1]<ph[-3]-0.02: pcr_momentum="FALLING"

    sh=st.session_state[sk(idx,"spot_history")]
    sh.append(spot); sh=sh[-20:]
    st.session_state[sk(idx,"spot_history")]=sh
    vwap_proxy=round(sum(sh)/len(sh),2)
    spot_vs_vwap="ABOVE" if spot>vwap_proxy else "BELOW"

    # ── SIGNAL LOGIC (Fixed & Improved) ──
    # Primary logic: PCR + spot position relative to support/resistance + VWAP
    signal="WAIT"; confidence="LOW"; filter_reason=""

    if not in_window:
        filter_reason="⏰ Outside trading hours (9:15–3:30)"
    elif not oi_active:
        filter_reason="📉 No OI data — market closed?"
    else:
        # HIGH confidence: PCR + VWAP + OI momentum all align
        if (pcr > 1.2 and spot > support and spot_vs_vwap == "ABOVE"
                and pcr_momentum in ("RISING", "FLAT") and oi_momentum_bullish):
            signal="BUY CE"; confidence="HIGH"
        elif (pcr < 0.8 and spot < resistance and spot_vs_vwap == "BELOW"
                and pcr_momentum in ("FALLING", "FLAT") and oi_momentum_bearish):
            signal="BUY PE"; confidence="HIGH"

        # MEDIUM confidence: PCR + VWAP align (even if OI momentum not confirmed)
        elif pcr > 1.15 and spot > support and spot_vs_vwap == "ABOVE":
            signal="BUY CE"; confidence="MEDIUM"
        elif pcr < 0.85 and spot < resistance and spot_vs_vwap == "BELOW":
            signal="BUY PE"; confidence="MEDIUM"

        # LOW confidence: pure PCR signal
        elif pcr > 1.1 and spot > support:
            signal="BUY CE"; confidence="LOW"
        elif pcr < 0.9 and spot < resistance:
            signal="BUY PE"; confidence="LOW"
        elif bias == "Neutral":
            signal="⚠️ SIDEWAYS"; confidence="AVOID"

    trap="NONE"
    if spot>resistance and total_ce_delta>total_pe_delta: trap="🚨 BULL TRAP"
    elif spot<support and total_pe_delta>total_ce_delta:  trap="🚨 BEAR TRAP"

    # ── SIGNAL BUFFER (confirm signal across refreshes) ──
    buf=st.session_state[sk(idx,"signal_buffer")]
    buf.append(signal); buf=buf[-3:]
    st.session_state[sk(idx,"signal_buffer")]=buf

    # Confirm signal: needs 2 of last 3 refreshes to agree (≈20 seconds of confirmation)
    if buf.count("BUY CE")>=2:   final_signal="BUY CE";  final_conf="HIGH"
    elif buf.count("BUY PE")>=2: final_signal="BUY PE";  final_conf="HIGH"
    elif buf.count("BUY CE")>=1 and confidence in ("HIGH","MEDIUM"):
        final_signal="BUY CE"; final_conf="MEDIUM"
    elif buf.count("BUY PE")>=1 and confidence in ("HIGH","MEDIUM"):
        final_signal="BUY PE"; final_conf="MEDIUM"
    else:
        final_signal="WAIT"; final_conf="LOW"

    # Don't enter new trade if one is already open
    open_exists=any(t.get("Status")=="OPEN" for t in st.session_state[tlog_key])
    if open_exists and final_signal in ("BUY CE","BUY PE"):
        final_signal="WAIT"; final_conf="LOW"

    ce_price=round(float(atm_row["CE LTP"]),2)
    pe_price=round(float(atm_row["PE LTP"]),2)

    # ── CHECK SL/TARGET on open trades ──
    changed=False
    for trade in st.session_state[tlog_key]:
        if trade.get("Status")=="OPEN":
            lp=ce_price if trade.get("Signal")=="BUY CE" else pe_price
            sl=float(trade.get("Stop Loss") or 0)
            tgt=float(trade.get("Target") or 0)
            ep_t=float(trade.get("Entry Price") or 0)
            qty_t=int(trade.get("Qty") or 0)
            trade["Live Price"]=lp
            now_str=datetime.datetime.now(IST).strftime("%I:%M:%S %p")
            if lp<=sl:
                trade.update({"Status":"CLOSED","Result":"🔴 LOSS","Exit Price":lp,
                               "Exit Time":now_str,"Actual P&L ₹":round((lp-ep_t)*qty_t,2)})
                changed=True
                st.session_state[sk(idx,"last_signal")]="WAIT"  # allow re-entry after SL
                send_telegram(f"🔴 *SL HIT — {idx} {trade.get('Signal')}*\n"
                              f"📍 Strike: `{trade.get('Strike')}` | Exit: `{lp}`\n"
                              f"💸 P&L: `₹{trade['Actual P&L ₹']:,.0f}` | Time: `{now_str}`")
            elif lp>=tgt:
                trade.update({"Status":"CLOSED","Result":"🟢 WIN","Exit Price":lp,
                               "Exit Time":now_str,"Actual P&L ₹":round((lp-ep_t)*qty_t,2)})
                changed=True
                st.session_state[sk(idx,"last_signal")]="WAIT"  # allow re-entry after target
                send_telegram(f"🟢 *TARGET HIT — {idx} {trade.get('Signal')}*\n"
                              f"📍 Strike: `{trade.get('Strike')}` | Exit: `{lp}`\n"
                              f"💸 P&L: `₹{trade['Actual P&L ₹']:,.0f}` | Time: `{now_str}`")
    if changed: save_log(idx)

    # ── KPI ──
    st.markdown(f"""
<div class="kpi-grid">
  <div class="card"><div class="label">{idx} SPOT</div><div class="kpi">{round(spot,2)}</div></div>
  <div class="card"><div class="label">ATM</div><div class="kpi">{atm_actual}</div></div>
  <div class="card"><div class="label">PCR</div><div class="kpi">{pcr}</div></div>
  <div class="card"><div class="label">BIAS</div><div class="kpi">{bias}</div></div>
  <div class="card"><div class="label">SUPPORT</div><div class="kpi">{support}</div></div>
  <div class="card"><div class="label">RESISTANCE</div><div class="kpi">{resistance}</div></div>
</div>""", unsafe_allow_html=True)

    # ── FILTERS STATUS ──
    tw_c="#34D399" if in_window else "#F87171"
    oi_c="#34D399" if oi_active else "#F87171"
    vw_c="#34D399" if spot_vs_vwap=="ABOVE" else "#F87171"
    pm_c="#34D399" if pcr_momentum!="FLAT" else "#F59E0B"
    pcr_momentum_display = pcr_momentum
    st.markdown(f"""
<div class="filter-grid">
  <div class="card" style="padding:10px;"><div class="label">⏰ Time</div>
    <div style="color:{tw_c};font-weight:700;">{"✅ IN WINDOW" if in_window else "❌ CLOSED"}</div></div>
  <div class="card" style="padding:10px;"><div class="label">📊 OI Market</div>
    <div style="color:{oi_c};font-weight:700;">{"✅ ACTIVE" if oi_active else "❌ NO DATA"}</div></div>
  <div class="card" style="padding:10px;"><div class="label">📈 vs VWAP ({vwap_proxy})</div>
    <div style="color:{vw_c};font-weight:700;">{spot_vs_vwap}</div></div>
  <div class="card" style="padding:10px;"><div class="label">🔄 PCR Momentum</div>
    <div style="color:{pm_c};font-weight:700;">{pcr_momentum_display}</div></div>
  <div class="card" style="padding:10px;"><div class="label">📊 OI Flow</div>
    <div style="color:#F59E0B;font-weight:700;">CE Δ:{int(total_ce_delta)} PE Δ:{int(total_pe_delta)}</div></div>
</div>""", unsafe_allow_html=True)

    # ── TRAP / SIGNAL ──
    if trap!="NONE":
        st.markdown(f'<div class="trap-alert">{trap} DETECTED!</div>',unsafe_allow_html=True)
    cc="signal-green" if "CE" in final_signal else ("signal-red" if "PE" in final_signal else "signal-yellow")
    st.markdown(
        f'<div class="card {cc}"><h2>{final_signal}</h2><p>Confidence: {final_conf}</p>'
        f'<p style="font-size:11px;color:#9CA3AF;">{idx} Raw: {signal} ({confidence}) | PCR: {pcr} | Buffer: {", ".join(buf[-3:])}'
        f'{" | "+filter_reason if filter_reason else ""}</p></div>',
        unsafe_allow_html=True)

    # ── LOG SIGNAL ──
    if final_signal in ("BUY CE","BUY PE") and final_conf in ("HIGH","MEDIUM"):
        ep=ce_price if final_signal=="BUY CE" else pe_price
        lbl="CE LTP" if final_signal=="BUY CE" else "PE LTP"
        qty,sl_p,tgt_p,ml,tp=calc_trade(ep,lot)
        st.markdown(
            f'<div style="margin-top:8px;padding:10px;background:#1F2937;border-radius:10px;">'
            f'<strong>📌 {lbl} @ {atm_actual}:</strong> {ep} &nbsp;|&nbsp;'
            f'<strong>💰 SL:</strong> {sl_p} &nbsp;|&nbsp;<strong>🎯 Tgt:</strong> {tgt_p} &nbsp;|&nbsp;'
            f'<strong>📦 Qty:</strong> {qty} &nbsp;|&nbsp;<strong>🔴 MaxLoss:</strong> ₹{ml} &nbsp;|&nbsp;'
            f'<strong>🟢 TgtP&L:</strong> ₹{tp}</div><br>',unsafe_allow_html=True)

        if final_signal!=st.session_state[sk(idx,"last_signal")]:
            now=datetime.datetime.now(IST).strftime("%I:%M:%S %p")
            st.session_state[tlog_key].insert(0,{
                "Entry Time":now,"Exit Time":None,"Index":idx,"Signal":final_signal,
                "Spot":round(spot,2),"Strike":atm_actual,"Entry Price":ep,"Live Price":ep,
                "Exit Price":None,"Stop Loss":sl_p,"Target":tgt_p,"Qty":qty,
                "Max Loss ₹":ml,"Target P&L ₹":tp,"Actual P&L ₹":None,"Status":"OPEN","Result":"⏳ OPEN"})
            save_log(idx)
            st.session_state[sk(idx,"last_signal")]=final_signal
            emoji="🟢" if "CE" in final_signal else "🔴"
            send_telegram(f"{emoji} *V12 {idx} SIGNAL: {final_signal}*\n"
                          f"📍 Strike: `{atm_actual}` | Spot: `{round(spot,2)}`\n"
                          f"💰 Entry: `{ep}` | SL: `{sl_p}` | Target: `{tgt_p}`\n"
                          f"📦 Qty: `{qty}` | Max Loss: `₹{ml}` | Target P&L: `₹{tp}`\n"
                          f"⏰ Time: `{now}` | Conf: `{final_conf}`")

        if final_signal!=st.session_state[sk(idx,"last_played")]:
            st.markdown('<audio autoplay style="display:none"><source src="https://actions.google.com/sounds/v1/alarms/beep_short.ogg" type="audio/ogg"></audio>',unsafe_allow_html=True)
            st.session_state[sk(idx,"last_played")]=final_signal
        st.success(f"🚨 {idx} {final_conf} CONFIDENCE SIGNAL — {final_signal} CONFIRMED")
    else:
        # Reset last_signal when signal disappears so next signal can be logged fresh
        if final_signal == "WAIT" and st.session_state[sk(idx,"last_signal")] not in ("WAIT",):
            # Only reset if no open trade exists (avoid resetting mid-trade)
            if not open_exists:
                st.session_state[sk(idx,"last_signal")] = "WAIT"
                st.session_state[sk(idx,"last_played")] = "WAIT"

    # ── TRACKER ──
    log_df=pd.DataFrame(st.session_state[tlog_key]) if st.session_state[tlog_key] else pd.DataFrame(columns=LOG_COLS)
    closed=log_df[log_df["Status"]=="CLOSED"] if not log_df.empty else pd.DataFrame()
    rpnl=closed["Actual P&L ₹"].apply(pd.to_numeric,errors="coerce").sum() if not closed.empty else 0
    rc=CAPITAL+rpnl; prog=max(0.0,min(1.0,rpnl/DAILY_TGT)); pc="pnl-green" if rpnl>=0 else "pnl-red"

    hdr,rcol,tcol=st.columns([4,1,1])
    with hdr: st.subheader(f"💼 {idx} Tracker")
    with rcol:
        st.write("")
        if st.button("🔄 Reset",key=f"reset_{idx}",use_container_width=True):
            st.session_state[tlog_key]=[]; st.session_state[sk(idx,"last_signal")]="WAIT"
            st.session_state[sk(idx,"last_played")]="WAIT"; st.session_state[sk(idx,"signal_buffer")]=[]
            st.session_state[sk(idx,"oi_baseline")]=None; st.session_state[sk(idx,"prev_df")]=None
            f=f"trade_log_{idx}_{datetime.datetime.now().strftime('%Y-%m-%d')}.csv"
            if os.path.exists(f): os.remove(f)
            st.rerun()
    with tcol:
        st.write("")
        if st.button("📨 Test",key=f"test_{idx}",use_container_width=True):
            now_t=datetime.datetime.now(IST).strftime("%I:%M:%S %p")
            send_telegram(f"🧪 *V12 {idx} TEST ALERT*\n🟢 SIGNAL: BUY CE\n"
                          f"📍 Strike: `{atm_actual}` | Spot: `{round(spot,2)}`\n⏰ Time: `{now_t}` ← TEST")
            st.success("📨 Test sent!")

    st.markdown(f"""
<div class="tracker-grid">
  <div class="card"><div class="label">Capital</div><div class="kpi">₹{CAPITAL:,}</div></div>
  <div class="card"><div class="label">Closed</div><div class="kpi">{len(closed)}</div></div>
  <div class="card"><div class="label">Realized P&L</div><div class="kpi {pc}">₹{rpnl:,.0f}</div></div>
  <div class="card"><div class="label">Running Cap</div><div class="kpi">₹{rc:,.0f}</div></div>
  <div class="card"><div class="label">Daily Progress</div><div class="kpi">{round(prog*100)}%</div></div>
</div>""",unsafe_allow_html=True)
    st.progress(prog,text=f"{idx}: ₹{rpnl:,.0f} / ₹{DAILY_TGT:,} daily target")

    # ── OPTION CHAIN ──
    disp=df.drop(columns=["dist"],errors="ignore")
    def hl(v):
        if isinstance(v,(int,float)):
            if v>0: return "background-color:#064E3B;color:white"
            if v<0: return "background-color:#7F1D1D;color:white"
        return ""
    with st.expander(f"📊 {idx} Option Chain & Charts"):
        st.dataframe(disp.style.map(hl,subset=["CE OI Δ","PE OI Δ"]),use_container_width=True)
        st.plotly_chart(px.bar(disp,x="Strike",y=["CE OI","PE OI"],barmode="group",
            color_discrete_map={"CE OI":"#34D399","PE OI":"#F87171"}),use_container_width=True)
        st.plotly_chart(px.bar(disp,x="Strike",y=["CE OI Δ","PE OI Δ"],barmode="group",
            color_discrete_map={"CE OI Δ":"#6EE7B7","PE OI Δ":"#FCA5A5"}),use_container_width=True)

    # ── POSITIONS ──
    with st.expander(f"📜 {idx} Trade Positions"):
        t1,t2=st.tabs(["🟢 Open","📋 History"])
        with t1:
            opens=[t for t in st.session_state[tlog_key] if t.get("Status")=="OPEN"]
            if opens:
                ot=opens[0]; ev=float(ot.get("Entry Price") or 0); lv=float(ot.get("Live Price") or ev)
                qv=int(ot.get("Qty") or 0); upl=round((lv-ev)*qv,2)
                uc="#34D399" if upl>=0 else "#F87171"; sc="#34D399" if "CE" in str(ot.get("Signal")) else "#F87171"
                st.markdown(f"""<div class="card" style="border-left:4px solid {sc};">
  <div style="display:flex;gap:20px;flex-wrap:wrap;">
    <div><div class="label">Signal</div><div class="kpi" style="color:{sc};">{ot.get('Signal')}</div></div>
    <div><div class="label">Strike</div><div class="kpi">{ot.get('Strike')}</div></div>
    <div><div class="label">Entry</div><div class="kpi">₹{ev}</div></div>
    <div><div class="label">Live</div><div class="kpi">₹{lv}</div></div>
    <div><div class="label">SL</div><div class="kpi pnl-red">₹{ot.get('Stop Loss')}</div></div>
    <div><div class="label">Target</div><div class="kpi pnl-green">₹{ot.get('Target')}</div></div>
    <div><div class="label">Qty</div><div class="kpi">{qv}</div></div>
    <div><div class="label">Unrealized P&L</div><div class="kpi" style="color:{uc};">₹{upl:,.0f}</div></div>
  </div></div>""",unsafe_allow_html=True)
            else: st.info("No open position. Waiting for signal...")
        with t2:
            if st.session_state[tlog_key]:
                cols=["Entry Time","Exit Time","Signal","Strike","Entry Price","Exit Price","Qty","Actual P&L ₹","Status","Result"]
                hdf=pd.DataFrame(st.session_state[tlog_key])
                for c in cols:
                    if c not in hdf.columns: hdf[c]=None
                def cp(v):
                    try: f=float(v); return "color:#34D399;font-weight:700" if f>=0 else "color:#F87171;font-weight:700"
                    except: return ""
                st.dataframe(hdf[cols].style.map(cp,subset=["Actual P&L ₹"]),use_container_width=True)
                pnl_s=hdf["Actual P&L ₹"].apply(pd.to_numeric,errors="coerce")
                ca,cb,cc2=st.columns(3)
                ca.metric("Trades",len(hdf)); cb.metric("Win/Loss",f"{(pnl_s>0).sum()}/{(pnl_s<=0).sum()}")
                cc2.metric("Net P&L",f"₹{pnl_s.sum():,.0f}",delta=f"{pnl_s.sum():+.0f}")
            else: st.info("Waiting for first signal...")

# ── TABS ──
tab0, tab1, tab2, tab3 = st.tabs(["🟢 Open Trades", "📈 NIFTY", "🏦 BANKNIFTY", "💹 FINNIFTY"])

# Each fragment runs silently every 3 sec in the background — no page flicker

@st.fragment(run_every=3)
def show_open_trades():
    update_open_trade_prices()
    st.subheader("🟢 All Open Trades")
    all_open = []
    for idx in INDEX_CONFIG:
        tlog = st.session_state.get(sk(idx, "trade_log"), [])
        for t in tlog:
            if t.get("Status") == "OPEN":
                all_open.append(t)

    if not all_open:
        st.markdown("""
<div style="text-align:center;padding:60px 20px;">
  <div style="font-size:48px;">📭</div>
  <div style="color:#9CA3AF;font-size:18px;margin-top:12px;">No open trades right now</div>
  <div style="color:#6B7280;font-size:13px;margin-top:6px;">Waiting for a signal...</div>
</div>""", unsafe_allow_html=True)
    else:
        total_trades = len(all_open)
        indices_active = list({t.get("Index","") for t in all_open})
        st.markdown(f"""
<div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap;">
  <div class="card" style="padding:10px 18px;min-width:130px;">
    <div class="label">Open Trades</div>
    <div class="kpi" style="color:#34D399;">{total_trades}</div>
  </div>
  <div class="card" style="padding:10px 18px;min-width:130px;">
    <div class="label">Active Indices</div>
    <div class="kpi">{" · ".join(indices_active)}</div>
  </div>
</div>""", unsafe_allow_html=True)

        for t in all_open:
            idx   = t.get("Index", "")
            sig   = t.get("Signal", "")
            ev    = float(t.get("Entry Price") or 0)
            lv    = float(t.get("Live Price") or ev)
            sl    = t.get("Stop Loss", "")
            tgt   = t.get("Target", "")
            qty   = int(t.get("Qty") or 0)
            strk  = t.get("Strike", "")
            spot  = t.get("Spot", "")
            etime = t.get("Entry Time", "")
            upl   = round((lv - ev) * qty, 2)
            ml    = t.get("Max Loss ₹", "")
            tp    = t.get("Target P&L ₹", "")
            sc    = "#34D399" if "CE" in str(sig) else "#F87171"
            uc    = "#34D399" if upl >= 0 else "#F87171"
            upl_arrow = "▲" if upl >= 0 else "▼"
            idx_color = "#6366F1" if idx == "NIFTY" else ("#F59E0B" if idx == "BANKNIFTY" else "#22D3EE")
            st.markdown(f"""
<div class="card" style="border-left:5px solid {sc};margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
    <div style="display:flex;align-items:center;gap:10px;">
      <span style="background:{idx_color};color:white;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700;">{idx}</span>
      <span style="color:{sc};font-size:20px;font-weight:800;">{sig}</span>
      <span style="color:#9CA3AF;font-size:12px;">Strike: <b style="color:white;">{strk}</b></span>
      <span style="color:#9CA3AF;font-size:12px;">Spot: <b style="color:white;">{spot}</b></span>
    </div>
    <div style="color:{uc};font-size:22px;font-weight:800;">{upl_arrow} ₹{abs(upl):,.0f}</div>
  </div>
  <div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:10px;">
    <div><div class="label">Entry Price</div><div style="color:white;font-weight:700;">₹{ev}</div></div>
    <div><div class="label">Live Price</div><div style="color:white;font-weight:700;">₹{lv}</div></div>
    <div><div class="label">Stop Loss</div><div style="color:#F87171;font-weight:700;">₹{sl}</div></div>
    <div><div class="label">Target</div><div style="color:#34D399;font-weight:700;">₹{tgt}</div></div>
    <div><div class="label">Qty</div><div style="color:white;font-weight:700;">{qty}</div></div>
    <div><div class="label">Max Loss</div><div style="color:#F87171;font-weight:700;">₹{ml}</div></div>
    <div><div class="label">Target P&L</div><div style="color:#34D399;font-weight:700;">₹{tp}</div></div>
    <div><div class="label">Entry Time</div><div style="color:#9CA3AF;font-weight:700;">{etime}</div></div>
  </div>
</div>""", unsafe_allow_html=True)

@st.fragment(run_every=3)
def show_nifty(): render_index("NIFTY")

@st.fragment(run_every=3)
def show_banknifty(): render_index("BANKNIFTY")

@st.fragment(run_every=3)
def show_finnifty(): render_index("FINNIFTY")

with tab0: show_open_trades()
with tab1: show_nifty()
with tab2: show_banknifty()
with tab3: show_finnifty()
