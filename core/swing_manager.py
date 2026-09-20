import os
import datetime
import pandas as pd
import numpy as np

# Patch os.makedirs to prevent FileExistsError from jugaad-data caching on Windows
_orig_makedirs = os.makedirs
def _patched_makedirs(name, mode=0o777, exist_ok=True):
    return _orig_makedirs(name, mode, exist_ok=True)
os.makedirs = _patched_makedirs

from jugaad_data.nse import stock_df

def get_data(symbol: str, days: int = 300) -> pd.DataFrame:
    """Fetch historical stock data using jugaad-data."""
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days)
    try:
        df = stock_df(symbol, from_date=start_date, to_date=end_date, series="EQ")
        if df.empty:
            raise ValueError(f"No data returned for {symbol}")
        # jugaad_data returns newest first, so we reverse it to oldest first
        df = df.iloc[::-1].reset_index(drop=True)
        # Ensure correct types
        df['CLOSE'] = pd.to_numeric(df['CLOSE'])
        df['HIGH'] = pd.to_numeric(df['HIGH'])
        df['LOW'] = pd.to_numeric(df['LOW'])
        df['OPEN'] = pd.to_numeric(df['OPEN'])
        df['VOLUME'] = pd.to_numeric(df['VOLUME'] if 'VOLUME' in df.columns else df.get('TOTAL TRADED QUANTITY', 0))
        return df
    except Exception as e:
        raise Exception(f"Failed to fetch data for {symbol}: {e}")

