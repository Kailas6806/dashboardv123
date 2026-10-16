import datetime
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from analytics.db import TradeDB
from analytics.trade_journal import TradeJournal


class TestTradingJsonSerialization(unittest.TestCase):
    def test_json_export_serializes_database_time_values(self):
        journal = TradeJournal(journal_path="unused.json")
        journal.get_all_trades = lambda: [
            {"Entry Time": datetime.time(10, 30, 15)}
        ]

        exported = json.loads(journal.export_to_json())

        self.assertEqual("10:30:15", exported[0]["Entry Time"])

    def test_journal_saves_datetime_and_numpy_values(self):
        with tempfile.TemporaryDirectory() as directory:
            journal_path = os.path.join(directory, "journal.json")
            journal = TradeJournal(journal_path=journal_path)
            entry_time = datetime.datetime(2026, 10, 16, 10, 30)

            journal.record_trade(
                {"Index": "NIFTY", "Entry Time": entry_time, "Signal": "BUY CE"},
                {
                    "created_at": entry_time,
                    "quantity": np.int64(50),
                    "values": np.array([1, 2]),
                },
            )

            with open(journal_path, encoding="utf-8") as file:
                saved = json.load(file)
            self.assertEqual(entry_time.isoformat(), saved[0]["Entry Time"])
            self.assertEqual(entry_time.isoformat(), saved[0]["signal_metadata"]["created_at"])
            self.assertEqual(50, saved[0]["signal_metadata"]["quantity"])
            self.assertEqual([1, 2], saved[0]["signal_metadata"]["values"])

    def test_atomic_reservation_serializes_numpy_and_datetime_metadata(self):
        db = TradeDB.__new__(TradeDB)
        db._lock = threading.RLock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        connection = MagicMock()
        connection.cursor.return_value = cursor
        created_at = datetime.datetime(2026, 10, 16, 10, 30)

        with patch.object(db, "_get_connection", return_value=connection):
            trade_id = db.upsert_trade(
                {"Index": "NIFTY", "Signal": "BUY CE", "Strike": np.int64(25000)},
                {"created_at": created_at, "quantity": np.int64(50)},
                reject_if_open=True,
            )

        self.assertTrue(trade_id)
        insert_params = cursor.execute.call_args_list[-1].args[1]
        metadata = json.loads(insert_params[-3])
        self.assertEqual(created_at.isoformat(), metadata["created_at"])
        self.assertEqual(50, metadata["quantity"])
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
