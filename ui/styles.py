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
  font-family: 'Segoe UI', Arial, sans-serif;
  background-color: var(--bg-0) !important;
  color: var(--text-0);
  -webkit-font-smoothing: antialiased;
  line-height: 1.5;
}

/* ── Prevent Streamlit Screen Dimming / Fading on Refresh & Reruns ── */
[data-stale="true"],
[data-stale="true"] *,
[stale_data="true"],
[stale_data="true"] * {
  opacity: 1 !important;
  filter: none !important;
  transition: none !important;
  -webkit-transition: none !important;
}

.stApp [data-stale="true"],
[data-testid="stAppViewContainer"] [data-stale="true"],
[data-testid="stAppViewBlockContainer"] [data-stale="true"],
[data-testid="stMain"] [data-stale="true"],
[data-testid="stMainBlockContainer"] [data-stale="true"],
[data-testid="stVerticalBlock"] [data-stale="true"],
[data-testid="stVerticalBlockBorderWrapper"] [data-stale="true"],
.element-container [data-stale="true"],
div[data-stale="true"],
.stMarkdown[data-stale="true"] {
  opacity: 1 !important;
  filter: none !important;
  transition: none !important;
  -webkit-transition: none !important;
}

/* Ensure containers and fragment roots never drop opacity or trigger fade animations */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
.block-container,
[data-testid="stVerticalBlock"],
div[data-testid="stVerticalBlock"] > div,
[data-baseweb="tab-panel"] {
  opacity: 1 !important;
  transition: none !important;
  -webkit-transition: none !important;
}

/* ── Keep Streamlit's sidebar toggle; remove secondary chrome ── */
header[data-testid="stHeader"] {
  background: transparent !important;
}
footer[data-testid="stFooter"],
.stDeployButton,
[data-testid="stStatusWidget"],
.stStatusWidget {
  display: none !important;
  visibility: hidden !important;
  opacity: 0 !important;
}

section[data-testid="stSidebar"] {
  display: block !important;
  visibility: visible !important;
  opacity: 1 !important;
  width: 92px !important;
  min-width: 92px !important;
  background: linear-gradient(180deg, #0d0f18 0%, #090b12 100%);
  border-right: 1px solid var(--border-blue);
}
section[data-testid="stSidebar"] > div {
  width: 92px !important;
  padding: 1rem 0.55rem 1rem;
}
.nav-brand {
  display: grid;
  width: 54px;
  height: 54px;
  margin: 0 auto 20px;
  place-items: center;
  border: 1px solid rgba(129, 140, 248, 0.2);
  border-radius: 17px;
  background: rgba(99, 102, 241, 0.12);
}
.nav-brand strong {
  display: block;
  color: #d9d6ff;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 17px;
  letter-spacing: -0.06em;
}
.nav-brand strong span {
  color: #818cf8;
}
.nav-section-label {
  margin: 0 0 13px;
  color: #55596d;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-align: center;
}
section[data-testid="stSidebar"] .stButton {
  margin: 0 0 9px;
}
section[data-testid="stSidebar"] button:not([kind="headerNoPadding"]) {
  width: 54px !important;
  min-width: 54px !important;
  max-width: 54px !important;
  min-height: 54px !important;
  margin: 0 auto;
  padding: 0 !important;
  border: 1px solid transparent !important;
  border-radius: 17px !important;
  background: transparent !important;
  color: #777d91 !important;
  font-family: 'Segoe UI Symbol', 'Segoe UI', sans-serif !important;
  font-size: 22px !important;
  line-height: 1 !important;
  letter-spacing: 0 !important;
}
section[data-testid="stSidebar"] button:not([kind="headerNoPadding"]):hover {
  border-color: rgba(129, 140, 248, 0.2) !important;
  background: rgba(129, 140, 248, 0.08) !important;
  color: #d2ceff !important;
}
section[data-testid="stSidebar"] button[kind="primary"] {
  border-color: rgba(129, 140, 248, 0.18) !important;
  background: rgba(99, 102, 241, 0.17) !important;
  color: #b7afff !important;
  box-shadow: inset 0 0 18px rgba(99, 102, 241, 0.06);
}
.st-key-mobile_bottom_nav {
  display: none;
}

/* ── Main Container Padding ── */
.block-container {
  padding-top: 0.6rem !important;
  padding-left: 0.85rem !important;
  padding-right: 0.85rem !important;
  padding-bottom: 70px !important;
  max-width: 1600px !important;
}

/* ── Typography & Hierarchy: Numbers are the HERO ── */
.num, .kpi, .kpi-lg, .kpi-sm, .signal-hero, .trade-val {
  font-family: 'Segoe UI', Arial, sans-serif !important;
  font-feature-settings: 'tnum' on, 'lnum' on;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.15;
  color: var(--text-0);
}

/* Labels RECEDE: small, muted uppercase */
.label {
  font-family: 'Segoe UI', Arial, sans-serif !important;
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
.dashboard-top {
  margin: 0 0 18px;
  padding: 30px 44px 32px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.035);
  border-radius: 34px;
  background: #08080b;
}
.app-header {
  padding: 0;
  margin: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 18px 24px;
  background: transparent;
}
.app-header-left h1 {
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: clamp(34px, 4vw, 58px);
  font-weight: 400;
  color: #e9e9ef;
  margin: 0;
  letter-spacing: -0.055em;
  display: flex;
  align-items: center;
  gap: 14px;
}
.brand-v {
  color: #e9e9ef;
}
.brand-pro {
  color: #aaa3df;
  font-size: 0.48em;
  font-weight: 500;
  letter-spacing: 0.11em;
  white-space: nowrap;
}
.app-header-left p {
  margin-top: 10px;
  color: #85869a;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 15px;
  font-weight: 500;
  letter-spacing: 0.1em;
  text-transform: none;
}
.app-header-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
}
.app-header-status {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
}
.header-indicator {
  display: inline-flex;
  width: 60px;
  height: 60px;
  align-items: center;
  justify-content: center;
  border: 2px solid currentColor;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.025);
  font-size: 17px;
  line-height: 1;
}
.header-indicator-purple {
  color: #6352e8;
}
.header-indicator-red {
  color: #d82c35;
}
.header-indicator-off {
  opacity: 0.58;
}
.header-indicator-on {
  background: rgba(0, 229, 160, 0.06);
}
.header-status-divider {
  width: 1px;
  height: 40px;
  margin: 0 8px;
  background: #393943;
}
.market-status {
  display: inline-flex;
  min-height: 50px;
  align-items: center;
  gap: 12px;
  padding: 0 23px;
  border: 1.5px solid currentColor;
  border-radius: 999px;
  font-size: 17px;
  font-weight: 600;
  white-space: nowrap;
}
.market-status i {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: currentColor;
}
.market-closed {
  color: #ed555b;
  background: rgba(237, 85, 91, 0.06);
}
.market-open {
  color: var(--ce);
  background: rgba(0, 229, 160, 0.06);
}
.header-datetime {
  color: #85869a;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.09em;
}

