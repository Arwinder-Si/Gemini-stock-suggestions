"""Tests for Webex help cards and natural-language handling."""

from unittest.mock import patch

import hermes.integrations.chatops as chatops
from hermes.integrations.webex_cards import build_help_adaptive_card, MENU_COMMANDS


def test_help_adaptive_card_lists_copy_commands():
    card = build_help_adaptive_card(bot_name="Hermes")
    assert card["type"] == "AdaptiveCard"
    card_str = str(card)
    assert "@Hermes plan" in card_str
    assert "Action.Submit" not in card_str
    for cmd, _, _ in MENU_COMMANDS:
        assert cmd.lstrip("/") in card_str or cmd in card_str


def test_extract_command_alias():
    assert chatops.extract_command_from_text("@Hermes plan") == "/plan"
    assert chatops.extract_command_from_text("@Hermes /ping") == "/ping"
    assert chatops.extract_command_from_text("what can you do") is None


def test_is_help_or_unknown_phrases():
    assert chatops.is_help_or_unknown("what can you do?")
    assert chatops.is_help_or_unknown("Hermes help")
    assert not chatops.is_help_or_unknown("/plan")


@patch.object(chatops, "send_help_card")
def test_process_message_natural_language(mock_help):
    chatops.process_message(
        {"personId": "user-1", "text": "what can you do?"},
        bot_id="bot-1",
        token="tok",
        room_id="room",
    )
    mock_help.assert_called_once()


@patch.object(chatops, "handle_command")
def test_process_message_alias_command(mock_cmd):
    chatops.process_message(
        {"personId": "user-1", "text": "@Hermes plan"},
        bot_id="bot-1",
        token="tok",
        room_id="room",
    )
    mock_cmd.assert_called_once_with("/plan", token="tok", room_id="room")


@patch.object(chatops, "handle_command")
def test_process_message_slash_command(mock_cmd):
    chatops.process_message(
        {"personId": "user-1", "text": "@Hermes /ping"},
        bot_id="bot-1",
        token="tok",
        room_id="room",
    )
    mock_cmd.assert_called_once()
