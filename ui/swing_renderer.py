import streamlit as st
import pandas as pd
from core.swing_manager import master_swing_scanner, calculate_risk_management
from config import CAPITAL

def render_swing_tab(copilot, notifier):
    st.markdown('<div class="card-inset"><h2 style="color:#38bdf8;">📈 SWING TRADING SCANNER (CASH MARKET)</h2></div>', unsafe_allow_html=True)
    
    # Default Watchlist
    default_nifty50 = [
        'RELIANCE', 'TCS',       'HDFCBANK',  'INFY',
        'ICICIBANK','WIPRO',     'AXISBANK',  'SBIN',
        'TATAMOTORS','BAJFINANCE','HCLTECH',  'KOTAKBANK',
        'LT',       'ASIANPAINT','MARUTI',    'TITAN',
        'SUNPHARMA','NESTLEIND', 'ONGC',      'NTPC'
    ]
    
    if "swing_watchlist" not in st.session_state:
        st.session_state["swing_watchlist"] = default_nifty50.copy()
        
    st.markdown("### Watchlist Management")
    col1, col2 = st.columns([3, 1])
    with col1:
        new_symbol = st.text_input("Add Stock Symbol (e.g. ITC, TATAPOWER)", key="add_stock_symbol").upper()
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Add to Watchlist", key="btn_add_stock"):
            if new_symbol and new_symbol not in st.session_state["swing_watchlist"]:
                st.session_state["swing_watchlist"].append(new_symbol)
                st.success(f"{new_symbol} added to watchlist!")
            elif new_symbol:
                st.warning(f"{new_symbol} is already in the watchlist.")
                
    st.write(f"**Current Watchlist:** {', '.join(st.session_state['swing_watchlist'])}")
    
    st.markdown("---")
    
    if st.button("🚀 RUN MASTER SCANNER", use_container_width=True, type="primary"):
        with st.spinner(f"Scanning {len(st.session_state['swing_watchlist'])} stocks... This may take a moment."):
            results_df = master_swing_scanner(st.session_state["swing_watchlist"])
            
            if not results_df.empty:
                st.session_state["swing_results"] = results_df
            else:
                st.error("No results generated. Data fetch might have failed.")
                
    if "swing_results" in st.session_state:
        st.markdown("### 🎯 SCANNER RESULTS")
        results = st.session_state["swing_results"]
        
        # Display as a dataframe with highlighting
        st.dataframe(
            results.style.map(
                lambda x: 'background-color: #064e3b; color: white' if '🔥' in str(x) else '',
                subset=['Grade']
            ).format({'Close': '{:.2f}', 'Stop_Loss': '{:.2f}', 'Target': '{:.2f}', 'R:R': '{:.2f}'}),
            use_container_width=True,
            height=400
        )
        
        st.markdown("### 🏆 TOP SWING TRADE PICKS (Score >= 8)")
        top_picks = results[results['Score'] >= 8]
        
        if not top_picks.empty:
            for _, row in top_picks.iterrows():
                with st.expander(f"📌 {row['Symbol']} | Grade: {row['Grade']}"):
                    col_info, col_risk = st.columns(2)
                    with col_info:
                        st.markdown(f"**Entry Price:** ₹{row['Close']}")
                        st.markdown(f"**Stop Loss:** ₹{row['Stop_Loss']}")
                        st.markdown(f"**Target:** ₹{row['Target']}")
                        st.markdown(f"**R:R Ratio:** {row['R:R']}x")
                        st.markdown(f"**Signals:** {row['Signals']}")
                    
                    with col_risk:
                        st.markdown("**Risk Management Calculator**")
                        # Use CAPITAL from config
                        cap = st.number_input(f"Capital for {row['Symbol']}", value=int(CAPITAL), step=10000, key=f"cap_{row['Symbol']}")
                        
                        risk_info = calculate_risk_management(
                            capital=cap,
                            entry=row['Close'],
                            stop_loss=row['Stop_Loss'],
                            target=row['Target']
                        )
                        
                        if risk_info:
                            st.write(f"**Risk/Share:** ₹{risk_info['Risk_Share']:.2f}")
                            st.write(f"**Reward/Share:** ₹{risk_info['Reward_Share']:.2f}")
                            st.write(f"**Quantity:** {risk_info['Quantity']} shares")
                            st.write(f"**Invest Amount:** ₹{risk_info['Invest_Amount']:,.0f}")
                            st.write(f"**Max Loss:** ₹{risk_info['Max_Loss']:,.0f} (2%)")
                            st.markdown(f"**Status:** {risk_info['Status']}")
                        else:
                            st.error("Invalid Stop Loss or Target for R:R calculation")
                            
            # Telegram Bot Integration for A+ Stocks
            aplus_picks = results[results['Score'] >= 10]
            if not aplus_picks.empty:
                st.markdown("---")
                if st.button("📲 Generate & Send A+ Picks via Telegram Copilot"):
                    with st.spinner("Copilot is drafting the message..."):
                        aplus_data = aplus_picks.to_dict('records')
                        draft = copilot.draft_swing_message(aplus_data)
                        if draft:
                            notifier.send(draft)
                            st.success("✅ Telegram message sent successfully!")
                            st.markdown("### Preview of sent message:")
                            st.info(draft)
                        else:
                            st.error("Failed to generate message.")
        else:
            st.info("No stocks matched the Top Pick criteria (Score >= 8) today.")
