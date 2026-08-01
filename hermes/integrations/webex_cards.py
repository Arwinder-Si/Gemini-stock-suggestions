"""
Webex Adaptive Cards for Hermes ChatOps.

Card Action.Submit buttons are handled via outbound WebSocket (see webex_websocket.py).
User-facing command text uses Webex mention tags:
``<@personEmail:hermes@webex.bot|Hermes> plan``
"""

from __future__ import annotations

from typing import Any

from hermes.integrations.webex_mention import format_bot_mention, format_user_command

# Commands exposed as card buttons (safe, everyday actions)
MENU_COMMANDS: list[tuple[str, str, str]] = [
    ("/ping", "Health Check", "Verify the bot and VM are online"),
    ("/plan", "Evening Trade Plan", "Latest screener picks and scores"),
    ("/morning", "Morning Briefing", "Gap prediction + refined trade list"),
    ("/paper", "Paper Portfolio", "Paper trading capital and limits"),
    ("/journal", "Today's Journal", "Paper trades executed today"),
    ("/stats", "Analytics", "Win rate and performance summary"),
    ("/help", "About Hermes", "What this bot does and all commands"),
]


def hermes_about_markdown(*, bot_email: str = "", bot_name: str = "Hermes") -> str:
    """Markdown description of the Hermes bot."""
    tagged = format_bot_mention(bot_email=bot_email, bot_name=bot_name)
    example = format_user_command("plan", bot_email=bot_email, bot_name=bot_name)
    return (
        "**Hermes — NSE Intraday Trading Assistant**\n\n"
        "Hermes automates your end-to-end trading workflow on the VM:\n\n"
        "**Evening (3:45 PM)** — Scans ~150 NSE stocks, scores setups, builds "
        "tomorrow's trade plan, and posts results here.\n\n"
        "**Morning (8:30 AM)** — Combines overnight global markets, news sentiment, "
        "and yesterday's screener to refine today's watchlist.\n\n"
        "**Market hours (9:00–15:30)** — Runs Opening Range Breakout (ORB) paper trades "
        "on the morning plan. Signals, entries, and P&L are logged to MongoDB.\n\n"
        f"**ChatOps** — @mention {tagged} or tap a button below. "
        f"You can also type: `{example}`\n\n"
        "_Paper mode only — no real broker orders._"
    )


def help_menu_markdown(*, bot_email: str = "", bot_name: str = "Hermes") -> str:
    tagged = format_bot_mention(bot_email=bot_email, bot_name=bot_name)
    return (
        f"**Tap a button below** or send a tagged command to {tagged}:\n\n"
        + "\n".join(
            f"- `{format_user_command(cmd, bot_email=bot_email, bot_name=bot_name)}` — {label}"
            for cmd, label, _ in MENU_COMMANDS
        )
        + "\n\n_Advanced: `@Hermes pnl`, `@Hermes kill`_"
    )


def build_help_adaptive_card(*, bot_email: str = "", bot_name: str = "Hermes") -> dict[str, Any]:
    """Adaptive Card with Submit buttons for each command."""
    tagged = format_bot_mention(bot_email=bot_email, bot_name=bot_name)
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
                f"Tap a button to run a command. In group spaces you can also type "
                f"{format_user_command('plan', bot_email=bot_email, bot_name=bot_name)}."
            ),
            "isSubtle": True,
            "wrap": True,
        },
    ]

    for cmd, label, desc in MENU_COMMANDS:
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
                                "type": "ActionSet",
                                "actions": [
                                    {
                                        "type": "Action.Submit",
                                        "title": cmd,
                                        "data": {
                                            "command": cmd,
                                            "callback_keyword": f"callback___{cmd}",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        )

    body.append(
        {
            "type": "TextBlock",
            "text": f"Bot tag for copy/paste: {tagged}",
            "isSubtle": True,
            "size": "Small",
            "wrap": True,
        }
    )

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.3",
        "body": body,
    }


def help_message_attachments(*, bot_email: str = "", bot_name: str = "Hermes") -> list[dict[str, Any]]:
    return [
        {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": build_help_adaptive_card(bot_email=bot_email, bot_name=bot_name),
        }
    ]
