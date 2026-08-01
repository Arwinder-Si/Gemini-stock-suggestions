"""Tests for Webex help cards and natural-language handling."""

from unittest.mock import patch

import hermes.integrations.chatops as chatops
from hermes.integrations.webex_cards import build_help_adaptive_card, MENU_COMMANDS


def test_help_adaptive_card_has_submit_buttons():
    card = build_help_adaptive_card()
    assert card["type"] == "AdaptiveCard"
    # Each menu command should have a Submit action with the command as title
    card_str = str(card)
    for cmd, _, _ in MENU_COMMANDS:
        assert cmd in card_str


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
def test_process_message_slash_command(mock_cmd):
    chatops.process_message(
        {"personId": "user-1", "text": "@Hermes /ping"},
        bot_id="bot-1",
        token="tok",
        room_id="room",
    )
    mock_cmd.assert_called_once()
