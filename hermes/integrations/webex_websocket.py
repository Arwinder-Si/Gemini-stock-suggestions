"""
Webex WebSocket listener for adaptive card button clicks.

Card Action.Submit events are delivered over an outbound WebSocket (WDM device
API), not via message polling — same pattern as platform-sre-chatops. This works
on internal VMs that cannot receive inbound HTTP webhooks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from typing import Any, Callable

import requests
import websockets

logger = logging.getLogger("WebexChatOps")

WDM_API = "https://wdm-a.wbx2.com/wdm/api/v1"
WEBEX_API = "https://webexapis.com/v1"

DEVICE_DATA = {
    "deviceName": "hermes-chatops",
    "deviceType": "DESKTOP",
    "localizedModel": "python",
    "model": "hermes",
    "name": "hermes-chatops-client",
    "systemName": "hermes-vm",
    "systemVersion": "1.0",
}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_or_create_device(token: str) -> dict[str, Any]:
    """Register a WDM device and return device info including webSocketUrl."""
    headers = _auth_headers(token)
    try:
        resp = requests.get(f"{WDM_API}/devices", headers=headers, timeout=15)
        if resp.ok:
            for device in resp.json().get("devices", []):
                if device.get("name") == DEVICE_DATA["name"]:
                    return device
    except requests.RequestException as exc:
        logger.warning("WDM device list failed: %s", exc)

    resp = requests.post(
        f"{WDM_API}/devices",
        headers=headers,
        json=DEVICE_DATA,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def resolve_activity_resource_id(activity: dict[str, Any], *, token: str) -> str:
    """Resolve attachment action or message id from a websocket activity."""
    activity_id = activity["id"]
    target = activity["target"]
    conversation_url = target["url"]
    target_id = target["id"]
    verb = "messages" if activity.get("verb") == "post" else "attachment/actions"
    resource_url = conversation_url.replace(
        f"conversations/{target_id}",
        f"{verb}/{activity_id}",
    )
    resp = requests.get(resource_url, headers=_auth_headers(token), timeout=15)
    resp.raise_for_status()
    return resp.json()["id"]


def fetch_attachment_action(action_id: str, *, token: str) -> dict[str, Any]:
    resp = requests.get(
        f"{WEBEX_API}/attachment/actions/{action_id}",
        headers=_auth_headers(token),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


class WebexCardActionListener:
    """Background WebSocket client for Action.Submit on adaptive cards."""

    def __init__(
        self,
        *,
        token: str,
        room_id: str,
        bot_id: str,
        on_card_action: Callable[[dict[str, Any]], None],
        bot_email: str = "",
    ) -> None:
        self._token = token
        self._room_id = room_id
        self._bot_id = bot_id
        self._bot_email = bot_email
        self._on_card_action = on_card_action
        self._device_info: dict[str, Any] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._seen_action_ids: set[str] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_forever,
            name="webex-card-listener",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                asyncio.run(self._listen())
            except Exception:
                logger.exception("Webex WebSocket listener crashed — retrying in 10s")
                if self._stop.wait(10):
                    break

    async def _listen(self) -> None:
        if self._device_info is None:
            self._device_info = get_or_create_device(self._token)

        ws_url = self._device_info["webSocketUrl"]
        logger.info("Opening Webex WebSocket for card actions: %s", ws_url)

        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=30) as ws:
            auth = {
                "id": str(uuid.uuid4()),
                "type": "authorization",
                "data": {"token": f"Bearer {self._token}"},
            }
            await ws.send(json.dumps(auth))
            logger.info("Webex WebSocket connected — card buttons enabled")

            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue
                self._handle_raw_message(raw)

    def _handle_raw_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        data = msg.get("data") or {}
        if data.get("eventType") != "conversation.activity":
            return

        activity = data.get("activity") or {}
        if activity.get("verb") != "cardAction":
            return

        actor = activity.get("actor") or {}
        if actor.get("type") != "PERSON":
            return
        actor_email = actor.get("emailAddress", "")
        if self._bot_email and actor_email == self._bot_email:
            return

        try:
            action_id = resolve_activity_resource_id(activity, token=self._token)
        except requests.RequestException as exc:
            logger.warning("Failed to resolve card action id: %s", exc)
            return

        if action_id in self._seen_action_ids:
            return
        self._seen_action_ids.add(action_id)
        if len(self._seen_action_ids) > 500:
            self._seen_action_ids.clear()

        try:
            action = fetch_attachment_action(action_id, token=self._token)
        except requests.RequestException as exc:
            logger.warning("Failed to fetch card action %s: %s", action_id, exc)
            return

        if action.get("personId") == self._bot_id:
            return
        if action.get("roomId") and action["roomId"] != self._room_id:
            return

        logger.info("Card button clicked — action %s", action_id)
        self._on_card_action(action)
