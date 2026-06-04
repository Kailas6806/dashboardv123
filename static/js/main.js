function switchTab(tabId) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById(tabId).classList.add('active');
}

async function sendDailyReport() {
    if(!confirm('Send Daily Report manually?')) return;
    try {
        await fetch('/api/send_report', { method: 'POST' });
        alert('Report sent!');
    } catch(e) { console.error(e); }
}

async function resetIndex(idx) {
    if(!confirm(`Reset data and clear trade logs for ${idx}?`)) return;
    try {
        await fetch(`/api/reset/${idx}`, { method: 'POST' });
        pollData();
    } catch(e) { console.error(e); }
}

async function testAlert(idx) {
    try {
        await fetch(`/api/test_alert/${idx}`, { method: 'POST' });
        alert('Test alert triggered via Telegram.');
    } catch(e) { console.error(e); }
}

// Audio context for playing Beep
let lastSignals = { 'NIFTY': 'WAIT', 'BANKNIFTY': 'WAIT', 'FINNIFTY': 'WAIT' };

function playBeep() {
    const audio = new Audio('https://actions.google.com/sounds/v1/alarms/beep_short.ogg');
    audio.play().catch(e => console.log('Audio blocked by browser:', e));
}

async function pollData() {
    const indices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY'];
    let allOpenTrades = [];
    let indicesActive = new Set();
    
    for (let idx of indices) {
        try {
            const res = await fetch(`/api/refresh/${idx}`);
            const data = await res.json();
            if (data.error) continue;
            
            // Audio trigger on new signal
            if (data.signal !== 'WAIT' && data.signal !== lastSignals[idx]) {
                playBeep();
                lastSignals[idx] = data.signal;
            } else if (data.signal === 'WAIT') {
                lastSignals[idx] = 'WAIT';
            }

            // Header & Tracker Grid
            let progress = (data.idx_pnl / data.risk.daily_tgt) * 100;
            progress = Math.min(Math.max(progress, -100), 100);
            
            let html = `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 24px;">
                <h2 style="margin:0;">📈 ${idx} Dashboard</h2>
                <div style="display:flex; gap:12px;">
                    <button onclick="testAlert('${idx}')" style="background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.2);">📨 Test Alert</button>
                    <button onclick="resetIndex('${idx}')" class="danger">🔄 Reset Data</button>
                </div>
            </div>`;
            
            html += `<div class="grid tracker-grid">
                <div class="card"><div class="label">CAPITAL</div><div class="kpi" style="font-size:22px">₹${data.risk.capital.toLocaleString()}</div></div>
                <div class="card"><div class="label">TRADES TODAY</div><div class="kpi" style="font-size:22px">${data.closed_count}</div></div>
                <div class="card"><div class="label">NET P&L</div><div class="kpi ${data.idx_pnl >= 0 ? 'pnl-green' : 'pnl-red'}" style="font-size:22px">₹${data.idx_pnl.toLocaleString()}</div></div>
                <div class="card"><div class="label">PROGRESS (${progress.toFixed(1)}%)</div>
                    <div class="conf-bar-outer"><div class="conf-bar-inner ${data.idx_pnl >= 0 ? 'conf-bar-high' : 'conf-bar-low'}" style="width: ${Math.abs(progress)}%"></div></div>
                </div>
            </div>`;
            
            // KPI Grid
            html += `<div class="grid kpi-grid">
                <div class="card"><div class="label">Spot</div><div class="kpi">${data.spot}</div></div>
                <div class="card"><div class="label">ATM</div><div class="kpi">${data.atm}</div></div>
                <div class="card"><div class="label">PCR</div><div class="kpi">${data.pcr}</div></div>
                <div class="card"><div class="label">Bias</div><div class="kpi" style="font-size:22px">${data.bias}</div></div>
                <div class="card"><div class="label">Support 1 / 2</div><div class="kpi" style="font-size:18px;">${data.support} <br> <span style="font-size:13px;color:#9CA3AF">${data.secondary_support || 'N/A'}</span></div></div>
                <div class="card"><div class="label">Resistance 1 / 2</div><div class="kpi" style="font-size:18px;">${data.resistance} <br> <span style="font-size:13px;color:#9CA3AF">${data.secondary_resistance || 'N/A'}</span></div></div>
            </div>`;
            
            // Filters & Status
            let filters = data.filters;
            let sidewaysStr = filters.sideways_is ? `<div class="card" style="border:1px dashed #F59E0B; background:rgba(245,158,11,0.1);"><div class="label">⚖️ Market Condition</div><div style="color:#F59E0B; font-weight:800; font-size:18px;">${filters.sideways_strength}</div></div>` : '';
            if (sidewaysStr) html += `<div class="grid" style="grid-template-columns:1fr;">${sidewaysStr}</div>`;
            
            html += `<div class="grid filter-grid">
                <div class="card">
                    <div class="label">Market Status</div>
                    <div><span class="badge ${filters.in_window ? 'badge-ok' : 'badge-warning'}">${filters.in_window ? '✅ OPEN' : '❌ CLOSED'}</span></div>
                </div>
                <div class="card">
                    <div class="label">VWAP Proxy</div>
                    <div><span class="badge ${filters.spot_vs_vwap === 'ABOVE' ? 'badge-ok' : 'badge-warning'}">${filters.spot_vs_vwap} (${filters.vwap_proxy})</span></div>
                </div>
                <div class="card">
                    <div class="label">PCR Momentum</div>
                    <div><span class="badge ${filters.pcr_momentum === 'RISING' ? 'badge-ok' : (filters.pcr_momentum === 'FALLING' ? 'badge-warning' : 'badge-cooldown')}">${filters.pcr_momentum}</span></div>
                </div>
                <div class="card">
                    <div class="label">OI Active</div>
                    <div><span class="badge ${filters.oi_active ? 'badge-ok' : 'badge-warning'}">${filters.oi_active ? 'YES' : 'NO'}</span></div>
                </div>
                <div class="card">
                    <div class="label">CE OI Flow</div>
                    <div style="color:#EF4444; font-weight:800; font-size:18px;">${filters.total_ce_delta.toLocaleString()}</div>
                </div>
                <div class="card">
                    <div class="label">PE OI Flow</div>
                    <div style="color:#10B981; font-weight:800; font-size:18px;">${filters.total_pe_delta.toLocaleString()}</div>
                </div>
            </div>`;
            
            // Risk Management Box
            let risk = data.risk;
            html += `<div class="card" style="border-left: 5px solid #8B5CF6; background:linear-gradient(135deg, rgba(76,29,149,0.3), rgba(30,41,59,0.5))">
                <div class="label">🛡️ Risk Management</div>
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
                    <div>
                        <div style="color:#E2E8F0; margin-bottom:4px">Consecutive Losses: <b style="color:#F87171">${risk.daily_losses} / ${risk.max_daily_losses}</b></div>
                        <div style="color:#E2E8F0;">Estimated ATR SL: <b style="color:#F59E0B">₹${risk.atr_sl || 'N/A'}</b></div>
                    </div>
                    <div>
                        ${risk.cooldown_remaining > 0 ? `<span class="badge badge-cooldown" style="font-size:14px; padding:8px 16px;">⏳ Cooldown: ${risk.cooldown_remaining}s</span>` : '<span class="badge badge-ok" style="font-size:14px; padding:8px 16px;">✅ Ready to Trade</span>'}
                    </div>
                </div>
            </div>`;
            
            // Signal Card
            let sigClass = 'signal-gray';
            if (data.signal === 'BUY CE') sigClass = 'signal-green';
            else if (data.signal === 'BUY PE') sigClass = 'signal-red';
            else if (data.signal.includes('SIDEWAYS')) sigClass = 'signal-yellow';
            
            html += `<div class="card ${sigClass}">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
                    <h2 style="margin:0; font-size:32px;">${data.signal} <span class="badge ${data.confidence === 'HIGH' ? 'badge-ok' : 'badge-warning'}">${data.confidence}</span></h2>
                    <div>
                        <span style="color:#94A3B8; font-size:12px; margin-right:8px; font-weight:700;">BUFFER:</span>
                        ${data.signal_buffer && data.signal_buffer.length > 0 ? 
                          data.signal_buffer.map(s => `<span class="badge" style="background:rgba(255,255,255,0.1); margin-right:4px">${s}</span>`).join('') 
                          : '<span class="badge">WAIT</span>'}
                    </div>
                </div>
                
                <div class="conf-bar-outer" style="height:12px; margin: 16px 0;">
                    <div class="conf-bar-inner ${data.conf_score > 60 ? 'conf-bar-high' : (data.conf_score > 20 ? 'conf-bar-medium' : 'conf-bar-low')}" style="width: ${data.conf_score}%"></div>
                </div>
                
                <div style="display:flex; justify-content:space-between; font-size:13px;">
                    <div>Score: <b style="font-size:16px;">${data.conf_score}/100</b></div>
                    <div style="color:#94A3B8;">Filter Reason: <b style="color:#CBD5E1">${data.filter_reason || 'N/A'}</b></div>
                </div>
                
                ${data.conf_score <= 20 && data.signal !== 'WAIT' ? '<div style="color:#FCA5A5; margin-top:8px; font-weight:700;">⚠️ Score too low for entry (Minimum: 21)</div>' : ''}
                ${data.trap !== 'NONE' ? `<div class="trap-alert" style="margin-top:16px;">🚨 ${data.trap} DETECTED!</div>` : ''}
                ${data.oi_unusual_activity ? `<div class="trap-alert" style="margin-top:16px;">🚨 UNUSUAL OI ACTIVITY - HOLD OFF</div>` : ''}
            </div>`;
            
            // Plotly Charts Container
            html += `<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(400px, 1fr))">
                        <div class="card"><div id="chart-oi-${idx}"></div></div>
                        <div class="card"><div id="chart-delta-${idx}"></div></div>
                     </div>`;
                     
            // Option Chain Table
            let oc = data.option_chain || [];
            let ocHtml = `<div class="card"><h2>📊 Option Chain</h2><div class="table-wrapper"><table>
                <thead><tr><th>CE OI</th><th>CE LTP</th><th>Strike</th><th>PE LTP</th><th>PE OI</th></tr></thead><tbody>`;
            
            let strikes = [];
            let ce_oi = [];
            let pe_oi = [];
            let ce_delta = [];
            let pe_delta = [];

            for (let row of oc) {
                strikes.push(row.Strike.toString());
                ce_oi.push(row['CE OI']);
                pe_oi.push(row['PE OI']);
                ce_delta.push(row['CE OI Δ'] || 0);
                pe_delta.push(row['PE OI Δ'] || 0);

                let isAtm = row.Strike === data.atm;
                ocHtml += `<tr style="${isAtm ? 'background:rgba(252, 211, 77, 0.1);' : ''}">
                    <td style="color:#F87171; font-weight:600;">${row['CE OI'].toLocaleString()}</td>
                    <td>₹${row['CE LTP']}</td>
                    <td style="font-weight:800; font-size:15px; ${isAtm ? 'color:#FCD34D' : ''}">${row.Strike} ${isAtm ? '🎯' : ''}</td>
                    <td>₹${row['PE LTP']}</td>
                    <td style="color:#34D399; font-weight:600;">${row['PE OI'].toLocaleString()}</td>
                </tr>`;
            }
            ocHtml += `</tbody></table></div></div>`;
            html += ocHtml;
            
            // Trade History
            if (data.trade_log) {
                const openTrades = data.trade_log.filter(t => t.Status === 'OPEN');
                allOpenTrades.push(...openTrades);
                if (openTrades.length > 0) indicesActive.add(idx);
                
                const closedTrades = data.trade_log.filter(t => t.Status === 'CLOSED');
                if (closedTrades.length > 0) {
                    html += `<div class="card"><h2>📋 Trade History</h2><div class="table-wrapper"><table>
                    <thead><tr><th>Entry Time</th><th>Signal</th><th>Strike</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Result</th></tr></thead><tbody>`;
                    for (let t of closedTrades) {
                        html += `<tr>
                            <td style="color:#94A3B8">${t['Entry Time']}</td>
                            <td style="font-weight:700">${t.Signal}</td>
                            <td>${t.Strike}</td>
                            <td>₹${t['Entry Price']}</td>
                            <td>₹${t['Exit Price']}</td>
                            <td class="${t['Actual P&L ₹'] >= 0 ? 'pnl-green' : 'pnl-red'}">₹${t['Actual P&L ₹']}</td>
                            <td><span class="badge ${t.Result.includes('PROFIT') ? 'badge-ok' : (t.Result.includes('LOSS') ? 'badge-warning' : 'badge-cooldown')}">${t.Result}</span></td>
                        </tr>`;
                    }
                    html += `</tbody></table></div></div>`;
                }
            }
            
            document.getElementById(`${idx}-content`).innerHTML = html;

            // Render Plotly charts with premium dark theme
            const layoutCommon = {
                paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
                font: {color: '#94A3B8', family: 'Inter'}, margin: {t:40, l:40, r:20, b:40},
                xaxis: {gridcolor: 'rgba(255,255,255,0.05)'}, yaxis: {gridcolor: 'rgba(255,255,255,0.05)'},
                legend: {orientation: 'h', y: -0.2}
            };
            
            Plotly.newPlot(`chart-oi-${idx}`, [
                {x: strikes, y: ce_oi, type: 'bar', name: 'CE OI', marker: {color: 'rgba(239, 68, 68, 0.8)'}},
                {x: strikes, y: pe_oi, type: 'bar', name: 'PE OI', marker: {color: 'rgba(16, 185, 129, 0.8)'}}
            ], { ...layoutCommon, title: {text: 'CE vs PE Open Interest', font: {color: '#F8FAFC', size: 16}} }, {displayModeBar: false});

            Plotly.newPlot(`chart-delta-${idx}`, [
                {x: strikes, y: ce_delta, type: 'bar', name: 'CE Δ', marker: {color: 'rgba(248, 113, 113, 0.8)'}},
                {x: strikes, y: pe_delta, type: 'bar', name: 'PE Δ', marker: {color: 'rgba(52, 211, 153, 0.8)'}}
            ], { ...layoutCommon, title: {text: 'CE vs PE OI Change', font: {color: '#F8FAFC', size: 16}} }, {displayModeBar: false});

        } catch (e) {
            console.error(e);
        }
    }
    
    // Render Open Trades Tab
    let openTradesHtml = '';
    
    // Top KPI for open trades
    openTradesHtml += `<div class="grid" style="grid-template-columns: 1fr 1fr; margin-bottom:24px;">
        <div class="card"><div class="label">Open Trades</div><div class="kpi" style="color:#34D399">${allOpenTrades.length}</div></div>
        <div class="card"><div class="label">Active Indices</div><div class="kpi">${Array.from(indicesActive).join(' · ') || 'NONE'}</div></div>
    </div>`;

    if (allOpenTrades.length === 0) {
        openTradesHtml += `
        <div class="empty-state">
            <div class="empty-state-icon">📭</div>
            <div class="empty-state-text">No open trades right now</div>
            <div style="color:#64748B; margin-top:8px;">Waiting for a signal...</div>
        </div>`;
    } else {
        openTradesHtml += allOpenTrades.map(t => {
            let ev = parseFloat(t['Entry Price']);
            let lv = parseFloat(t['Live Price']);
            let qty = parseInt(t.Qty);
            let upl = (lv - ev) * qty;
            if (t.Signal.includes('PE')) upl = (ev - lv) * qty; // Quick inversion for PE logic visual only if needed, backend handles logic. Actually backend PnL logic applies.
            
            // Re-calculate UPL generically based on live price direction. If CE, up is good. If PE, down is good.
            let dir = t.Signal.includes('CE') ? 1 : -1;
            upl = Math.round((lv - ev) * dir * qty);
            
            let uc = upl >= 0 ? '#34D399' : '#F87171';
            let uarrow = upl >= 0 ? '▲' : '▼';
            
            return `
            <div class="card ${t.Signal.includes('CE') ? 'signal-green' : 'signal-red'}">
                <div style="display:flex; justify-content:space-between; align-items:center; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom:16px;">
                    <div>
                        <span class="badge" style="background:#6366F1; margin-right:8px">${t.Index}</span>
                        <span style="font-size:24px; font-weight:800; margin-right:8px">${t.Signal}</span>
                        <span style="color:#94A3B8">Strike: <b style="color:white">${t.Strike}</b></span>
                    </div>
                    <div style="color:${uc}; font-size:28px; font-weight:800; text-shadow: 0 0 15px ${uc}40;">
                        ${uarrow} ₹${Math.abs(upl).toLocaleString()}
                    </div>
                </div>
                
                <div class="trade-detail-grid">
                    <div><div class="label">Entry Price</div><div style="font-weight:700; font-size:16px;">₹${ev}</div></div>
                    <div><div class="label">Live Price</div><div style="font-weight:700; font-size:16px; color:${uc}">₹${lv}</div></div>
                    <div><div class="label">Stop Loss</div><div style="font-weight:700; font-size:16px; color:#F87171">₹${t['Stop Loss']}</div></div>
                    <div><div class="label">Target</div><div style="font-weight:700; font-size:16px; color:#34D399">₹${t.Target}</div></div>
                    <div><div class="label">Qty</div><div style="font-weight:700; font-size:16px;">${qty}</div></div>
                    <div><div class="label">Max Loss</div><div style="font-weight:700; font-size:16px; color:#F87171">₹${t['Max Loss ₹']}</div></div>
                    <div><div class="label">Target P&L</div><div style="font-weight:700; font-size:16px; color:#34D399">₹${t['Target P&L ₹']}</div></div>
                </div>
                
                <div style="margin-top:20px; display:flex; justify-content:space-between; align-items:center;">
                    <div style="color:#64748B; font-size:13px; font-weight:600;">Entered: ${t['Entry Time']}</div>
                    <button onclick="closeTrade('${t.Index}', '${t['Entry Time']}', '${t.Strike}', '${t.Signal}', ${lv})" class="danger">❌ Close Position</button>
                </div>
            </div>`;
        }).join('');
    }
    document.getElementById('open-trades-container').innerHTML = openTradesHtml;
    
    // Poll Analytics
    try {
        const resA = await fetch('/api/analytics');
        const stats = await resA.json();
        
        // Build KPIs
        let aHtml = `<div class="grid kpi-grid">
            <div class="card"><div class="label">Total Trades</div><div class="kpi">${stats.total_trades || 0}</div></div>
            <div class="card"><div class="label">Win Rate</div><div class="kpi">${stats.win_rate ? stats.win_rate.toFixed(1) : 0}%</div></div>
            <div class="card"><div class="label">Net P&L</div><div class="kpi ${stats.total_pnl >= 0 ? 'pnl-green' : 'pnl-red'}">₹${(stats.total_pnl || 0).toLocaleString()}</div></div>
            <div class="card"><div class="label">Max Drawdown</div><div class="kpi" style="color:#EF4444">₹${stats.max_drawdown || 0}</div></div>
            <div class="card"><div class="label">Risk/Reward</div><div class="kpi">${stats.risk_reward_ratio ? stats.risk_reward_ratio.toFixed(2) : 0}</div></div>
        </div>`;
        
        // Add chart containers
        aHtml += `<div class="card" style="margin-top:24px;"><h2>Cumulative P&L</h2><div id="chart-cum-pnl" style="height:350px;"></div></div>`;
        aHtml += `<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(400px, 1fr))">
                    <div class="card"><h2>P&L by Index</h2><div id="chart-index-pnl" style="height:300px;"></div></div>
                    <div class="card"><h2>Performance by Hour</h2><div id="chart-hour-pnl" style="height:300px;"></div></div>
                  </div>`;
        aHtml += `<div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(400px, 1fr))">
                    <div class="card"><h2>Win / Loss Distribution</h2><div id="chart-win-loss" style="height:300px;"></div></div>
                    <div class="card"><h2>Signal Type Performance</h2><div id="signal-cards-container"></div></div>
                  </div>`;
        
        document.getElementById('analytics-content').innerHTML = aHtml;

        // Draw Plotly Charts if we have trades
        if(stats.all_trades && stats.all_trades.length > 0) {
            const layoutCommon = {
                paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
                font: {color: '#94A3B8', family: 'Inter'}, margin: {t:20, l:40, r:20, b:40},
                xaxis: {gridcolor: 'rgba(255,255,255,0.05)'}, yaxis: {gridcolor: 'rgba(255,255,255,0.05)'},
                showlegend: false
            };

            // 1. Cumulative P&L
            let cumPnl = 0;
            let xCum = [];
            let yCum = [];
            let colorsCum = [];
            stats.all_trades.forEach((t, i) => {
                cumPnl += (parseFloat(t['Actual P&L ₹']) || 0);
                xCum.push(t['Entry Time'].substring(0, 16));
                yCum.push(cumPnl);
                colorsCum.push(cumPnl >= 0 ? '#10B981' : '#EF4444');
            });
            Plotly.newPlot('chart-cum-pnl', [{
                x: xCum, y: yCum, type: 'scatter', mode: 'lines+markers',
                line: {color: cumPnl >= 0 ? '#10B981' : '#EF4444', width: 2},
                marker: {color: colorsCum, size: 6}
            }], layoutCommon, {displayModeBar: false});

            // 2. P&L By Index
            if (stats.by_index) {
                let idxs = Object.keys(stats.by_index);
                let wins = idxs.map(i => stats.by_index[i].wins);
                let losses = idxs.map(i => stats.by_index[i].losses);
                Plotly.newPlot('chart-index-pnl', [
                    {x: idxs, y: wins, type: 'bar', name: 'Wins', marker: {color: '#10B981'}},
                    {x: idxs, y: losses, type: 'bar', name: 'Losses', marker: {color: '#EF4444'}}
                ], {...layoutCommon, barmode: 'group', showlegend: true, legend: {orientation: 'h', y: -0.2}}, {displayModeBar: false});
            }

            // 3. P&L by Hour
            if (stats.by_hour) {
                let hrs = Object.keys(stats.by_hour).sort((a,b)=>parseInt(a)-parseInt(b));
                let hrLabels = hrs.map(h => `${h.padStart(2,'0')}:00`);
                let hrPnls = hrs.map(h => stats.by_hour[h].pnl);
                let hrColors = hrPnls.map(p => p >= 0 ? '#10B981' : '#EF4444');
                Plotly.newPlot('chart-hour-pnl', [{
                    x: hrLabels, y: hrPnls, type: 'bar', marker: {color: hrColors}
                }], layoutCommon, {displayModeBar: false});
            }

            // 4. Win/Loss Pie
            Plotly.newPlot('chart-win-loss', [{
                values: [stats.wins, stats.losses], labels: ['Wins', 'Losses'],
                type: 'pie', hole: 0.45, marker: {colors: ['#10B981', '#EF4444']}
            }], {...layoutCommon, showlegend: true, legend: {orientation: 'h', y: -0.2}}, {displayModeBar: false});
            
            // 5. Signal Types
            if (stats.by_signal_type) {
                let sigHtml = '';
                for (const [sigName, s] of Object.entries(stats.by_signal_type)) {
                    let wr = s.trades > 0 ? (s.wins / s.trades * 100).toFixed(1) : 0;
                    sigHtml += `<div style="background:rgba(255,255,255,0.05); padding:16px; border-radius:12px; margin-bottom:12px; display:flex; justify-content:space-between;">
                        <div><div class="label" style="color:white; font-size:14px;">${sigName}</div>
                        <div style="color:#94A3B8; font-size:12px; margin-top:4px;">${s.trades} trades · ${wr}% WR</div></div>
                        <div style="font-size:20px; font-weight:700; color:${s.pnl >= 0 ? '#10B981' : '#EF4444'}">₹${s.pnl.toLocaleString()}</div>
                    </div>`;
                }
                document.getElementById('signal-cards-container').innerHTML = sigHtml;
            }
        }
    } catch (e) {
        console.error(e);
    }
}

async function closeTrade(idx, entryTime, strike, signal, livePrice) {
    if (!confirm(`Close ${idx} ${signal} position at market price?`)) return;
    
    await fetch('/api/close_trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idx, entryTime, strike, signal, livePrice })
    });
    pollData();
}

setInterval(pollData, 3000);
pollData();
