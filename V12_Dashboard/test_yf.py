import sys
sys.path.append(r'd:\KD\.venv\Lib\site-packages')
import yfinance as yf

try:
    nifty = yf.Ticker("^NSEI")
    print("Options dates:", nifty.options)
    if nifty.options:
        opt = nifty.option_chain(nifty.options[0])
        print("Calls:", len(opt.calls))
        print("Puts:", len(opt.puts))
except Exception as e:
    print("Exception:", e)
