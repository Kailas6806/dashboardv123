import streamlit as st
import pandas as pd
from core.swing_manager import master_swing_scanner, calculate_risk_management
from config import CAPITAL

def create_swing_chart(symbol, row, df_chart):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        row_heights=[0.7, 0.3], vertical_spacing=0.03)
    
    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df_chart['DATE'], open=df_chart['OPEN'], high=df_chart['HIGH'],
        low=df_chart['LOW'], close=df_chart['CLOSE'], name="Candlestick",
        increasing_line_color='#22c55e', decreasing_line_color='#ef4444'
    ), row=1, col=1)
    
    # EMA 21 (Supertrend proxy)
    fig.add_trace(go.Scatter(
        x=df_chart['DATE'], y=df_chart['EMA_21'], 
        line=dict(color='#22c55e', width=1.5), name="EMA 21"
    ), row=1, col=1)
    
    # Target and Stop Loss lines
    fig.add_hline(y=row['Target_1'], line_dash="dash", line_color="#22c55e", 
                  annotation_text=f"Target 1: ₹{row['Target_1']}", annotation_position="top right", row=1, col=1)
    fig.add_hline(y=row['Target_2'], line_dash="dot", line_color="#22c55e", 
                  annotation_text=f"Target 2: ₹{row['Target_2']}", annotation_position="top right", row=1, col=1)
    fig.add_hline(y=row['Stop_Loss'], line_dash="dash", line_color="#ef4444", 
                  annotation_text=f"Stop Loss: ₹{row['Stop_Loss']}", annotation_position="bottom right", row=1, col=1)
    
    # Volume
    colors = ['#06b6d4' if c >= o else '#525252' for c, o in zip(df_chart['CLOSE'], df_chart['OPEN'])]
    fig.add_trace(go.Bar(
        x=df_chart['DATE'], y=df_chart['VOLUME'], marker_color=colors, name="Volume"
    ), row=2, col=1)
    
    # High Volume Marker
    high_vol_mask = df_chart['Vol_Rat'] > 1.5
    if high_vol_mask.any():
        high_vol_df = df_chart[high_vol_mask]
        fig.add_trace(go.Scatter(
            x=high_vol_df['DATE'], y=high_vol_df['VOLUME'], mode='markers',
            marker=dict(symbol='x', size=8, color='#d946ef', line=dict(width=2, color='#d946ef')),
            name="High Volume Marker"
        ), row=2, col=1)
        
    title_text = f"🎯 {symbol} | Swing Trade Analysis | Close: ₹{row['Close']} | RSI: {row['RSI']} | ATR: ₹{round(df_chart.iloc[-1]['ATR'], 2)}"
    
    fig.update_layout(
        title=title_text,
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=60, b=20),
        plot_bgcolor="#111111",
        paper_bgcolor="#111111"
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    
    return fig

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
                        st.markdown(f"**TGT 1:** ₹{row['Target_1']} | **TGT 2:** ₹{row['Target_2']}")
                        st.markdown(f"**R:R Ratio:** {row['R:R']}x (based on TGT 2)")
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
                            
                    st.markdown("---")
                    if st.button(f"📊 View Chart for {row['Symbol']}", key=f"chart_btn_{row['Symbol']}"):
                        try:
                            from core.swing_manager import get_data, add_indicators
                            # Use the cached 300 days but display the last 90 days
                            df_chart = get_data(row['Symbol'], days=300)
                            df_chart = add_indicators(df_chart).tail(90)
                            fig = create_swing_chart(row['Symbol'], row, df_chart)
                            st.plotly_chart(fig, use_container_width=True)
                        except Exception as e:
                            st.error(f"Failed to load chart: {e}")
                            
            # Telegram Bot Integration for A+ and A Stocks
            aplus_picks = results[results['Score'] >= 8]
            if not aplus_picks.empty:
                st.markdown("---")
                if st.button("📲 Generate & Send A+/A Picks via Telegram Copilot"):
                    with st.spinner("Copilot is drafting the message..."):
                        # Generate and send chart and message for each stock
                        from core.swing_manager import get_data, add_indicators
                        
                        success_count = 0
                        for _, p in aplus_picks.iterrows():
                            try:
                                # Generate single-stock message
                                single_data = [p.to_dict()]
                                draft = copilot.draft_swing_message(single_data)
                                
                                # Generate chart
                                df_chart = get_data(p['Symbol'], days=300)
                                df_chart = add_indicators(df_chart).tail(90)
                                fig = create_swing_chart(p['Symbol'], p, df_chart)
                                
                                # Convert to image bytes
                                img_bytes = fig.to_image(format="png", engine="kaleido", width=1000, height=800)
                                
                                # Send photo with the AI message as the caption
                                notifier.send_photo(img_bytes, caption=draft)
                                success_count += 1
                                
                                # Show preview in UI
                                st.markdown(f"**Preview sent for {p['Symbol']}:**")
                                st.info(draft)
                                
                            except Exception as e:
                                st.error(f"Failed to generate and send alert for {p['Symbol']}: {e}")
                                
                        if success_count > 0:
                            st.success(f"✅ {success_count} Telegram alerts and charts sent successfully!")
        else:
            st.info("No stocks matched the Top Pick criteria (Score >= 8) today.")
