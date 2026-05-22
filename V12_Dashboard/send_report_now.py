"""
Utility script to send the daily P&L report immediately (e.g., after market close).
It mimics the logic in app.py's `send_daily_pnl_report` function.
"""
import datetime
import pandas as pd

from config import INDEX_CONFIG, IST
from analytics.trade_journal import TradeJournal
from notifications.telegram import TelegramNotifier

def build_report():
    now = datetime.datetime.now(IST)
    current_date = now.strftime('%Y-%m-%d')
    report_lines = [f"📊 *DAILY P&L REPORT — {current_date}*\n"]
    total_pnl = total_trades = wins = losses = 0

    journal = TradeJournal()
    for idx in INDEX_CONFIG:
        # Load trades for this index from the journal
        trades = [t for t in journal.get_all_trades() if t.get('Index') == idx]
        if not trades:
            continue
        df = pd.DataFrame(trades)
        closed = df[df['Status'] == 'CLOSED'] if not df.empty else pd.DataFrame()
        if closed.empty:
            continue
        pnl_series = closed['Actual P&L ₹'].apply(pd.to_numeric, errors='coerce')
        idx_pnl = pnl_series.sum()
        idx_trades = len(closed)
        idx_wins = (pnl_series > 0).sum()
        idx_losses = (pnl_series <= 0).sum()
        total_pnl += idx_pnl
        total_trades += idx_trades
        wins += idx_wins
        losses += idx_losses
        emoji = '🟢' if idx_pnl >= 0 else '🔴'
        report_lines.append(f"{emoji} *{idx}*: ₹{idx_pnl:,.0f} ({idx_wins}W/{idx_losses}L)")

    report_lines.append(f"\n📈 *TOTAL TRADES*: {total_trades} ({wins}W / {losses}L)")
    final_emoji = '🟢' if total_pnl >= 0 else '🔴'
    report_lines.append(f"{final_emoji} *NET P&L*: ₹{total_pnl:,.0f}")
    return report_lines

def main():
    notifier = TelegramNotifier()
    lines = build_report()
    notifier.send_daily_report(lines)
    print('Daily report sent via Telegram (or logged if not configured).')

if __name__ == '__main__':
    main()