/* ── Market Ticker Strip ── */
.market-ticker {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 34px 0 22px;
  padding: 24px 0;
  overflow-x: auto;
  border: 1px solid #292a36;
  border-radius: 24px;
  background: #101015;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.market-ticker::-webkit-scrollbar { display: none; }
.ticker-item {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
  padding: 0 32px;
  border-right: 1px solid #292a36;
}
.ticker-item:last-child {
  border-right: none;
}
.ticker-symbol {
  color: #85869a;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.08em;
}
.ticker-val {
  color: #e9e9ef;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 24px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.025em;
}
.scanner-status-line {
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 24px;
  padding-left: 4px;
  color: #85869a;
  font-size: 15px;
}
.scanner-status-icon {
  position: relative;
  display: inline-block;
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  border: 1px solid #54a9e8;
}
.scanner-active .scanner-status-icon::after {
  position: absolute;
  top: 4px;
  left: 4px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #54a9e8;
  content: "";
}
.scanner-disabled .scanner-status-icon {
  border-color: var(--text-2);
}
.scanner-status-line > span:last-child {
  overflow-wrap: anywhere;
}

/* ── Status Pills (Market Open / Closed / Live) ── */
.pill, .status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 99px;
  font-family: 'Segoe UI', Arial, sans-serif;
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
.account-overview {
  margin: 2px 0 14px;
  padding: 20px 22px 15px;
  border: 1px solid var(--border-blue);
  border-radius: 16px;
  background: linear-gradient(145deg, #111421 0%, #0b0d14 100%);
}
.account-overview-top,
.account-equity-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}
.account-overview-top {
  margin-bottom: 22px;
}
.account-brand {
  color: #f8fafc;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.04em;
}
.account-brand small {
  margin-left: 5px;
  color: var(--text-1);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.06em;
}
.account-cloud-status {
  padding: 5px 9px;
  border: 1px solid var(--ce-border);
  border-radius: 999px;
  background: var(--ce-dim);
  color: var(--ce);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
}
.account-equity-label,
.account-overview-label {
  display: block;
  color: var(--text-1);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
}
.account-equity {
  font-size: clamp(30px, 4vw, 46px);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.05em;
  line-height: 1.15;
}
.account-equity-change {
  padding: 4px 9px;
  border-radius: 7px;
  background: rgba(255, 77, 109, 0.12);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.account-capital-note {
  margin-top: 3px;
  color: var(--text-1);
  font-size: 12px;
}
.account-capital-note span {
  padding: 0 5px;
  color: var(--text-2);
}
.account-margin-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 18px;
  padding-top: 15px;
  border-top: 1px solid var(--border-hi);
}
.account-margin-row > div {
  min-width: 0;
  padding-right: 12px;
  border-right: 1px solid var(--border-hi);
}
.account-margin-row > div:last-child {
  padding-right: 0;
  border-right: 0;
}
.account-margin-row strong {
  display: block;
  margin-top: 4px;
  color: #f8fafc;
  font-size: 17px;
  font-variant-numeric: tabular-nums;
}
.account-realized-note {
  display: block;
  margin-top: 12px;
  color: var(--text-1);
  font-size: 11px;
}
.positions-summary {
  margin-bottom: 16px;
}
.positions-summary-heading {
  margin: 0 0 8px;
  color: var(--text-1) !important;
}
.positions-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.positions-summary-card {
  min-width: 0;
  margin: 0;
  padding: 12px 14px;
  border-color: var(--border-hi);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.018);
}
.positions-summary-card .kpi {
  font-size: clamp(18px, 2vw, 24px);
  overflow-wrap: anywhere;
}
.win-rate-track {
  height: 4px;
  margin-top: 8px;
  overflow: hidden;
  border-radius: 99px;
  background: rgba(148, 163, 184, 0.2);
}
.win-rate-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--ce);
}
.trade-card {
  margin: 0 0 10px;
  padding: 15px 18px 13px;
  border: 1px solid var(--border-hi);
  border-left: 3px solid var(--border-hi);
  border-radius: 13px;
  background: linear-gradient(145deg, rgba(17, 20, 33, 0.98), rgba(13, 15, 24, 0.94));
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
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
}
.trade-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
}
.trade-instrument {
  color: #f8fafc;
  font-size: 17px;
  font-weight: 700;
}
.trade-direction {
  padding: 4px 8px;
  border-radius: 6px;
  background: rgba(0, 229, 160, 0.12);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
}
.trade-contract {
  color: var(--text-1);
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 13px;
  font-weight: 600;
}
.trade-status {
  padding: 3px 7px;
  border-radius: 999px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
}
.trade-status-open {
  border: 1px solid var(--ce-border);
  color: var(--ce);
}
.trade-status-closed {
  border: 1px solid var(--border-hi);
  color: var(--text-1);
}
.trade-pnl {
  font-size: 23px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.trade-live-line {
  margin: 0 0 5px 8px;
  color: var(--text-1);
  font-size: 11px;
}
.trade-live-line strong {
  margin-left: 5px;
  font-variant-numeric: tabular-nums;
}
.trade-price-track {
  position: relative;
  height: 16px;
  margin: 13px 8px 2px;
}
.trade-track-base,
.trade-track-risk,
.trade-track-reward {
  position: absolute;
  top: 5px;
  height: 7px;
  border-radius: 99px;
}
.trade-track-base {
  right: 0;
  left: 0;
  background: rgba(148, 163, 184, 0.16);
}
.trade-track-risk {
  background: rgba(255, 77, 109, 0.78);
}
.trade-track-reward {
  background: rgba(0, 229, 160, 0.35);
}
.trade-track-marker {
  position: absolute;
  z-index: 1;
  top: 1px;
  width: 3px;
  height: 15px;
  border-radius: 2px;
  transform: translateX(-50%);
}
.trade-marker-sl { background: var(--amber); }
.trade-marker-entry { background: #f8fafc; }
.trade-marker-target { background: var(--ce); }
.trade-marker-live {
  top: 0;
  width: 12px;
  height: 12px;
  border: 2px solid var(--bg-1);
  border-radius: 50%;
  background: var(--pe);
}
.trade-track-labels {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  align-items: start;
  margin: 0 8px 8px;
  font-size: 10px;
}
.trade-track-labels span:nth-child(2) { text-align: center; color: var(--text-1); }
.trade-track-labels span:last-child { text-align: right; }
.trade-stop-label { color: var(--amber); }
.trade-entry-label b, .trade-track-labels b { font-weight: 600; }
.trade-target-label { color: var(--ce); }
.trade-detail-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  color: var(--text-1);
  font-size: 11px;
}
.trade-detail-row span {
  white-space: nowrap;
}
.trade-detail-row b {
  margin-left: 3px;
  color: #f8fafc;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
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
  font-family: 'Segoe UI', Arial, sans-serif !important;
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
  font-family: 'Segoe UI', Arial, sans-serif !important;
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

/* ── Navigation Pills (Fast Lazy Tabs) ── */
div[data-testid="stPills"] {
  background: var(--bg-1);
  border: 1px solid var(--border-blue);
  border-radius: var(--r);
  padding: 4px;
  gap: 4px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  margin-bottom: 12px;
  display: flex !important;
  flex-wrap: nowrap !important;
}
div[data-testid="stPills"]::-webkit-scrollbar { display: none; }
section[data-testid="stSidebar"] div[data-testid="stPills"] {
  width: 100%;
  flex-direction: column;
  align-items: stretch;
  overflow: visible;
}
section[data-testid="stSidebar"] div[data-testid="stPills"] button {
  width: 100%;
  justify-content: flex-start !important;
  text-align: left;
  font-size: 12px !important;
}
div[data-testid="stPills"] button {
  background: transparent !important;
  border: 1px solid transparent !important;
  border-radius: var(--r-sm) !important;
  padding: 8px 14px !important;
  min-height: var(--touch-min) !important;
  font-family: 'Segoe UI', Arial, sans-serif !important;
  font-weight: 700 !important;
  font-size: 13px !important;
  letter-spacing: 0.04em !important;
  color: var(--text-1) !important;
  white-space: nowrap !important;
  flex: 0 0 auto !important;
  scroll-snap-align: start;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  transition: all 0.15s ease !important;
}
div[data-testid="stPills"] button:hover {
  color: #ffffff !important;
  background: rgba(255, 255, 255, 0.04) !important;
}
div[data-testid="stPills"] button[aria-pressed="true"],
div[data-testid="stPills"] button[aria-selected="true"],
div[data-testid="stPills"] button[data-checked="true"] {
  background: var(--indigo-dim) !important;
  color: #ffffff !important;
  border: 1px solid var(--indigo-hi) !important;
  border-bottom: 2px solid var(--purple) !important;
}

/* ── Readability, focus, and high-density dashboard surfaces ── */
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {
  color: #f8fafc;
  letter-spacing: -0.025em;
  line-height: 1.25;
  margin-bottom: 0.45rem;
}
.stMarkdown p, .stCaption, [data-testid="stCaptionContainer"] {
  line-height: 1.55;
}
.stMarkdown a {
  color: #a5b4fc !important;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}
.stApp :is(button, input, textarea, [role="combobox"], [role="slider"]):focus-visible {
  outline: 2px solid #818cf8 !important;
  outline-offset: 2px !important;
  box-shadow: 0 0 0 4px rgba(129, 140, 248, 0.18) !important;
}
.stApp [data-testid="stMetric"] {
  background: linear-gradient(145deg, rgba(17, 20, 33, 0.96), rgba(13, 15, 24, 0.96));
  border: 1px solid var(--border-blue);
  border-radius: 10px;
  padding: 12px 14px;
  min-height: 88px;
}
.stApp [data-testid="stMetricLabel"] {
  color: var(--text-1) !important;
  font-size: 0.76rem;
  font-weight: 600;
}
.stApp [data-testid="stMetricValue"] {
  color: #f8fafc;
  font-family: 'Segoe UI', Arial, sans-serif;
  font-variant-numeric: tabular-nums;
}
.stApp [data-testid="stDataFrame"],
.stApp [data-testid="stTable"] {
  border: 1px solid var(--border-blue);
  border-radius: 10px;
  overflow: hidden;
}
.stApp [data-testid="stTextInput"] input,
.stApp [data-testid="stNumberInput"] input,
.stApp [data-testid="stDateInput"] input,
.stApp [data-testid="stSelectbox"] [role="combobox"] {
  background: var(--bg-1);
  border-color: var(--border-hi);
  border-radius: var(--r-sm);
  min-height: var(--touch-min);
}
.stApp [data-testid="stHorizontalBlock"] {
  gap: 0.85rem;
}

/* ── Signal Cards ── */
.signal-overview {
  margin: 4px 0 10px;
  padding: 20px 22px 0;
  overflow: hidden;
  background: linear-gradient(145deg, #111421 0%, #0c0e16 100%);
  border: 1px solid var(--border-blue);
  border-radius: 14px;
}
.signal-overview-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 170px;
  align-items: center;
  gap: 12px;
  min-height: 174px;
}
.signal-eyebrow, .signal-overview-label {
  color: var(--text-1);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.signal-eyebrow span {
  color: var(--text-2);
  padding: 0 4px;
}
.signal-spot {
  margin: 8px 0 12px;
  color: #f8fafc;
  font-size: clamp(38px, 5.2vw, 62px);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.055em;
  line-height: 1.05;
}
.signal-bias {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
}
.signal-bias.c-pe {
  background: rgba(255, 77, 109, 0.88);
  color: #18080c !important;
  -webkit-text-fill-color: #18080c !important;
}
.signal-bias.c-ce {
  background: rgba(0, 229, 160, 0.88);
  color: #03140e !important;
  -webkit-text-fill-color: #03140e !important;
}
.signal-bias.c-amber {
  background: rgba(245, 158, 11, 0.9);
  color: #1c1204 !important;
  -webkit-text-fill-color: #1c1204 !important;
}
.signal-bias-icon {
  font-size: 19px;
  line-height: 1;
}
.pcr-gauge {
  position: relative;
  width: 160px;
  height: 112px;
  margin: 0 auto;
  text-align: center;
}
.pcr-gauge svg {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}
.pcr-gauge svg path {
  fill: none;
  stroke-width: 11;
  stroke-linecap: round;
}
.pcr-gauge-track {
  stroke: rgba(148, 163, 184, 0.2);
}
.pcr-gauge-value {
  transition: stroke-dashoffset 0.25s ease;
}
.pcr-gauge-number {
  position: absolute;
  right: 0;
  bottom: 21px;
  left: 0;
  color: #f8fafc;
  font-size: 25px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.pcr-gauge-label {
  position: absolute;
  right: 0;
  bottom: 3px;
  left: 0;
  color: var(--text-1);
  font-size: 10px;
  letter-spacing: 0.12em;
}
.signal-context-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr);
  align-items: center;
  gap: 18px;
  min-height: 68px;
  border-top: 1px solid var(--border-hi);
}
.signal-context-stat {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}
.signal-overview-value {
  color: #f8fafc;
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.signal-context-divider {
  width: 1px;
  height: 42px;
  background: var(--border-hi);
}
.signal-diagnostics {
  margin: 0 0 12px;
  border: 1px solid var(--border-blue);
  border-radius: 10px;
  background: rgba(13, 15, 24, 0.7);
}
.signal-diagnostics summary {
  padding: 10px 14px;
  color: var(--text-1);
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.signal-diagnostics[open] summary {
  border-bottom: 1px solid var(--border);
  color: #f8fafc;
}
.signal-diagnostics .filter-grid {
  padding: 10px;
}
.signal-diagnostics .card {
  margin: 0;
}
.cooldown-notice {
  margin: 10px 0;
  border-left: 3px solid var(--indigo) !important;
}
.signal-card {
  margin: 4px 0 12px;
  padding: 22px 25px 20px;
  overflow: hidden;
  border: 1px solid #252631;
  border-radius: 18px;
  background: #101015;
}
.signal-card.sc-ce {
  border-color: rgba(0, 229, 160, 0.28);
  background: #0e1213;
}
.signal-card.sc-pe {
  border-color: rgba(255, 77, 109, 0.28);
  background: #130f12;
}
.signal-card.sc-wait {
  border-color: #292a36;
  background: #101015;
}
.signal-card-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.signal-card-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  color: #a2a2b4;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: capitalize;
}
.signal-card-eyebrow > span {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--amber);
}
.sc-ce .signal-card-eyebrow > span { background: var(--ce); }
.sc-pe .signal-card-eyebrow > span { background: var(--pe); }
.signal-state-pill {
  padding: 5px 13px;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.12);
  color: #ffb52e;
  font-size: 12px;
  font-weight: 700;
}
.sc-ce .signal-state-pill {
  background: var(--ce-dim);
  color: var(--ce);
}
.sc-pe .signal-state-pill {
  background: var(--pe-dim);
  color: var(--pe);
}
.signal-card-main {
  display: flex;
  min-height: 160px;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 8px 0 18px;
}
.signal-card-primary {
  min-width: 0;
}
.signal-hero {
  margin: 0 0 12px !important;
  color: #f1f0f5;
  font-family: 'Segoe UI', Arial, sans-serif !important;
  font-size: clamp(52px, 6vw, 70px);
  font-weight: 500;
  letter-spacing: -0.055em;
  line-height: 1.05;
  text-transform: uppercase;
}
.sc-ce .signal-hero { color: var(--ce); }
.sc-pe .signal-hero { color: var(--pe); }
.signal-action-switch {
  display: inline-grid;
  grid-template-columns: repeat(3, minmax(58px, 1fr));
  align-items: center;
  gap: 4px;
  min-height: 43px;
  padding: 4px;
  border: 1px solid #292a36;
  border-radius: 13px;
  background: #09090d;
}
.signal-action-option {
  padding: 8px 13px;
  border-radius: 9px;
  color: #85869a;
  font-size: 13px;
  text-align: center;
}
.signal-action-selected {
  background: rgba(245, 158, 11, 0.16);
  color: #ffb52e;
  font-weight: 700;
}
.sc-ce .signal-action-selected {
  background: rgba(0, 229, 160, 0.15);
  color: var(--ce);
}
.sc-pe .signal-action-selected {
  background: rgba(255, 77, 109, 0.15);
  color: var(--pe);
}
.signal-confidence {
  flex: 0 0 auto;
}
.signal-confidence-ring {
  display: grid;
  width: 106px;
  height: 106px;
  place-items: center;
  border-radius: 50%;
}
.signal-confidence-inner {
  display: flex;
  width: 88px;
  height: 88px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #101015;
}
.signal-confidence-inner strong {
  color: #f1f0f5;
  font-size: 26px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
}
.signal-confidence-inner span {
  margin-top: 3px;
  color: #8b91a8;
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.signal-data-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.signal-data-cell {
  display: flex;
  min-width: 0;
  min-height: 62px;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding: 9px 14px;
  border: 1px solid #292a36;
  border-radius: 13px;
  background: rgba(15, 16, 23, 0.7);
}
.signal-data-cell > span {
  color: #8b91a8;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 11px;
  letter-spacing: 0.07em;
}
.signal-data-cell > strong {
  overflow: hidden;
  color: #f0eff5;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.signal-data-cell > strong small {
  margin-left: 5px;
  color: #9298ad;
  font-size: 11px;
  font-weight: 400;
}
.signal-buffer-bars {
  display: flex;
  gap: 6px;
  align-items: center;
}
.signal-buffer-bar {
  display: block;
  width: 100%;
  height: 7px;
  border-radius: 99px;
}
.signal-buffer-active { background: var(--amber); }
.sc-ce .signal-buffer-active { background: var(--ce); }
.sc-pe .signal-buffer-active { background: var(--pe); }
.signal-buffer-muted { background: #393b49; }
.signal-card .badge-warning {
  display: inline-flex;
  margin-top: 10px;
}
.signal-market-notice,
.signal-filter-note {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  padding: 12px 15px;
  border-radius: 12px;
  color: #ff7778;
  font-size: 12px;
}
.signal-market-notice {
  background: rgba(103, 22, 25, 0.16);
}
.signal-market-notice > span:first-child {
  flex: 0 0 auto;
  font-size: 18px;
}
.signal-filter-note {
  background: rgba(148, 163, 184, 0.06);
  color: var(--text-1);
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
.empty-state .msg  { font-family: 'Segoe UI', Arial, sans-serif; font-size: 16px; font-weight: 700; color: #ffffff; margin-bottom: 4px; }
.empty-state .sub  { font-size: 12px; color: var(--text-2); }

/* ── Responsive Grids ── */
.kpi-grid, .filter-grid, .tracker-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}
.kpi-context-card {
  min-width: 0;
  padding: 14px 16px;
  background: linear-gradient(145deg, rgba(17, 20, 33, 0.98), rgba(13, 15, 24, 0.96));
}
.kpi-context-card .label {
  color: var(--text-1) !important;
  letter-spacing: 0.09em !important;
}
.kpi-context-card .kpi {
  overflow-wrap: anywhere;
  font-size: clamp(19px, 2vw, 26px);
}

@media (min-width: 600px) {
  .kpi-grid     { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
  .filter-grid  { grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .tracker-grid { grid-template-columns: repeat(3, 1fr); gap: 10px; }
}

@media (min-width: 960px) {
  .block-container {
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    padding-bottom: 30px !important;
  }
  .kpi-grid     { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
  .filter-grid  { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
  .tracker-grid { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
}

@media (max-width: 768px) {
  .block-container {
    padding-top: 0.4rem !important;
    padding-left: 0.65rem !important;
    padding-right: 0.65rem !important;
    padding-bottom: 132px !important;
  }
  section[data-testid="stSidebar"] {
    display: none !important;
  }
  header[data-testid="stHeader"] button {
    display: none !important;
  }
  .st-key-mobile_bottom_nav {
    position: fixed !important;
    z-index: 1000001 !important;
    right: 0 !important;
    bottom: 0 !important;
    left: 0 !important;
    display: block !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 7px max(8px, env(safe-area-inset-right)) calc(7px + env(safe-area-inset-bottom)) max(8px, env(safe-area-inset-left)) !important;
    border-top: 1px solid rgba(148, 163, 184, 0.16);
    background: rgba(8, 9, 14, 0.97);
    box-shadow: 0 -8px 24px rgba(0, 0, 0, 0.28);
    -webkit-backdrop-filter: blur(18px);
    backdrop-filter: blur(18px);
  }
  .st-key-mobile_bottom_nav [data-testid="stHorizontalBlock"] {
    display: flex !important;
    flex-direction: row !important;
    gap: 4px !important;
  }
  .st-key-mobile_bottom_nav [data-testid="column"] {
    width: auto !important;
    min-width: 0 !important;
    flex: 1 1 0% !important;
  }
  .st-key-mobile_bottom_nav [data-testid="stColumn"] {
    width: auto !important;
    min-width: 0 !important;
    flex: 1 1 0% !important;
  }
  .st-key-mobile_bottom_nav .stButton,
  .st-key-mobile_bottom_nav [data-testid="stPopover"] {
    margin: 0 !important;
  }
  .st-key-mobile_bottom_nav .stButton > button,
  .st-key-mobile_bottom_nav [data-testid="stPopover"] > button,
  .st-key-mobile_bottom_nav [data-testid="stPopoverButton"],
  [class*="st-key-mobile_nav_"] button {
    display: flex !important;
    width: 100% !important;
    min-width: 0 !important;
    min-height: 48px !important;
    flex-direction: column !important;
    justify-content: center !important;
    gap: 2px !important;
    padding: 4px 2px !important;
    border: 1px solid transparent !important;
    border-radius: 10px !important;
    background: transparent !important;
    color: #7c8298 !important;
    font-size: 10px !important;
    font-weight: 500 !important;
    line-height: 1.1 !important;
    letter-spacing: 0 !important;
    text-align: center !important;
    text-transform: none !important;
    white-space: pre-line !important;
  }
  .st-key-mobile_bottom_nav .stButton > button p,
  .st-key-mobile_bottom_nav [data-testid="stPopoverButton"] p,
  [class*="st-key-mobile_nav_"] button p {
    margin: 0 !important;
    white-space: pre-line !important;
  }
  .st-key-mobile_bottom_nav .stButton > button:hover,
  .st-key-mobile_bottom_nav [data-testid="stPopoverButton"]:hover,
  [class*="st-key-mobile_nav_"] button:hover {
    background: rgba(129, 140, 248, 0.08) !important;
    color: #d2ceff !important;
  }
  .st-key-mobile_bottom_nav .stButton > button[kind="primary"],
  [class*="st-key-mobile_nav_"] button[kind="primary"] {
    background: rgba(99, 102, 241, 0.13) !important;
    color: #b8afff !important;
  }
  .st-key-mobile_bottom_nav [data-testid="stPopover"] {
    width: 100%;
  }
  .st-key-mobile_bottom_nav [data-testid="stPopoverButton"] {
    height: 48px;
  }
  .st-key-mobile_bottom_nav [data-testid="stPopoverBody"] {
    min-width: min(270px, calc(100vw - 24px));
  }
  .st-key-mobile_bottom_nav [data-testid="stPopoverBody"] .stButton > button {
    justify-content: flex-start !important;
    padding: 8px 12px !important;
    text-align: left !important;
  }
  .dashboard-top {
    padding: 20px 18px 22px;
    border-radius: 24px;
  }
  .app-header {
    align-items: flex-start;
    gap: 14px;
  }
  .app-header-left h1 {
    font-size: clamp(32px, 9vw, 44px);
    gap: 9px;
  }
  .app-header-left p {
    margin-top: 6px;
    font-size: 11px;
    letter-spacing: 0.07em;
  }
  .app-header-right {
    width: 100%;
    align-items: flex-start;
    gap: 8px;
  }
  .app-header-status {
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: 8px;
  }
  .header-indicator {
    width: 40px;
    height: 40px;
    font-size: 13px;
  }
  .header-status-divider {
    height: 30px;
    margin: 0 3px;
  }
  .market-status {
    min-height: 38px;
    gap: 8px;
    padding: 0 14px;
    font-size: 13px;
  }
  .market-status i {
    width: 8px;
    height: 8px;
  }
  .header-datetime {
    font-size: 11px;
    letter-spacing: 0.06em;
  }
  .market-ticker {
    display: flex;
    max-width: 100%;
    margin: 22px 0 15px;
    padding: 16px 0;
    border-radius: 17px;
    scroll-snap-type: x proximity;
    overscroll-behavior-x: contain;
  }
  .ticker-item {
    min-width: 155px;
    scroll-snap-align: start;
    gap: 4px;
    padding: 0 18px;
  }
  .ticker-symbol {
    font-size: 11px;
  }
  .ticker-val {
    font-size: 19px;
  }
  .scanner-status-line {
    align-items: flex-start;
    gap: 10px;
    font-size: 12px;
  }
  .scanner-status-icon {
    margin-top: 1px;
  }
  .scanner-status-line > span:last-child {
    line-height: 1.45;
  }
  .stApp [data-testid="stMetric"] {
    min-height: 76px;
    padding: 10px 12px;
  }

  @media (max-width: 420px) {
    .dashboard-top {
      padding: 17px 13px 18px;
      border-radius: 20px;
    }
    .app-header-left h1 {
      font-size: 33px;
      gap: 8px;
    }
    .brand-pro {
      font-size: 0.43em;
    }
    .app-header-status {
      gap: 6px;
    }
    .header-indicator {
      width: 35px;
      height: 35px;
      border-width: 1.5px;
      font-size: 11px;
    }
    .header-status-divider {
      height: 26px;
      margin: 0 2px;
    }
    .market-status {
      min-height: 35px;
      padding: 0 10px;
      font-size: 12px;
    }
    .market-ticker {
      margin-top: 18px;
    }
  }
  .stApp [data-testid="stMetricValue"] {
    font-size: clamp(1.15rem, 6vw, 1.65rem);
    overflow-wrap: anywhere;
  }
  .trade-card {
    padding: 12px !important;
  }
  .account-overview {
    padding: 16px 14px 12px;
    border-radius: 13px;
  }
  .account-overview-top {
    margin-bottom: 18px;
  }
  .account-equity-line {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }
  .account-equity {
    font-size: clamp(30px, 9vw, 40px);
  }
  .account-margin-row {
    gap: 8px;
    margin-top: 14px;
    padding-top: 12px;
  }
  .account-margin-row > div {
    padding-right: 6px;
  }
  .account-margin-row strong {
    font-size: clamp(12px, 3.8vw, 16px);
    overflow-wrap: anywhere;
  }
  .account-overview-label {
    font-size: 9px;
    letter-spacing: 0.04em;
  }
  .positions-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .positions-summary-card {
    padding: 10px 11px;
  }
  .trade-card {
    padding: 12px 12px 10px !important;
  }
  .trade-header {
    align-items: flex-start;
    gap: 5px;
  }
  .trade-title {
    gap: 6px 8px;
  }
  .trade-instrument {
    font-size: 15px;
  }
  .trade-contract {
    font-size: 11px;
  }
  .trade-pnl {
    font-size: 19px;
  }
  .trade-detail-row {
    gap: 7px 12px;
    font-size: 10px;
  }
  .trade-track-labels {
    font-size: 9px;
  }
  .signal-overview {
    padding: 16px 15px 0;
    border-radius: 12px;
  }
  .signal-card {
    padding: 17px 15px 15px;
    border-radius: 14px;
  }
  .signal-card-main {
    min-height: 132px;
    gap: 8px;
    padding: 8px 0 14px;
  }
  .signal-hero {
    margin-bottom: 10px !important;
    font-size: clamp(43px, 13vw, 60px);
  }
  .signal-action-switch {
    grid-template-columns: repeat(3, minmax(45px, 1fr));
    min-height: 39px;
    gap: 2px;
    padding: 3px;
  }
  .signal-action-option {
    padding: 7px 8px;
    font-size: 12px;
  }
  .signal-confidence-ring {
    width: 86px;
    height: 86px;
  }
  .signal-confidence-inner {
    width: 72px;
    height: 72px;
  }
  .signal-confidence-inner strong {
    font-size: 22px;
  }
  .signal-data-grid {
    gap: 6px;
  }
  .signal-data-cell {
    min-height: 59px;
    padding: 8px;
    border-radius: 10px;
  }
  .signal-data-cell > span {
    font-size: 10px;
  }
  .signal-data-cell > strong {
    font-size: 12px;
  }
  .signal-data-cell > strong small {
    margin-left: 2px;
    font-size: 9px;
  }
  .signal-buffer-bars {
    gap: 3px;
  }
  .signal-buffer-bar {
    height: 6px;
  }
  .signal-market-notice,
  .signal-filter-note {
    gap: 8px;
    padding: 10px;
    font-size: 11px;
  }
  .mobile-signal-bar {
    bottom: calc(64px + env(safe-area-inset-bottom)) !important;
  }
  .signal-overview-main {
    grid-template-columns: minmax(0, 1fr) 112px;
    gap: 4px;
    min-height: 148px;
  }
  .signal-eyebrow, .signal-overview-label {
    font-size: 9px;
    letter-spacing: 0.07em;
  }
  .signal-spot {
    margin: 10px 0 12px;
    font-size: clamp(34px, 10vw, 48px);
    letter-spacing: -0.06em;
  }
  .signal-bias {
    gap: 6px;
    padding: 8px 10px;
    font-size: 13px;
  }
  .pcr-gauge {
    width: 112px;
    height: 88px;
  }
  .pcr-gauge svg path {
    stroke-width: 10;
  }
  .pcr-gauge-number {
    bottom: 17px;
    font-size: 21px;
  }
  .pcr-gauge-label {
    bottom: 1px;
    font-size: 9px;
  }
  .signal-context-row {
    gap: 10px;
    min-height: 62px;
  }
  .signal-overview-value {
    font-size: 17px;
  }
  .kpi-context-card {
    padding: 12px;
  }
  .kpi-context-card .label {
    white-space: normal;
    min-height: 1.5em;
  }
  .trade-header {
    align-items: flex-start;
  }
  .trade-header > div:first-child {
    font-size: 14px !important;
  }
  .stApp [data-testid="stDataFrame"],
  .stApp [data-testid="stTable"] {
    max-width: 100%;
    overflow-x: auto;
  }
  .stApp :is(button, input, textarea, [role="combobox"]) {
    min-height: var(--touch-min);
  }
  div[data-testid="stPills"] {
    scroll-snap-type: x proximity;
    overscroll-behavior-x: contain;
  }
  .stApp [data-testid="stHorizontalBlock"] {
    gap: 0.5rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
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
  .st-key-mobile_bottom_nav { display: none !important; }
}

/* Instant visual feedback when switching tabs */
div[data-stale="true"] {
  opacity: 0.25 !important;
  transition: opacity 0.1s ease-out;
  pointer-events: none;
}
section[data-testid="stSidebar"] button[kind="primary"] {
  border-color: rgba(129, 140, 248, 0.18) !important;
  background: rgba(99, 102, 241, 0.17) !important;
  color: #b7afff !important;
  box-shadow: inset 0 0 18px rgba(99, 102, 241, 0.06) !important;
}
section[data-testid="stSidebar"] button:not([kind="headerNoPadding"]) p {
  display: none !important;
}
section[data-testid="stSidebar"] button:not([kind="headerNoPadding"]) [data-testid="stIconMaterial"] {
  color: inherit !important;
  font-size: 24px !important;
}
</style>
"""
