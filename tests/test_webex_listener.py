"""Unit tests for Webex ChatOps command routing."""

from unittest.mock import patch

import webex_listener


class TestHandleCommand:
    @patch.object(webex_listener, "send_webex_reply")
    def test_ping_with_mention(self, mock_reply):
        webex_listener.handle_command("Hermes /ping")
        mock_reply.assert_called_once()
        assert "Pong" in mock_reply.call_args[0][0]

    @patch.object(webex_listener, "send_webex_reply")
    def test_ping_direct(self, mock_reply):
        webex_listener.handle_command("/ping")
        mock_reply.assert_called_once()
        assert "Pong" in mock_reply.call_args[0][0]

    @patch.object(webex_listener, "send_webex_reply")
    def test_help(self, mock_reply):
        webex_listener.handle_command("/help")
        mock_reply.assert_called_once()
        assert "/ping" in mock_reply.call_args[0][0]

    @patch.object(webex_listener, "send_webex_reply")
    def test_unknown_command(self, mock_reply):
        webex_listener.handle_command("/foobar")
        mock_reply.assert_called_once()
        assert "Unknown command" in mock_reply.call_args[0][0]

    @patch.object(webex_listener, "send_webex_reply")
    def test_no_slash_ignored(self, mock_reply):
        webex_listener.handle_command("Ping")
        mock_reply.assert_not_called()

    @patch.object(webex_listener, "run_script")
    @patch.object(webex_listener, "send_webex_reply")
    def test_pnl_runs_notify_script(self, mock_reply, mock_run):
        webex_listener.handle_command("/pnl")
        mock_reply.assert_called_once()
        mock_run.assert_called_once_with(["python", "notify_webex.py", "pnl"])


class TestWebhookRoute:
    def test_health_endpoint(self):
        client = webex_listener.app.test_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json["status"] == "healthy"

    @patch.object(webex_listener, "handle_command")
    @patch.object(webex_listener.requests, "get")
    def test_webhook_fetches_message_and_routes_command(
        self, mock_get, mock_handle
    ):
        webex_listener.BOT_ID = "bot-person-id"
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"text": "/ping"}

        client = webex_listener.app.test_client()
        resp = client.post(
            "/webhook",
            json={
                "data": {
                    "id": "msg-123",
                    "personId": "user-person-id",
                }
            },
        )

        assert resp.status_code == 200
        mock_get.assert_called_once()
        mock_handle.assert_called_once_with("/ping")

    @patch.object(webex_listener, "handle_command")
    def test_webhook_ignores_bot_own_messages(self, mock_handle):
        webex_listener.BOT_ID = "bot-person-id"

        client = webex_listener.app.test_client()
        resp = client.post(
            "/webhook",
            json={
                "data": {
                    "id": "msg-123",
                    "personId": "bot-person-id",
                }
            },
        )

        assert resp.status_code == 200
        mock_handle.assert_not_called()
