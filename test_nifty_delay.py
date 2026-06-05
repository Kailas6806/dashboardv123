import time
import sys

# Add the current directory to sys.path so it can import from core.data_fetcher
sys.path.append('.')

from core.data_fetcher import NSEDataFetcher

def test_delay():
    print("Initializing NSEDataFetcher (this creates the session)...")
    fetcher = NSEDataFetcher()
    
    print("\nWarming up (first fetch usually takes longer due to session setup)...")
    start = time.time()
    data = fetcher.fetch_option_chain("NIFTY")
    end = time.time()
    
    if data:
        print(f"Warmup fetch successful. Time taken: {end - start:.4f} seconds")
    else:
        print(f"Warmup fetch failed. Time taken: {end - start:.4f} seconds")
        
    print("\nStarting 1-minute data fetch test...")
    print("Cache will be invalidated before each iteration to force network fetch.")
    print(f"{'Time':<12} | {'Latency':<10} | {'Spot Price':<12} | {'ATM Strike':<12} | {'CE LTP':<10} | {'PE LTP':<10}")
    print("-" * 75)
    
    delays = []
    start_time = time.time()
    
    # Run for 60 seconds
    while (time.time() - start_time) < 60:
        # Invalidate cache so it actually fetches from network
        fetcher.invalidate_cache("NIFTY")
        
        req_start = time.time()
        # Fetch data and get ATM prices directly using the helper method
        ce_ltp, pe_ltp, spot = fetcher.get_atm_prices("NIFTY")
        req_end = time.time()
        
        delay = req_end - req_start
        current_time = time.strftime("%H:%M:%S")
        
        if spot is not None:
            delays.append(delay)
            # Calculate ATM strike just for display purposes
            step = 50 # NIFTY step
            atm = round(spot / step) * step
            print(f"{current_time:<12} | {delay:.4f}s  | {spot:<12.2f} | {atm:<12} | {ce_ltp:<10.2f} | {pe_ltp:<10.2f}")
        else:
            print(f"{current_time:<12} | {delay:.4f}s  | FETCH FAILED")
            
        time.sleep(1.5) # Wait to respect minimum request interval
        
    if delays:
        avg_delay = sum(delays) / len(delays)
        print(f"\n--- Results ---")
        print(f"Total successful fetches: {len(delays)}")
        print(f"Average Delay: {avg_delay:.4f} seconds")
        print(f"Min Delay: {min(delays):.4f} seconds")
        print(f"Max Delay: {max(delays):.4f} seconds")

if __name__ == "__main__":
    test_delay()
