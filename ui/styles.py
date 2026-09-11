"""
V12 PRO MAX — UI Styles & Terminal Design System
Design Principles:
- Background: #06070D (very dark navy / deep space black)
- Cards: #0D0F18, #111421
- Borders: Subtle dark blue/gray (rgba(255, 255, 255, 0.07) / #1E2235)
- Primary accent: Purple/electric indigo (#4F46E5 / #6366F1)
- Profit / Live: Emerald (#00E5A0)
- Loss: Rose (#FF4D6D)
- Neutral: Amber (#F59E0B)
- Typography: Space Grotesk for numerics & hero metrics; Inter for body & receded labels.
- Layout: True mobile-first responsive grid. Touch targets >= 44px.
"""

def get_styles():
    return """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

/* ── Reset & Global Box Sizing ── */
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  /* Surface palette */
  --bg-0:          #06070D;  /* Very dark navy base */
  --bg-1:          #0D0F18;  /* Primary card surface */
  --bg-2:          #111421;  /* Inset card / secondary surface */
  --bg-3:          #181B2C;  /* Active hover surface */
  
  /* Borders */
  --border:        rgba(255, 255, 255, 0.07);
  --border-hi:     rgba(255, 255, 255, 0.14);
  --border-blue:   #1E2235;
  
  /* Typography colors */
  --text-0:        #FFFFFF;  /* Primary white */
  --text-1:        #94A3B8;  /* Secondary blue-gray */
  --text-2:        #525270;  /* Receded muted labels */
  
  /* Accents */
  --indigo:        #4F46E5;  /* Electric indigo anchor */
  --purple:        #6366F1;  /* Primary terminal purple */
  --indigo-dim:    rgba(79, 70, 229, 0.12);
  --indigo-hi:     rgba(79, 70, 229, 0.28);
  
  /* State Colors */
  --ce:            #00E5A0;  /* Emerald for CE / Bullish / Profit */
  --ce-dim:        rgba(0, 229, 160, 0.10);
  --ce-border:     rgba(0, 229, 160, 0.25);
  
  --pe:            #FF4D6D;  /* Rose for PE / Bearish / Loss */
  --pe-dim:        rgba(255, 77, 109, 0.10);
  --pe-border:     rgba(255, 77, 109, 0.25);

  --amber:         #F59E0B;  /* Amber for Neutral / Wait */
  --amber-dim:     rgba(245, 158, 11, 0.10);
  --amber-border:  rgba(245, 158, 11, 0.25);

  /* Touch & Geometry */
  --r:             8px;
  --r-sm:          6px;
  --touch-min:     44px;
}

body, .stApp {
  font-family: 'Inter', -apple-system, sans-serif;
  background-color: var(--bg-0) !important;
  color: var(--text-0);
  -webkit-font-smoothing: antialiased;
}

/* ── Hide Streamlit chrome ── */
header[data-testid="stHeader"],
footer[data-testid="stFooter"],
.stDeployButton,
section[data-testid="stSidebar"] {
  display: none !important;
}

/* ── Main Container Padding ── */
.block-container {
  padding-top: 0.6rem !important;
  padding-left: 0.85rem !important;
  padding-right: 0.85rem !important;
  padding-bottom: 70px !important;
  max-width: 100% !important;
}

/* ── Typography & Hierarchy: Numbers are the HERO ── */
.num, .kpi, .kpi-lg, .kpi-sm, .signal-hero, .trade-val {
  font-family: 'Space Grotesk', -apple-system, sans-serif !important;
  font-feature-settings: 'tnum' on, 'lnum' on;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.15;
  color: var(--text-0);
}

/* Labels RECEDE: small, muted uppercase */
.label {
  font-family: 'Inter', sans-serif !important;
  font-size: 10px !important;
  font-weight: 600 !important;
  color: var(--text-2) !important;
  text-transform: uppercase !important;
  letter-spacing: 0.12em !important;
  margin-bottom: 4px;
  white-space: nowrap;
}

/* KPI size hierarchy */
.kpi      { font-size: 24px; }
.kpi-lg   { font-size: 32px; }
.kpi-sm   { font-size: 17px; }

/* State Text Colors */
.c-ce, .pnl-positive { color: var(--ce) !important; -webkit-text-fill-color: var(--ce) !important; }
.c-pe, .pnl-negative { color: var(--pe) !important; -webkit-text-fill-color: var(--pe) !important; }
.c-amber             { color: var(--amber) !important; -webkit-text-fill-color: var(--amber) !important; }
.c-indigo            { color: var(--indigo) !important; -webkit-text-fill-color: var(--indigo) !important; }
.c-white             { color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }
.c-muted             { color: var(--text-1) !important; }
.c-dim               { color: var(--text-2) !important; }

/* ── Semantic Card Architecture ── */
.card, .kpi-card, .trade-card {
  background: var(--bg-1);
  border: 1px solid var(--border-blue);
  border-radius: var(--r);
  padding: 12px 14px;
  margin-bottom: 10px;
  position: relative;
  transition: border-color 0.15s ease;
}
.card:hover, .kpi-card:hover, .trade-card:hover {
  border-color: var(--border-hi);
}
.card-inset {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 10px 12px;
}

/* ── App Header ── */
.app-header {
  padding: 6px 0 12px 0;
  border-bottom: 1px solid var(--border-blue);
  margin-bottom: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.app-header-left h1 {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 26px;
  font-weight: 800;
  color: #ffffff;
  margin: 0;
  letter-spacing: -0.03em;
  display: flex;
  align-items: center;
  gap: 8px;
}
.app-header-left p {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-2);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin-top: 2px;
}

/* ── Market Ticker Strip ── */
.market-ticker {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding: 6px 10px;
  background: var(--bg-1);
  border: 1px solid var(--border-blue);
  border-radius: var(--r-sm);
  margin-bottom: 12px;
  align-items: center;
  white-space: nowrap;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.market-ticker::-webkit-scrollbar { display: none; }
.ticker-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-right: 1px solid var(--border);
}
.ticker-item:last-child {
  border-right: none;
}
.ticker-symbol {
  color: var(--text-2);
  letter-spacing: 0.05em;
}
.ticker-val {
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 700;
  color: #ffffff;
}

/* ── Status Pills (Market Open / Closed / Live) ── */
.pill, .status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 99px;
  font-family: 'Space Grotesk', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  white-space: nowrap;
}
.pill::before, .status-badge::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.pill-on {
  background: rgba(0, 229, 160, 0.12);
  color: var(--ce);
  border: 1px solid var(--ce-border);
}
.pill-off {
  background: rgba(255, 77, 109, 0.12);
  color: var(--pe);
  border: 1px solid var(--pe-border);
}
.pill-live {
  background: rgba(79, 70, 229, 0.16);
  color: #818cf8;
  border: 1px solid var(--indigo-hi);
}

/* ── Badges ── */
.badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  white-space: nowrap;
}
.badge-ce      { background: var(--ce-dim); color: var(--ce); border: 1px solid var(--ce-border); }
.badge-pe      { background: var(--pe-dim); color: var(--pe); border: 1px solid var(--pe-border); }
.badge-amber, .badge-warning { background: var(--amber-dim); color: var(--amber); border: 1px solid var(--amber-border); }
.badge-indigo  { background: var(--indigo-dim); color: #a5b4fc; border: 1px solid var(--indigo-hi); }

/* ── Trade Card Components ── */
.trade-card {
  border-left: 4px solid var(--border-hi);
  padding: 16px 18px;
  margin-bottom: 8px;
}
.trade-card.ce-card {
  border-left-color: var(--ce);
}
.trade-card.pe-card {
  border-left-color: var(--pe);
}
.trade-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 8px;
}
.trade-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(75px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}
.trade-strip {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--text-1);
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--bg-2);
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
}

/* ── Progress Bar ── */
.progress-bar, .conf-bar-outer {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 99px;
  overflow: hidden;
  margin-top: 4px;
}
.progress-fill, .conf-bar-inner {
  height: 100%;
  border-radius: 99px;
  transition: width 0.4s ease;
}
.fill-ce, .conf-bar-high   { background: var(--ce); }
.fill-pe, .conf-bar-low    { background: var(--pe); }
.fill-amber, .conf-bar-med { background: var(--amber); }

/* ── Confirmation Box ── */
.confirm-box {
  background: rgba(255, 77, 109, 0.08);
  border: 1px solid var(--pe-border);
  border-radius: var(--r-sm);
  padding: 12px 16px;
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* ── Touch Targets & Buttons ── */
.stButton > button {
  font-family: 'Space Grotesk', -apple-system, sans-serif !important;
  font-weight: 700 !important;
  font-size: 13px !important;
  letter-spacing: 0.04em !important;
  text-transform: uppercase !important;
  border-radius: var(--r-sm) !important;
  border: 1px solid var(--border-hi) !important;
  background: var(--bg-2) !important;
  color: var(--text-0) !important;
  min-height: var(--touch-min) !important;
  min-width: var(--touch-min) !important;
  padding: 8px 16px !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  transition: all 0.15s ease !important;
}
.stButton > button:hover {
  background: var(--bg-3) !important;
  border-color: var(--indigo) !important;
  color: #ffffff !important;
}

/* Danger [ CLOSE POSITION ] Button */
.stButton button[kind="primary"], .close-position {
  background: rgba(255, 77, 109, 0.12) !important;
  border: 1px solid rgba(255, 77, 109, 0.45) !important;
  color: #ff4d6d !important;
  min-height: var(--touch-min) !important;
}
.stButton button[kind="primary"]:hover, .close-position:hover {
  background: rgba(255, 77, 109, 0.25) !important;
  border-color: #ff4d6d !important;
  color: #ffffff !important;
}

/* ── Navigation Tabs ── */
.stTabs [data-baseweb="tab-list"] {
  background: var(--bg-1);
  border: 1px solid var(--border-blue);
  border-radius: var(--r);
  padding: 4px;
  gap: 4px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }
.stTabs [data-baseweb="tab"] {
  background: transparent;
  border: none !important;
  border-radius: var(--r-sm);
  padding: 8px 14px !important;
  min-height: var(--touch-min) !important;
  font-family: 'Space Grotesk', sans-serif !important;
  font-weight: 700 !important;
  font-size: 13px !important;
  letter-spacing: 0.04em !important;
  color: var(--text-1);
  white-space: nowrap;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.stTabs [data-baseweb="tab"]:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.03);
}
.stTabs [aria-selected="true"] {
  background: var(--indigo-dim) !important;
  color: #ffffff !important;
  border: 1px solid var(--indigo-hi) !important;
  border-bottom: 2px solid var(--purple) !important;
}

/* ── Signal Cards ── */
.signal-card {
  border-radius: var(--r);
  padding: 16px 18px;
  margin-bottom: 10px;
}
.sc-ce {
  background: var(--ce-dim) !important;
  border: 1px solid var(--ce-border) !important;
  border-left: 4px solid var(--ce) !important;
}
.sc-pe {
  background: var(--pe-dim) !important;
  border: 1px solid var(--pe-border) !important;
  border-left: 4px solid var(--pe) !important;
}
.sc-wait {
  background: var(--amber-dim) !important;
  border: 1px solid var(--amber-border) !important;
  border-left: 4px solid var(--amber) !important;
}

/* ── Empty State ── */
.empty-state {
  text-align: center;
  padding: 50px 20px;
  background: var(--bg-1);
  border: 1px dashed var(--border-blue);
  border-radius: var(--r);
  margin: 12px 0;
}
.empty-state .icon { font-size: 36px; margin-bottom: 10px; opacity: 0.7; }
.empty-state .msg  { font-family: 'Space Grotesk', sans-serif; font-size: 16px; font-weight: 700; color: #ffffff; margin-bottom: 4px; }
.empty-state .sub  { font-size: 12px; color: var(--text-2); }

/* ── Responsive Grids ── */
.kpi-grid, .filter-grid, .tracker-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 10px;
}

@media (min-width: 600px) {
  .kpi-grid     { grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .filter-grid  { grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .tracker-grid { grid-template-columns: repeat(3, 1fr); gap: 10px; }
}

@media (min-width: 960px) {
  .block-container {
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    padding-bottom: 30px !important;
  }
  .kpi-grid     { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
  .filter-grid  { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
  .tracker-grid { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
}

/* ── Bottom Sticky Bar on Mobile ── */
@media (max-width: 768px) {
  .mobile-signal-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 999999;
    background: rgba(6, 7, 13, 0.96);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-top: 1px solid var(--border-hi);
    padding: 10px 14px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 56px;
  }
}
@media (min-width: 769px) {
  .mobile-signal-bar { display: none !important; }
}

/* Stale overlay disabled */
div[data-stale="true"] { opacity: 1 !important; }
</style>
"""
