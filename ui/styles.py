"""
V12 PRO MAX — All CSS styles in one place.
"""

def get_styles():
    """Return the full <style> block for the dashboard."""
    return """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

* {
    box-sizing: border-box;
    font-family: 'Inter', sans-serif !important;
}

/* ── Base App Styles ── */
.stApp {
    background-color: #09090b; /* Deep zinc-950 */
    background-image: radial-gradient(circle at 50% -20%, rgba(30, 58, 138, 0.15), transparent 60%);
    color: #e4e4e7;
}

/* Hide Streamlit default UI elements for a cleaner look */
header[data-testid="stHeader"] { display: none; }
footer[data-testid="stFooter"] { display: none; }

/* ── Cards (Modern Glassmorphism) ── */
.card {
    padding: 18px 20px;
    border-radius: 16px;
    background: rgba(24, 24, 27, 0.65); /* zinc-900 with opacity */
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255, 255, 255, 0.06);
    box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.4);
    margin-bottom: 16px;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
}

.card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
    opacity: 0;
    transition: opacity 0.3s ease;
}

.card:hover {
    transform: translateY(-3px);
    box-shadow: 0 12px 30px -5px rgba(0, 0, 0, 0.6);
    border-color: rgba(255, 255, 255, 0.12);
}

.card:hover::before {
    opacity: 1;
}

/* ── KPI Typography ── */
.kpi {
    font-size: 26px;
    font-weight: 800;
    line-height: 1.2;
    word-break: break-word;
    background: linear-gradient(180deg, #ffffff, #a1a1aa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.02em;
}
.label {
    color: #a1a1aa;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    font-weight: 600;
    margin-bottom: 6px;
}

/* ── Signal Cards ── */
.signal-green {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.1), rgba(5, 150, 105, 0.2));
    border-left: 4px solid #10b981;
}
.signal-green .kpi, .signal-green h2 {
    background: linear-gradient(180deg, #34d399, #059669);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 4px;
    margin-top: 0;
}
.signal-red {
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.1), rgba(220, 38, 38, 0.2));
    border-left: 4px solid #ef4444;
}
.signal-red .kpi, .signal-red h2 {
    background: linear-gradient(180deg, #f87171, #dc2626);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 4px;
    margin-top: 0;
}
.signal-yellow {
    background: linear-gradient(135deg, rgba(245, 158, 11, 0.1), rgba(217, 119, 6, 0.2));
    border-left: 4px solid #f59e0b;
}
.signal-yellow h2 {
    margin-bottom: 4px;
    margin-top: 0;
}

/* ── Trap Alert ── */
.trap-alert {
    background: linear-gradient(135deg, #ef4444, #991b1b);
    color: white;
    font-weight: 800;
    padding: 16px 20px;
    border-radius: 12px;
    text-align: center;
    margin-bottom: 20px;
    font-size: 14px;
    letter-spacing: 0.05em;
    box-shadow: 0 0 25px rgba(239, 68, 68, 0.4);
    animation: pulse-trap 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
}
@keyframes pulse-trap {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; box-shadow: 0 0 10px rgba(239, 68, 68, 0.2); }
}

/* ── P&L Colors ── */
.pnl-green { color: #10b981 !important; -webkit-text-fill-color: #10b981; }
.pnl-red { color: #ef4444 !important; -webkit-text-fill-color: #ef4444; }

/* ── Grids ── */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 16px; margin-bottom: 16px; }
.filter-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; margin-bottom: 16px; }
.tracker-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; margin-bottom: 16px; }
.analytics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 20px; }

/* ── Confidence Score Bar ── */
.conf-bar-outer {
    width: 100%;
    height: 8px;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    overflow: hidden;
    margin-top: 10px;
    margin-bottom: 4px;
}
.conf-bar-inner {
    height: 100%;
    border-radius: 8px;
    transition: width 1s cubic-bezier(0.25, 1, 0.5, 1);
}
.conf-bar-high { background: linear-gradient(90deg, #10b981, #34d399); box-shadow: 0 0 12px rgba(16, 185, 129, 0.6); }
.conf-bar-medium { background: linear-gradient(90deg, #f59e0b, #fbbf24); box-shadow: 0 0 12px rgba(245, 158, 11, 0.6); }
.conf-bar-low { background: linear-gradient(90deg, #ef4444, #f87171); box-shadow: 0 0 12px rgba(239, 68, 68, 0.6); }

/* ── Badges ── */
.badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.badge-cooldown { background: rgba(139, 92, 246, 0.2); color: #c4b5fd; border: 1px solid rgba(139, 92, 246, 0.3); }
.badge-warning { background: rgba(245, 158, 11, 0.2); color: #fcd34d; border: 1px solid rgba(245, 158, 11, 0.3); }
.badge-ok { background: rgba(16, 185, 129, 0.2); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.3); }

/* ── Sideways Indicator ── */
.sideways-indicator {
    background: rgba(39, 39, 42, 0.5);
    backdrop-filter: blur(10px);
    padding: 14px;
    border-radius: 12px;
    text-align: center;
    margin-bottom: 16px;
    border: 1px dashed rgba(161, 161, 170, 0.3);
    color: #d4d4d8;
    font-weight: 600;
    font-size: 14px;
}

/* ── Risk Overlay ── */
.risk-card {
    background: linear-gradient(135deg, rgba(30, 27, 75, 0.6), rgba(49, 46, 129, 0.7));
    backdrop-filter: blur(16px);
    padding: 18px 24px;
    border-radius: 16px;
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-left: 4px solid #6366f1;
    margin-bottom: 16px;
    display: flex;
    gap: 32px;
    flex-wrap: wrap;
}

/* ── Streamlit overrides ── */
div[data-stale="true"] { opacity: 1 !important; transition: none; }
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background-color: rgba(24, 24, 27, 0.6);
    padding: 6px;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.08);
}
.stTabs [data-baseweb="tab"] {
    background-color: transparent;
    border-radius: 8px;
    padding: 10px 16px;
    font-weight: 600;
    color: #a1a1aa;
    border: none !important;
}
.stTabs [aria-selected="true"] {
    background-color: rgba(255,255,255,0.12) !important;
    color: #fff !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.2);
}

/* ── Mobile Responsive ── */
@media(max-width:640px){
  .kpi { font-size: 20px; }
  .kpi-grid, .filter-grid, .tracker-grid, .analytics-grid { grid-template-columns: repeat(2, 1fr); }
  .card { padding: 14px; }
}
</style>
"""
