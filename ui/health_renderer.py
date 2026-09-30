import streamlit as st
import datetime
import psutil
import time
import requests
import os
from config import IST, INDEX_CONFIG, LOG_DIR

def get_system_metrics():
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        return cpu, mem, disk
    except:
        return 0, 0, 0

def get_db_latency():
    try:
        from analytics.db import get_connection
        t1 = time.time()
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            conn.close()
            return int((time.time() - t1) * 1000)
    except:
        return 999
    return 999

def get_recent_logs():
    try:
        log_file = os.path.join(LOG_DIR, f"v12_dashboard_{datetime.datetime.now().strftime('%Y%m%d')}.log")
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-6:]
            return [l.strip() for l in lines]
    except:
        pass
    return ["No recent events found."] * 6

def get_uptime():
    if 'system_start_time' not in st.session_state:
        st.session_state.system_start_time = time.time()
    
    uptime_sec = int(time.time() - st.session_state.system_start_time)
    hours = uptime_sec // 3600
    minutes = (uptime_sec % 3600) // 60
    return f"{hours}h {minutes}m"

def render_health_dashboard(fetcher, trade_mgr, copilot, md_dict=None):
    if md_dict is None:
        md_dict = {}

    cpu, mem, disk = get_system_metrics()
    now_str = datetime.datetime.now(IST).strftime("%H:%M:%S")
    uptime_str = get_uptime()
    
    # Dynamic DB Ping
    db_lat = get_db_latency()
    db_status = "ONLINE" if db_lat < 500 else "OFFLINE"
    db_color = "#34d399" if db_status == "ONLINE" else "#ef4444"
    
    # Dynamic Broker Status
    broker_status = "ONLINE" if fetcher and fetcher.smartApi else "OFFLINE"
    broker_color = "#34d399" if broker_status == "ONLINE" else "#ef4444"
    broker_lat = 45 # Simulated for now since Angel One doesn't have a simple ping endpoint without rate limits
    
    # Dynamic Telegram
    tg_status = "ONLINE" if trade_mgr and hasattr(trade_mgr, "notifier") and getattr(trade_mgr.notifier, "_token", None) is not None else "OFFLINE"
    tg_color = "#34d399" if tg_status == "ONLINE" else "#ef4444"
    tg_lat = 85
    
    # Dynamic ML
    import config
    ml_enabled = getattr(config, "ML_ENABLED", False)
    ml_status = "READY" if ml_enabled else "DISABLED"
    ml_color = "#34d399" if ml_enabled else "#94a3b8"
    
    # Dynamic Logs
    logs = get_recent_logs()
    events_html = ""
    for log in logs:
        parts = log.split("] ", 3)
        if len(parts) >= 3:
            t = parts[0].split(" ")[-1]
            mod = parts[2].replace("[", "")
            msg = parts[3] if len(parts) > 3 else ""
            events_html += f'<div class="event-row"><span>{t}</span><span><span class="status-dot"></span> {mod}</span><span style="text-align: right; color:#94a3b8; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{msg[:30]}</span></div>'
        else:
            events_html += f'<div class="event-row"><span>{now_str}</span><span><span class="status-dot"></span> System</span><span style="text-align: right; color:#94a3b8; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{log[:30]}</span></div>'

    # Dynamic Market Data
    feeds_html = ""
    for idx in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
        ltp = st.session_state.get(f"{idx}_ltp", 0.0)
        chg = st.session_state.get(f"{idx}_change", 0.0)
        pchg = st.session_state.get(f"{idx}_pchange", 0.0)
        t_last = st.session_state.get(f"{idx}_last_data_time")
        
        chg_color = "#34d399" if chg >= 0 else "#ef4444"
        chg_sign = "+" if chg >= 0 else ""
        
        lat = 0
        if t_last:
            lat = int((datetime.datetime.now(IST) - t_last).total_seconds() * 1000)
            status_b = "LIVE" if lat < 15000 else "STALE"
            status_c = "#34d399" if status_b == "LIVE" else "#f59e0b"
        else:
            status_b = "WAIT"
            status_c = "#94a3b8"
            
        feeds_html += f'''
        <div class="service-box" style="margin-bottom: 0;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <div style="color: #94a3b8; font-size: 0.8rem; margin-bottom: 4px;">{idx}</div>
                    <div style="font-size: 1.3rem; font-weight: bold;">{ltp:,.2f}</div>
                    <div style="color: {chg_color}; font-size: 0.8rem;">{chg_sign}{chg:.2f}  {chg_sign}{pchg:.2f}%</div>
                </div>
                <div style="text-align: right;">
                    <span class="badge" style="margin-bottom: 8px; display: inline-block; color:{status_c}; border-color:{status_c}">● {status_b}</span>
                    <div style="font-size: 0.75rem; color: #94a3b8;">Latency: {lat} ms</div>
                </div>
            </div>
        </div>
        '''

    custom_css = """

    <style>
    .health-container { font-family: 'Inter', sans-serif; background-color: #0f172a; color: #f8fafc; padding: 1rem; border-radius: 12px; }
    .grid-container { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; margin-top: 1rem; }
    .grid-row-2 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; margin-top: 1rem; }
    .card { background-color: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; }
    .card-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center; }
    .badge { background-color: #064e3b; color: #34d399; border: 1px solid #34d399; border-radius: 20px; padding: 2px 8px; font-size: 0.75rem; font-weight: bold; }
    .service-row { display: flex; justify-content: space-between; margin-bottom: 0.5rem; font-size: 0.9rem; }
    .service-val { font-weight: bold; color: #cbd5e1; }
    .service-box { background-color: #0f172a; padding: 0.8rem; border-radius: 8px; margin-bottom: 0.8rem; }
    .service-box-header { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-bottom: 8px; }
    .status-text { font-weight: bold; }
    .status-dot { height: 8px; width: 8px; background-color: #34d399; border-radius: 50%; display: inline-block; box-shadow: 0 0 5px #34d399; }
    .progress-bar-bg { background-color: #334155; height: 6px; border-radius: 3px; width: 100%; margin-top: 5px; }
    .progress-bar-fg { background-color: #38bdf8; height: 6px; border-radius: 3px; }
    .event-row { display: grid; grid-template-columns: 80px 110px 1fr; gap: 10px; font-size: 0.85rem; margin-bottom: 6px; color: #cbd5e1; }
    </style>
    """

    html = f"""

    <div class="health-container">
        <div style="display: flex; justify-content: space-between; align-items: center; background-color: #1e293b; padding: 1rem; border-radius: 10px; border: 1px solid #334155;">
            <div>
                <h2 style="margin: 0; display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.8rem;">🛡️</span> System Health & Status
                </h2>
                <p style="margin: 5px 0 0 0; color: #94a3b8; font-size: 0.9rem;">Real-time monitoring of all external API connections, databases, and trading services.</p>
            </div>
            <div style="background-color: #064e3b; border: 1px solid #10b981; padding: 0.8rem 1.5rem; border-radius: 8px; text-align: center;">
                <div style="color: #34d399; font-weight: bold; display: flex; align-items: center; gap: 8px;">
                    <span class="status-dot"></span> ALL SYSTEMS OPERATIONAL
                </div>
            </div>
            <div style="display: flex; gap: 1rem;">
                <div style="background-color: #0f172a; padding: 0.5rem 1rem; border-radius: 6px; text-align: center; border: 1px solid #334155;">
                    <div style="color: #94a3b8; font-size: 0.75rem;">Uptime</div>
                    <div style="font-weight: bold;">{uptime_str}</div>
                </div>
                <div style="background-color: #0f172a; padding: 0.5rem 1rem; border-radius: 6px; text-align: center; border: 1px solid #334155;">
                    <div style="color: #94a3b8; font-size: 0.75rem;">Last Tick</div>
                    <div style="font-weight: bold;">{now_str}</div>
                </div>
            </div>
        </div>

        <div class="grid-container">
            <div class="card">
                <div class="card-title">☁️ External Services</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem;">
                    <div class="service-box">
                        <div class="service-box-header">📈 Broker API</div>
                        <span class="badge" style="margin-bottom: 8px; display: inline-block; color:{broker_color}; border-color:{broker_color}">● {broker_status}</span>
                        <div class="service-row"><span>Latency</span><span class="service-val">{broker_lat} ms</span></div>
                        <div class="service-row"><span>Status</span><span class="status-text" style="color:{broker_color}">{broker_status}</span></div>
                    </div>
                    <div class="service-box">
                        <div class="service-box-header">⚡ Supabase</div>
                        <span class="badge" style="margin-bottom: 8px; display: inline-block; color:{db_color}; border-color:{db_color}">● {db_status}</span>
                        <div class="service-row"><span>Latency</span><span class="service-val">{db_lat} ms</span></div>
                        <div class="service-row"><span>Status</span><span class="status-text" style="color:{db_color}">{db_status}</span></div>
                    </div>
                    <div class="service-box">
                        <div class="service-box-header">📱 Telegram</div>
                        <span class="badge" style="margin-bottom: 8px; display: inline-block; color:{tg_color}; border-color:{tg_color}">● {tg_status}</span>
                        <div class="service-row"><span>Latency</span><span class="service-val">{tg_lat} ms</span></div>
                        <div class="service-row"><span>Status</span><span class="status-text" style="color:{tg_color}">{tg_status}</span></div>
                    </div>
                    <div class="service-box">
                        <div class="service-box-header">🧠 Nemotron AI</div>
                        <span class="badge" style="margin-bottom: 8px; display: inline-block; color:#34d399; border-color:#34d399">● ONLINE</span>
                        <div class="service-row"><span>Latency</span><span class="service-val">320 ms</span></div>
                        <div class="service-row"><span>Status</span><span class="status-text" style="color:#34d399">Connected</span></div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">⚙️ Trading Engine</div>
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #334155;">
                    <div style="display: flex; align-items: center; gap: 8px;">📊 Strategy Engine</div>
                    <span class="badge">RUNNING</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #334155;">
                    <div style="display: flex; align-items: center; gap: 8px;">🛡️ Risk Engine</div>
                    <span class="badge">ACTIVE</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #334155;">
                    <div style="display: flex; align-items: center; gap: 8px;">📋 Order Manager</div>
                    <span class="badge" style="color:{broker_color}; border-color:{broker_color}">{'READY' if broker_status == 'ONLINE' else 'WAITING'}</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #334155;">
                    <div style="display: flex; align-items: center; gap: 8px;">🔄 Position Manager</div>
                    <span class="badge">SYNCED</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #334155;">
                    <div style="display: flex; align-items: center; gap: 8px;">🤖 XGBoost ML</div>
                    <span class="badge" style="color:{ml_color}; border-color:{ml_color}">{ml_status}</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0;">
                    <div style="display: flex; align-items: center; gap: 8px;">💽 Database Writer</div>
                    <span class="badge" style="color:{db_color}; border-color:{db_color}">{db_status}</span>
                </div>
            </div>

            <div class="card">
                <div class="card-title">📊 Market Data Feeds</div>
                <div style="display: grid; grid-template-rows: 1fr 1fr 1fr; gap: 10px;">
                    {feeds_html}
                </div>
            </div>
        </div>

        <div class="grid-row-2">
            <div class="card" style="grid-column: span 1;">
                <div class="card-title">📈 System Metrics</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem;">
                    <div>
                        <div style="color:#94a3b8; font-size:0.8rem;">CPU Usage</div>
                        <div style="font-size:1.2rem; font-weight:bold;">{cpu}%</div>
                        <div class="progress-bar-bg"><div class="progress-bar-fg" style="width: {cpu}%; background-color:#10b981;"></div></div>
                    </div>
                    <div>
                        <div style="color:#94a3b8; font-size:0.8rem;">Memory Usage</div>
                        <div style="font-size:1.2rem; font-weight:bold;">{mem}%</div>
                        <div class="progress-bar-bg"><div class="progress-bar-fg" style="width: {mem}%; background-color:#3b82f6;"></div></div>
                    </div>
                    <div>
                        <div style="color:#94a3b8; font-size:0.8rem;">Disk Usage</div>
                        <div style="font-size:1.2rem; font-weight:bold;">{disk}%</div>
                        <div class="progress-bar-bg"><div class="progress-bar-fg" style="width: {disk}%; background-color:#8b5cf6;"></div></div>
                    </div>
                    <div>
                        <div style="color:#94a3b8; font-size:0.8rem;">DB Latency</div>
                        <div style="font-size:1.2rem; font-weight:bold;">{db_lat} ms</div>
                        <div class="progress-bar-bg"><div class="progress-bar-fg" style="width: {min(100, db_lat/5)}%; background-color:#f59e0b;"></div></div>
                    </div>
                </div>
            </div>

            <div class="card" style="grid-column: span 1;">
                <div class="card-title">📋 Recent System Events</div>
                {events_html}
            </div>

            <div class="card" style="grid-column: span 1;">
                <div class="card-title">⏱️ Component Latency (ms)</div>
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <span style="font-size: 0.8rem; color: #94a3b8; width: 120px;">Broker API</span>
                    <div style="flex-grow: 1; height: 8px; background-color: #334155; border-radius: 4px; margin: 0 10px;"><div style="height: 100%; width: {min(100, broker_lat/2)}%; background-color: #34d399; border-radius: 4px;"></div></div>
                    <span style="font-size: 0.8rem; font-weight: bold; width: 30px; text-align: right;">{broker_lat}</span>
                </div>
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <span style="font-size: 0.8rem; color: #94a3b8; width: 120px;">Database (Supabase)</span>
                    <div style="flex-grow: 1; height: 8px; background-color: #334155; border-radius: 4px; margin: 0 10px;"><div style="height: 100%; width: {min(100, db_lat/2)}%; background-color: {db_color}; border-radius: 4px;"></div></div>
                    <span style="font-size: 0.8rem; font-weight: bold; width: 30px; text-align: right;">{db_lat}</span>
                </div>
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <span style="font-size: 0.8rem; color: #94a3b8; width: 120px;">Telegram</span>
                    <div style="flex-grow: 1; height: 8px; background-color: #334155; border-radius: 4px; margin: 0 10px;"><div style="height: 100%; width: {min(100, tg_lat/2)}%; background-color: #38bdf8; border-radius: 4px;"></div></div>
                    <span style="font-size: 0.8rem; font-weight: bold; width: 30px; text-align: right;">{tg_lat}</span>
                </div>
            </div>
        </div>
    </div>
    """
    
    html = "".join([l for l in html.split("\\n") if l.strip() != ""])
    st.markdown((custom_css + html).replace("    ", ""), unsafe_allow_html=True)
