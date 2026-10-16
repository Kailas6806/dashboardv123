import unittest
from unittest.mock import patch

from core.websocket_manager import SmartWebSocketManager, SmartWebSocketV2


class _FailingSocket:
    def __init__(self, *args, **kwargs):
        self.on_open = None
        self.on_data = None
        self.on_error = None
        self.on_close = None

    def connect(self):
        pass


class TestWebSocketReconnect(unittest.TestCase):
    def test_manager_disables_sdk_owned_retries(self):
        manager = SmartWebSocketManager("auth", "api", "client", "feed")

        with patch("core.websocket_manager.SmartWebSocketV2") as socket_class:
            socket = manager._new_socket()

        self.assertIs(socket, socket_class.return_value)
        self.assertEqual(0, socket_class.call_args.kwargs["max_retry_attempt"])

    def test_sdk_close_callback_accepts_websocket_client_close_details(self):
        socket = SmartWebSocketV2.__new__(SmartWebSocketV2)
        socket.on_close = lambda *details: setattr(socket, "close_details", details)

        socket._on_close("socket-app", 1000, "closed")

        self.assertEqual(("socket-app", 1000, "closed"), socket.close_details)

    def test_sdk_error_callback_preserves_transport_error_without_recursive_retry(self):
        socket = SmartWebSocketV2.__new__(SmartWebSocketV2)
        socket.RESUBSCRIBE_FLAG = False
        socket.on_error = lambda *details: setattr(socket, "error_details", details)
        socket.close_connection = lambda: self.fail("SDK must not close/retry recursively")
        socket.connect = lambda: self.fail("SDK must leave reconnect ownership to manager")
        transport_error = ConnectionError("server rejected websocket handshake")

        socket._on_error("socket-app", transport_error)

        self.assertTrue(socket.RESUBSCRIBE_FLAG)
        self.assertEqual(("socket-app", transport_error), socket.error_details)

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
