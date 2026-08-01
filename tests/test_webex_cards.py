"""Tests for Webex mention tags, cards, and card-action handling."""

from unittest.mock import patch

import hermes.integrations.chatops as chatops
from hermes.integrations.webex_cards import build_help_adaptive_card, MENU_COMMANDS
from hermes.integrations.webex_mention import format_bot_mention, format_user_command


def test_format_bot_mention_person_email():
    assert (
        format_bot_mention(bot_email="hermes@webex.bot", bot_name="Hermes")
        == "<@personEmail:hermes@webex.bot|Hermes>"
    )


def test_format_user_command():
    cmd = format_user_command("/plan", bot_email="hermes@webex.bot", bot_name="Hermes")
    assert cmd == "<@personEmail:hermes@webex.bot|Hermes> plan"


def test_help_adaptive_card_has_submit_buttons():
    card = build_help_adaptive_card(bot_email="hermes@webex.bot", bot_name="Hermes")
    card_str = str(card)
    assert "Action.Submit" in card_str
    assert "<@personEmail:hermes@webex.bot|Hermes>" in card_str
    for cmd, _, _ in MENU_COMMANDS:
        assert cmd in card_str


def test_handle_attachment_action_runs_command():
    with patch.object(chatops, "handle_command") as mock_cmd:
        chatops.handle_attachment_action(
            {"inputs": {"command": "/plan"}, "roomId": "room"},
            token="tok",
            room_id="room",
        )
        mock_cmd.assert_called_once_with("/plan", token="tok", room_id="room")


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
        bot_email="hermes@webex.bot",
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
    mock_cmd.assert_called_once_with("/ping", token="tok", room_id="room")
