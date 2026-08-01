"""Unit tests for Webex ChatOps polling and command routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import hermes.integrations.chatops as chatops


class TestHandleCommand:
    @patch.object(chatops, "send_webex_reply")
    def test_ping_with_mention(self, mock_reply):
        chatops.handle_command("Hermes /ping", token="tok", room_id="room")
        mock_reply.assert_called_once()
        assert "Pong" in mock_reply.call_args.kwargs.get("text", mock_reply.call_args[0][0])

    @patch.object(chatops, "send_webex_reply")
    def test_ping_direct(self, mock_reply):
        chatops.handle_command("/ping", token="tok", room_id="room")
        mock_reply.assert_called_once()

    @patch.object(chatops, "send_help_card")
    def test_help(self, mock_help):
        chatops.handle_command("/help", token="tok", room_id="room")
        mock_help.assert_called_once_with(token="tok", room_id="room", include_about=True)

    @patch.object(chatops, "send_webex_message")
    @patch.object(chatops, "send_webex_reply")
    def test_unknown_command(self, mock_reply, mock_message):
        chatops.handle_command("/foobar", token="tok", room_id="room")
        text = mock_reply.call_args.kwargs.get("text", mock_reply.call_args[0][0])
        assert "Unknown command" in text
        mock_message.assert_called_once()

    @patch.object(chatops, "send_webex_reply")
    def test_no_slash_ignored(self, mock_reply):
        chatops.handle_command("Ping", token="tok", room_id="room")
        mock_reply.assert_not_called()


class TestPollingHelpers:
    def test_collect_new_messages_oldest_first(self):
        messages = [
            {"id": "c", "text": "/ping"},
            {"id": "b", "text": "/help"},
            {"id": "a", "text": "old"},
        ]
        new = chatops.collect_new_messages(messages, "a")
        assert [m["id"] for m in new] == ["b", "c"]

    def test_collect_new_messages_empty_when_no_cursor(self):
        messages = [{"id": "x", "text": "/ping"}]
        assert chatops.collect_new_messages(messages, None) == []

    @patch.object(chatops, "handle_command")
    def test_process_message_skips_bot(self, mock_handle):
        chatops.process_message(
            {"id": "1", "personId": "bot-1", "text": "/ping"},
            bot_id="bot-1",
            token="tok",
            room_id="room",
        )
        mock_handle.assert_not_called()

    @patch.object(chatops, "handle_command")
    def test_process_message_routes_command(self, mock_handle):
        chatops.process_message(
            {"id": "1", "personId": "user-1", "text": "@Hermes /ping"},
            bot_id="bot-1",
            token="tok",
            room_id="room",
        )
        mock_handle.assert_called_once_with("/ping", token="tok", room_id="room")

    def test_list_room_messages_raises_on_rate_limit(self, monkeypatch):
        def fake_get(url, headers=None, params=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 429
            resp.headers = {"Retry-After": "30"}
            return resp

        monkeypatch.setattr(chatops.requests, "get", fake_get)
        with pytest.raises(chatops.WebexRateLimited) as exc:
            chatops.list_room_messages("tok", "room-1", room_type="group")
        assert exc.value.retry_after == 30.0

    def test_list_room_messages_uses_mentioned_for_group(self, monkeypatch):
        captured = {}

        def fake_get(url, headers=None, params=None, timeout=None):
            captured["params"] = params
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"items": []}
            resp.raise_for_status = MagicMock()
            return resp

        monkeypatch.setattr(chatops.requests, "get", fake_get)
        chatops.list_room_messages("tok", "room-1", room_type="group")
        assert captured["params"]["mentionedPeople"] == "me"

    def test_poll_once_initializes_state_without_backlog(self, tmp_path):
        state_file = tmp_path / "state.json"
        state: dict = {}

        with patch.object(chatops, "list_room_messages", return_value=[{"id": "newest"}]):
            chatops.poll_once(
                token="tok",
                room_id="room",
                room_type="group",
                bot_id="bot",
                bot_name="Hermes",
                state=state,
                state_file=state_file,
            )

        assert state["last_message_id"] == "newest"
        assert state_file.exists()

    def test_poll_once_processes_new_commands(self, tmp_path):
        state_file = tmp_path / "state.json"
        state = {"last_message_id": "old"}

        messages = [
            {"id": "new", "personId": "user", "text": "/ping"},
            {"id": "old", "personId": "user", "text": "hi"},
        ]

        with patch.object(chatops, "list_room_messages", return_value=messages):
            with patch.object(chatops, "process_message") as mock_process:
                chatops.poll_once(
                    token="tok",
                    room_id="room",
                    room_type="group",
                    bot_id="bot",
                    bot_name="Hermes",
                    state=state,
                    state_file=state_file,
                )

        mock_process.assert_called_once()
        assert state["last_message_id"] == "new"
