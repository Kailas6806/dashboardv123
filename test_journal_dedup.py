"""Test for trade journal dedup fix."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

# Use a temp directory to isolate from existing CSVs
orig_cwd = os.getcwd()
test_dir = tempfile.mkdtemp(prefix="v12_test_")
os.chdir(test_dir)

from analytics.trade_journal import TradeJournal

test_file = os.path.join(test_dir, "_test_journal.json")

def cleanup():
    if os.path.exists(test_file):
        os.remove(test_file)

def test_record_dedup():
    """Test that record_trade() doesn't create duplicates."""
    cleanup()
    j = TradeJournal(journal_path=test_file)
    
    trade = {
        "Entry Time": "10:26:31 AM",
        "Index": "BANKNIFTY",
        "Signal": "BUY PE",
        "Strike": 54900,
        "Entry Price": 233.75,
        "Status": "OPEN",
        "Result": "OPEN",
    }
    
    ids = []
    for i in range(6):
        tid = j.record_trade(trade, {"pcr": 0.75})
        ids.append(tid)
    
    assert len(j.trades) == 1, f"FAIL: Expected 1 trade, got {len(j.trades)}"
    assert len(set(ids)) == 1, f"FAIL: Expected same ID, got {set(ids)}"
    print(f"  PASS: test_record_dedup -- 6 calls -> {len(j.trades)} entry")
    cleanup()

def test_record_dedup_float_strike():
    """Test dedup works even when strike is float vs int."""
    cleanup()
    j = TradeJournal(journal_path=test_file)
    
    trade_int = {"Entry Time": "10:26:31 AM", "Index": "BANKNIFTY", "Signal": "BUY PE", "Strike": 54900}
    trade_float = {"Entry Time": "10:26:31 AM", "Index": "BANKNIFTY", "Signal": "BUY PE", "Strike": 54900.0}
    trade_str = {"Entry Time": "10:26:31 AM", "Index": "BANKNIFTY", "Signal": "BUY PE", "Strike": "54900.0"}
    
    j.record_trade(trade_int)
    j.record_trade(trade_float)
    j.record_trade(trade_str)
    
    assert len(j.trades) == 1, f"FAIL: Expected 1 trade, got {len(j.trades)}"
    print(f"  PASS: test_record_dedup_float_strike -- int/float/str strike -> {len(j.trades)} entry")
    cleanup()

def test_load_dedup():
    """Test that _load() cleans existing duplicates."""
    cleanup()
    
    dupes = []
    for i in range(6):
        dupes.append({
            "trade_id": f"BANKNIFTY_20260525_10263{i}",
            "Entry Time": "10:26:31 AM",
            "Index": "BANKNIFTY",
            "Signal": "BUY PE",
            "Strike": 54900.0 if i % 2 == 0 else 54900,  # mix float/int
            "Entry Price": 233.75,
            "Status": "CLOSED" if i == 5 else "OPEN",
            "Result": "LOSS" if i == 5 else "OPEN",
            "Actual P&L": -1015.5 if i == 5 else None,
            "recorded_at": "2026-05-25T10:26:31+05:30",
        })
    dupes.append({
        "trade_id": "FINNIFTY_20260525_102628",
        "Entry Time": "10:26:28 AM",
        "Index": "FINNIFTY",
        "Signal": "BUY PE",
        "Strike": 25900,
        "Status": "CLOSED",
        "recorded_at": "2026-05-25T10:26:28+05:30",
    })
    
    with open(test_file, "w") as f:
        json.dump(dupes, f)
    
    j = TradeJournal(journal_path=test_file)
    
    assert len(j.trades) == 2, f"FAIL: Expected 2 trades after dedup, got {len(j.trades)}"
    bn = [t for t in j.trades if t["Index"] == "BANKNIFTY"][0]
    assert bn["Status"] == "CLOSED", f"FAIL: Expected CLOSED kept, got {bn['Status']}"
    
    print(f"  PASS: test_load_dedup -- 7 entries (6 dupes + 1 unique) -> {len(j.trades)} entries")
    cleanup()

def test_different_trades_not_deduped():
    """Test that genuinely different trades are NOT removed."""
    cleanup()
    j = TradeJournal(journal_path=test_file)
    
    trade1 = {"Entry Time": "10:26:31 AM", "Index": "BANKNIFTY", "Signal": "BUY PE", "Strike": 54900}
    trade2 = {"Entry Time": "10:26:31 AM", "Index": "BANKNIFTY", "Signal": "BUY CE", "Strike": 54900}
    trade3 = {"Entry Time": "11:00:00 AM", "Index": "BANKNIFTY", "Signal": "BUY PE", "Strike": 54900}
    trade4 = {"Entry Time": "10:26:31 AM", "Index": "NIFTY",     "Signal": "BUY PE", "Strike": 23950}
    
    j.record_trade(trade1)
    j.record_trade(trade2)
    j.record_trade(trade3)
    j.record_trade(trade4)
    
    assert len(j.trades) == 4, f"FAIL: Expected 4 unique trades, got {len(j.trades)}"
    print(f"  PASS: test_different_trades_not_deduped -- 4 unique trades -> {len(j.trades)} entries")
    cleanup()

def test_update_with_float_strike():
    """Test that update_trade works with float strike in existing data."""
    cleanup()
    
    # Simulate a journal with float strike (from CSV import)
    data = [{
        "trade_id": "BN_123",
        "Entry Time": "10:26:31 AM",
        "Index": "BANKNIFTY",
        "Signal": "BUY PE",
        "Strike": 54900.0,
        "Status": "OPEN",
        "recorded_at": "2026-05-25T10:26:31+05:30",
    }]
    with open(test_file, "w") as f:
        json.dump(data, f)
    
    j = TradeJournal(journal_path=test_file)
    
    # Update using int strike
    updated = j.update_trade("", {"Status": "CLOSED", "Result": "WIN"}, {
        "Index": "BANKNIFTY", "Entry Time": "10:26:31 AM", "Strike": 54900, "Signal": "BUY PE"
    })
    
    assert updated, "FAIL: update_trade should have found the entry"
    assert j.trades[0]["Status"] == "CLOSED", f"FAIL: Status should be CLOSED"
    print(f"  PASS: test_update_with_float_strike -- update matched float strike with int")
    cleanup()

if __name__ == "__main__":
    print("=" * 50)
    print("Trade Journal Dedup Tests")
    print("=" * 50)
    passed = 0
    failed = 0
    tests = [
        test_record_dedup,
        test_record_dedup_float_strike,
        test_load_dedup,
        test_different_trades_not_deduped,
        test_update_with_float_strike,
    ]
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {test.__name__} -- {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {test.__name__} -- {e}")
            failed += 1
    
    os.chdir(orig_cwd)
    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED")
    print("=" * 50)
    sys.exit(1 if failed else 0)