def master_swing_scanner(symbols):
    all_results = []
    
    for symbol in symbols:
        try:
            df = get_data(symbol, days=300)
            
            # --- All Indicators ---
            # EMA
            df['EMA_9']  = df['CLOSE'].ewm(span=9, adjust=False).mean()
            df['EMA_21'] = df['CLOSE'].ewm(span=21, adjust=False).mean()
            df['EMA_50'] = df['CLOSE'].ewm(span=50, adjust=False).mean()
            df['EMA_200']= df['CLOSE'].ewm(span=200, adjust=False).mean()
            
            # RSI
            delta = df['CLOSE'].diff()
            gain  = delta.where(delta > 0, 0).rolling(14).mean()
            loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
            # To avoid division by zero
            rs = gain / loss.replace(0, np.nan)
            df['RSI'] = 100 - (100 / (1 + rs))
            df['RSI'] = df['RSI'].fillna(50)
            
            # MACD
            df['MACD']        = df['CLOSE'].ewm(span=12, adjust=False).mean() - df['CLOSE'].ewm(span=26, adjust=False).mean()
            df['MACD_Sig']    = df['MACD'].ewm(span=9, adjust=False).mean()
            df['MACD_Hist']   = df['MACD'] - df['MACD_Sig']
            
            # Bollinger
            df['BB_Mid']   = df['CLOSE'].rolling(20).mean()
            df['BB_Std']   = df['CLOSE'].rolling(20).std()
            df['BB_Upper'] = df['BB_Mid'] + 2 * df['BB_Std']
            df['BB_Lower'] = df['BB_Mid'] - 2 * df['BB_Std']
            
            # Volume
            df['Vol_MA']  = df['VOLUME'].rolling(20).mean()
            df['Vol_Rat'] = df['VOLUME'] / df['Vol_MA'].replace(0, np.nan)
            df['Vol_Rat'] = df['Vol_Rat'].fillna(0)
            
            # ATR
            df['TR']  = np.maximum(df['HIGH']-df['LOW'],
                        np.maximum(abs(df['HIGH']-df['CLOSE'].shift(1)),
                                   abs(df['LOW']-df['CLOSE'].shift(1))))
            df['ATR'] = df['TR'].rolling(14).mean()
            
            # 52 Week High/Low (assuming ~252 trading days)
            df['52W_High'] = df['HIGH'].rolling(252, min_periods=100).max()
            df['52W_Low']  = df['LOW'].rolling(252, min_periods=100).min()
            
            latest = df.iloc[-1]
            
            # === SCORING SYSTEM ===
            score   = 0
            signals = []
            
            # 1. Trend Score (0-4)
            if latest['EMA_9']  > latest['EMA_21']:  score+=1; signals.append("EMA9>21")
            if latest['EMA_21'] > latest['EMA_50']:  score+=1; signals.append("EMA21>50")
            if latest['CLOSE']  > latest['EMA_200']: score+=1; signals.append("Above EMA200")
            if latest['EMA_50'] > latest['EMA_200']: score+=1; signals.append("EMA50>200")
            
            # 2. Momentum Score (0-3)
            if 50 < latest['RSI'] < 65:  score+=2; signals.append(f"RSI={latest['RSI']:.0f}✅")
            elif latest['RSI'] < 35:     score+=3; signals.append(f"RSI={latest['RSI']:.0f}🔥")
            if latest['MACD'] > latest['MACD_Sig']:   score+=1; signals.append("MACD Bullish")
            if len(df) > 2 and latest['MACD_Hist'] > 0 and latest['MACD_Hist'] > df['MACD_Hist'].iloc[-2]:
                score+=1; signals.append("MACD Rising")
            
            # 3. Volume Score (0-2)
            if latest['Vol_Rat'] > 1.5: score+=2; signals.append(f"Vol={latest['Vol_Rat']:.1f}x🔥")
            elif latest['Vol_Rat'] > 1.2: score+=1; signals.append(f"Vol={latest['Vol_Rat']:.1f}x")
            
            # 4. Price Action Score (0-2)
            if not pd.isna(latest['52W_High']) and latest['52W_High'] > 0:
                from52high = ((latest['52W_High'] - latest['CLOSE']) / latest['52W_High']) * 100
            else:
                from52high = 100
                
            if not pd.isna(latest['52W_Low']) and latest['52W_Low'] > 0:
                from52low  = ((latest['CLOSE'] - latest['52W_Low'])  / latest['52W_Low'])  * 100
            else:
                from52low = 100
                
            if from52low < 20:   score+=1; signals.append("Near 52W Low")
            if from52high < 10:  score+=2; signals.append("Near 52W High🚀")
            
            # 5. Bollinger Score (0-2)
            bb_range = latest['BB_Upper'] - latest['BB_Lower']
            if not pd.isna(bb_range) and bb_range > 0:
                bb_pos = (latest['CLOSE'] - latest['BB_Lower']) / bb_range
                if bb_pos < 0.2:  score+=2; signals.append("BB Oversold🔥")
                elif bb_pos > 0.8: score+=1; signals.append("BB Upper")
            
            # Risk Reward
            stop   = latest['CLOSE'] - (2 * latest['ATR'])
            target = latest['CLOSE'] + (4 * latest['ATR'])
            risk   = latest['CLOSE'] - stop
            reward = target - latest['CLOSE']
            rr     = reward / risk if risk > 0 else 0
            
            # Grade
            if score >= 10:   grade = "A+ 🔥🔥🔥"
            elif score >= 8:  grade = "A  🔥🔥"
            elif score >= 6:  grade = "B+ 🔥"
            elif score >= 4:  grade = "B  ✅"
            else:             grade = "C  ⚠️"
            
            all_results.append({
                'Symbol'    : symbol,
                'Close'     : round(latest['CLOSE'], 2),
                'Score'     : score,
                'Grade'     : grade,
                'RSI'       : round(latest['RSI'], 1),
                'Vol_Ratio' : round(latest['Vol_Rat'], 2),
                'Stop_Loss' : round(stop, 2),
                'Target'    : round(target, 2),
                'R:R'       : round(rr, 2),
                'Signals'   : ' | '.join(signals[:4])
            })
            
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            all_results.append({
                'Symbol'    : symbol,
                'Close'     : 0,
                'Score'     : 0,
                'Grade'     : "Error",
                'RSI'       : 0,
                'Vol_Ratio' : 0,
                'Stop_Loss' : 0,
                'Target'    : 0,
                'R:R'       : 0,
                'Signals'   : str(e)[:30]
            })
    
    if not all_results:
        return pd.DataFrame()
        
    result_df = pd.DataFrame(all_results).sort_values('Score', ascending=False)
    return result_df

def calculate_risk_management(capital, entry, stop_loss, target):
    """Calculate risk management parameters for a trade."""
    risk_per_trade = 0.02  # 2% of capital
    
    risk_per_share   = entry - stop_loss
    if risk_per_share <= 0:
        return None
        
    reward_per_share = target - entry
    rr_ratio         = reward_per_share / risk_per_share
    
    # Position sizing
    max_loss    = capital * risk_per_trade
    qty         = int(max_loss / risk_per_share)
    invest_amt  = qty * entry
    
    return {
        'Capital': capital,
        'Entry': entry,
        'Stop_Loss': stop_loss,
        'Target': target,
        'Risk_Share': risk_per_share,
        'Reward_Share': reward_per_share,
        'RR_Ratio': rr_ratio,
        'Quantity': qty,
        'Invest_Amount': invest_amt,
        'Max_Loss': max_loss,
        'Max_Profit': qty * reward_per_share,
        'Status': "✅ GOOD TRADE (R:R >= 1:2)" if rr_ratio >= 2 else "❌ SKIP (R:R < 1:2)"
    }
