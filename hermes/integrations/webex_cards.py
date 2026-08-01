"""
Webex Adaptive Cards for Hermes ChatOps.

Submit buttons use the command as the button title so Webex may post it as a
room message the poller can pick up (works in many clients without webhooks).
"""

from __future__ import annotations

from typing import Any

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
        "**ChatOps (this bot)** — Ask anytime with `@Hermes /command` or tap a button below.\n\n"
        "_Paper mode only — no real broker orders._"
    )


def help_menu_markdown() -> str:
    return (
        "I didn't recognize that request. Here is what I can do — "
        "**tap a button below** or type `@Hermes /command`:\n\n"
        + "\n".join(f"- `{cmd}` — {label}" for cmd, label, _ in MENU_COMMANDS)
        + "\n\n_Advanced: `/pnl` (live Dhan), `/kill` (emergency halt)_"
    )


def build_help_adaptive_card() -> dict[str, Any]:
    """Adaptive Card with clickable Submit buttons for each command."""
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
            "text": "Tap a button to run a command, or type @Hermes /command in this space.",
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
                                        "data": {"command": cmd},
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


def help_message_attachments() -> list[dict[str, Any]]:
    return [
        {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": build_help_adaptive_card(),
        }
    ]
