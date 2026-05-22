"""
V12 PRO MAX — All CSS styles in one place.
"""


def get_styles():
    """Return the full <style> block for the dashboard."""
    return """
<style>
*{box-sizing:border-box;}

/* ── Cards ── */
.card{padding:12px;border-radius:12px;background:#111827;color:white;
      box-shadow:0 4px 14px rgba(0,0,0,.3);margin-bottom:8px;
      transition: transform 0.15s ease, box-shadow 0.15s ease;}
.card:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(0,0,0,.4);}

/* ── KPI ── */
.kpi{font-size:20px;font-weight:700;word-break:break-word;}
.label{color:#9CA3AF;font-size:11px;text-transform:uppercase;letter-spacing:.05em;}

/* ── Signal Cards ── */
.signal-green{background:linear-gradient(135deg,#064E3B,#065F46);border-left:4px solid #34D399;}
.signal-red{background:linear-gradient(135deg,#7F1D1D,#991B1B);border-left:4px solid #F87171;}
.signal-yellow{background:linear-gradient(135deg,#78350F,#92400E);border-left:4px solid #F59E0B;}

/* ── Trap Alert ── */
.trap-alert{background:linear-gradient(135deg,#DC2626,#B91C1C);color:white;font-weight:bold;
            padding:12px;border-radius:8px;text-align:center;margin-bottom:12px;font-size:13px;
            animation: pulse-trap 2s ease-in-out infinite;}
@keyframes pulse-trap{0%,100%{opacity:1;}50%{opacity:0.85;}}

/* ── P&L Colors ── */
.pnl-green{color:#34D399;font-weight:700;}
.pnl-red{color:#F87171;font-weight:700;}

/* ── Grids ── */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;margin-bottom:8px;}
.filter-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-bottom:8px;}
.tracker-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-bottom:8px;}
.analytics-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:12px;}

/* ── Confidence Score Bar ── */
.conf-bar-outer{width:100%;height:8px;background:#1F2937;border-radius:4px;overflow:hidden;margin-top:4px;}
.conf-bar-inner{height:100%;border-radius:4px;transition:width 0.5s ease;}
.conf-bar-high{background:linear-gradient(90deg,#059669,#34D399);}
.conf-bar-medium{background:linear-gradient(90deg,#D97706,#F59E0B);}
.conf-bar-low{background:linear-gradient(90deg,#DC2626,#F87171);}

/* ── Cooldown / Warning Badges ── */
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;}
.badge-cooldown{background:#7C3AED;color:white;}
.badge-warning{background:#D97706;color:white;}
.badge-ok{background:#059669;color:white;}

/* ── Sideways Indicator ── */
.sideways-indicator{background:linear-gradient(135deg,#374151,#4B5563);
                    padding:10px;border-radius:8px;text-align:center;margin-bottom:8px;
                    border:1px dashed #6B7280;}

/* ── Risk Overlay ── */
.risk-card{background:linear-gradient(135deg,#1E1B4B,#312E81);padding:12px;border-radius:12px;
           border-left:4px solid #818CF8;margin-bottom:8px;}

/* ── Hide Streamlit noise ── */
[data-testid="stStatusWidget"] {visibility:hidden !important;}
div[data-stale="true"] {opacity:1 !important;}
.stSpinner {display:none !important;}

/* ── Trailing Stop Indicator ── */
.trailing-active{animation: trail-pulse 1.5s ease-in-out infinite;}
@keyframes trail-pulse{0%,100%{box-shadow:0 0 0 0 rgba(52,211,153,0.4);}50%{box-shadow:0 0 0 8px rgba(52,211,153,0);}}

/* ── Mobile Responsive ── */
@media(max-width:640px){
  .kpi{font-size:16px;}
  .kpi-grid,.filter-grid,.tracker-grid,.analytics-grid{grid-template-columns:repeat(2,1fr);}
  .card{padding:8px;}
  [data-testid="stDataFrame"]{font-size:11px;}
}
</style>
"""
