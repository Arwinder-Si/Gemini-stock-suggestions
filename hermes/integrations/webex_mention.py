"""Webex @mention helpers (esp-eyes / chatops-adhoc-scripts pattern)."""

from __future__ import annotations


def format_bot_mention(*, bot_email: str, bot_name: str) -> str:
    """
    Webex markdown mention for a bot.

    Example: ``<@personEmail:hermes@webex.bot|Hermes>``
    """
    if bot_email:
        return f"<@personEmail:{bot_email}|{bot_name}>"
    return f"@{bot_name}"


def format_user_command(
    cmd: str,
    *,
    bot_email: str = "",
    bot_name: str = "Hermes",
) -> str:
    """Full command a user can send: tagged bot + command."""
    alias = cmd.lstrip("/")
    return f"{format_bot_mention(bot_email=bot_email, bot_name=bot_name)} {alias}"


def plain_user_command(cmd: str, *, bot_name: str = "Hermes") -> str:
    """Plain @Name command (safe inside adaptive card attachments)."""
    return f"@{bot_name} {cmd.lstrip('/')}"
