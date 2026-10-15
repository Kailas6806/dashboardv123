import unittest
from unittest.mock import patch

from core.websocket_manager import SmartWebSocketManager


class _FailingSocket:
    def __init__(self, *args, **kwargs):
        self.on_open = None
        self.on_data = None
        self.on_error = None
        self.on_close = None

    def connect(self):
        pass


class TestWebSocketReconnect(unittest.TestCase):
    def test_token_refresh_does_not_prevent_reconnect_cooldown(self):
        refresh_calls = []
        sleep_calls = []
        manager = SmartWebSocketManager(
            auth_token="old-auth",
            api_key="api-key",
            client_code="client",
            feed_token="old-feed",
            token_refresher=lambda: (refresh_calls.append(True) or ("new-auth", "new-feed")),
        )
        manager._is_running = True

        def sleep_and_stop(delay):
            sleep_calls.append(delay)
            if delay == 30:
                manager._is_running = False

        with (
            patch("core.websocket_manager.HAS_SMART_WS", True),
            patch("core.websocket_manager.SmartWebSocketV2", _FailingSocket),
            patch.object(SmartWebSocketManager, "is_market_hours", return_value=True),
            patch("core.websocket_manager.time.sleep", side_effect=sleep_and_stop),
        ):
            manager._run_connection()

        self.assertEqual(5, len(sleep_calls))
        self.assertEqual([5, 10, 15, 20, 30], sleep_calls)
        self.assertEqual(1, len(refresh_calls))
        self.assertEqual("new-auth", manager.auth_token)
        self.assertEqual("new-feed", manager.feed_token)


if __name__ == "__main__":
    unittest.main()
