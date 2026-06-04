"""
V12 PRO MAX — All CSS styles in one place.
"""


def get_styles():
    """Return the full <style> block for the dashboard."""
    return """
<style>
*{box-sizing:border-box;}

/* ── Base App Styles ── */
.stApp {
    background-color: #0B0F19; /* Deep dark background */
}

/* ── Cards (Glassmorphism) ── */
.card{
    padding:16px;
    border-radius:16px;
    background: rgba(17, 24, 39, 0.6);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color:white;
    box-shadow:0 8px 32px 0 rgba(0, 0, 0, 0.37);
    margin-bottom:12px;
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.card:hover{
    transform:translateY(-2px);
    box-shadow:0 12px 40px 0 rgba(0, 0, 0, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.15);
}

/* ── KPI ── */
.kpi{
    font-size:24px;
    font-weight:800;
    word-break:break-word;
    background: linear-gradient(90deg, #E2E8F0, #94A3B8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.label{
    color:#9CA3AF;
    font-size:12px;
    text-transform:uppercase;
    letter-spacing:0.1em;
    font-weight: 600;
    margin-bottom: 4px;
}

/* ── Signal Cards ── */
.signal-green{
    background: linear-gradient(135deg, rgba(6, 78, 59, 0.8), rgba(6, 95, 70, 0.9));
    border-left: 5px solid #10B981;
    box-shadow: 0 0 20px rgba(16, 185, 129, 0.2);
}
.signal-red{
    background: linear-gradient(135deg, rgba(127, 29, 29, 0.8), rgba(153, 27, 27, 0.9));
    border-left: 5px solid #EF4444;
    box-shadow: 0 0 20px rgba(239, 68, 68, 0.2);
}
.signal-yellow{
    background: linear-gradient(135deg, rgba(120, 53, 15, 0.8), rgba(146, 64, 14, 0.9));
    border-left: 5px solid #F59E0B;
    box-shadow: 0 0 20px rgba(245, 158, 11, 0.2);
}

/* ── Trap Alert ── */
.trap-alert{
    background: linear-gradient(135deg, rgba(220, 38, 38, 0.9), rgba(185, 28, 28, 0.9));
    color: white;
    font-weight: 800;
    padding: 16px;
    border-radius: 12px;
    text-align: center;
    margin-bottom: 16px;
    font-size: 15px;
    box-shadow: 0 0 15px rgba(220, 38, 38, 0.5);
    animation: pulse-trap 2s ease-in-out infinite;
}
@keyframes pulse-trap{
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.85; transform: scale(0.98); }
}

/* ── P&L Colors ── */
.pnl-green{color:#10B981;font-weight:800; text-shadow: 0 0 10px rgba(16,185,129,0.3);}
.pnl-red{color:#EF4444;font-weight:800; text-shadow: 0 0 10px rgba(239,68,68,0.3);}

/* ── Grids ── */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:12px;margin-bottom:12px;}
.filter-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:12px;margin-bottom:12px;}
.tracker-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:12px;margin-bottom:12px;}
.analytics-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:16px;}

/* ── Confidence Score Bar ── */
.conf-bar-outer{
    width: 100%;
    height: 10px;
    background: rgba(31, 41, 55, 0.6);
    border-radius: 5px;
    overflow: hidden;
    margin-top: 6px;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);
}
.conf-bar-inner{
    height: 100%;
    border-radius: 5px;
    transition: width 0.8s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.conf-bar-high{background:linear-gradient(90deg,#059669,#10B981); box-shadow: 0 0 10px #10B981;}
.conf-bar-medium{background:linear-gradient(90deg,#D97706,#F59E0B); box-shadow: 0 0 10px #F59E0B;}
.conf-bar-low{background:linear-gradient(90deg,#DC2626,#EF4444); box-shadow: 0 0 10px #EF4444;}

/* ── Cooldown / Warning Badges ── */
.badge{
    display:inline-block;
    padding:4px 12px;
    border-radius:24px;
    font-size:11px;
    font-weight:800;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
.badge-cooldown{background: linear-gradient(135deg, #7C3AED, #6D28D9);color:white;}
.badge-warning{background: linear-gradient(135deg, #D97706, #B45309);color:white;}
.badge-ok{background: linear-gradient(135deg, #059669, #047857);color:white;}

/* ── Sideways Indicator ── */
.sideways-indicator{
    background: rgba(55, 65, 81, 0.4);
    backdrop-filter: blur(8px);
    padding:12px;
    border-radius:12px;
    text-align:center;
    margin-bottom:12px;
    border:1px dashed rgba(156, 163, 175, 0.5);
    color: #E5E7EB;
    font-weight: 600;
}

/* ── Risk Overlay ── */
.risk-card{
    background: linear-gradient(135deg, rgba(30, 27, 75, 0.8), rgba(49, 46, 129, 0.9));
    backdrop-filter: blur(12px);
    padding:16px;
    border-radius:16px;
    border-left: 5px solid #818CF8;
    margin-bottom:12px;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
}

/* ── Hide Streamlit noise ── */
[data-testid="stStatusWidget"] {visibility:hidden !important;}
div[data-stale="true"] {opacity:1 !important;}
.stSpinner {display:none !important;}

/* ── Mobile Responsive ── */
@media(max-width:640px){
  .kpi{font-size:20px;}
  .kpi-grid,.filter-grid,.tracker-grid,.analytics-grid{grid-template-columns:repeat(2,1fr);}
  .card{padding:12px;}
  [data-testid="stDataFrame"]{font-size:12px;}
}
</style>
"""
