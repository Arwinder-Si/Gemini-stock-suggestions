"""
Webex Adaptive Cards for Hermes ChatOps.

Card buttons (Action.Submit) require an inbound webhook — not available on the
internal polling VM. The help card lists copy-paste commands such as
``@Hermes plan`` instead of fake clickable buttons.
"""

from __future__ import annotations

from typing import Any

# Commands exposed in the help menu
MENU_COMMANDS: list[tuple[str, str, str]] = [
    ("/ping", "Health Check", "Verify the bot and VM are online"),
    ("/plan", "Evening Trade Plan", "Latest screener picks and scores"),
    ("/morning", "Morning Briefing", "Gap prediction + refined trade list"),
    ("/paper", "Paper Portfolio", "Paper trading capital and limits"),
    ("/journal", "Today's Journal", "Paper trades executed today"),
    ("/stats", "Analytics", "Win rate and performance summary"),
    ("/help", "About Hermes", "What this bot does and all commands"),
]


def user_command_text(cmd: str, *, bot_name: str = "Hermes") -> str:
    """Human-typed command for group spaces (no leading slash required)."""
    alias = cmd.lstrip("/")
    return f"@{bot_name} {alias}"


def hermes_about_markdown() -> str:
    """Markdown description of the Hermes bot."""
    return (
        "**Hermes — NSE Intraday Trading Assistant**\n\n"
        "Hermes automates your end-to-end trading workflow on the VM:\n\n"
        "**Evening (3:45 PM)** — Scans ~150 NSE stocks, scores setups, builds "
        "tomorrow's trade plan, and posts results here.\n\n"
        "**Morning (8:30 AM)** — Combines overnight global markets, news sentiment, "
        "and yesterday's screener to refine today's watchlist.\n\n"
        "**Market hours (9:00–15:30)** — Runs Opening Range Breakout (ORB) paper trades "
        "on the morning plan. Signals, entries, and P&L are logged to MongoDB.\n\n"
        "**ChatOps (this bot)** — In this space, @mention Hermes and send a command "
        "(example: `@Hermes plan`).\n\n"
        "_Paper mode only — no real broker orders._"
    )


def help_menu_markdown(*, bot_name: str = "Hermes") -> str:
    return (
        "**How to run a command**\n\n"
        "In group spaces you must @mention Hermes. Card buttons do not work on this "
        "VM (no public webhook). Copy and send one of these:\n\n"
        + "\n".join(
            f"- `{user_command_text(cmd, bot_name=bot_name)}` — {label}"
            for cmd, label, _ in MENU_COMMANDS
        )
        + "\n\n_Short form works too: `@Hermes plan` or `@Hermes /plan`._\n"
        + "_Advanced: `@Hermes pnl`, `@Hermes kill`_"
    )


def build_help_adaptive_card(*, bot_name: str = "Hermes") -> dict[str, Any]:
    """Adaptive Card listing copy-paste commands (no Submit buttons)."""
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": "Hermes Trading Bot",
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": (
                "Copy a command below, paste it in the message box, and send. "
                "You must include @Hermes — card buttons cannot run commands "
                "without a public webhook URL."
            ),
            "isSubtle": True,
            "wrap": True,
        },
    ]

    for cmd, label, desc in MENU_COMMANDS:
        copy_text = user_command_text(cmd, bot_name=bot_name)
        body.append(
            {
                "type": "ColumnSet",
                "columns": [
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": f"**{label}**",
                                "wrap": True,
                            },
                            {
                                "type": "TextBlock",
                                "text": desc,
                                "isSubtle": True,
                                "size": "Small",
                                "wrap": True,
                            },
                        ],
                    },
                    {
                        "type": "Column",
                        "width": "auto",
                        "items": [
                            {
                                "type": "Container",
                                "style": "emphasis",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": copy_text,
                                        "fontType": "Monospace",
                                        "horizontalAlignment": "Center",
                                        "wrap": False,
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        )

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": body,
    }


def help_message_attachments(*, bot_name: str = "Hermes") -> list[dict[str, Any]]:
    return [
        {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": build_help_adaptive_card(bot_name=bot_name),
        }
    ]
