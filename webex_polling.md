# Webex health bot — polling setup

This document describes how we run a **Webex bot on an internal VM** that
responds to health commands in a Webex space. The bot uses **outbound API
polling** — not webhooks — because the VM has no public inbound URL and
corporate DNS blocks tunnel services such as ngrok.

**App source:** `apps/webex-health-bot/`  
**Reference deployment:** `arw-test-rhel5` on `cloud-svldev-1` (`10.199.63.201`),
bot **Hermes** (`hermes-trader@webex.bot`), room **The Agora**.

---

## Why polling instead of webhooks


| Approach            | Requirement                        | Internal VM (`10.199.x.x`) |
| ------------------- | ---------------------------------- | -------------------------- |
| **Webhooks (push)** | Public HTTPS URL Webex can POST to | Not available              |
| **Polling (pull)**  | Outbound HTTPS to `webexapis.com`  | Works                      |


Webex [webhooks](https://developer.webex.com/docs/api/guides/webhooks) require
a `targetUrl` that is **publicly reachable on the internet**. `localhost`,
private IPs, and ngrok (when DNS is blocked) do not satisfy that requirement.

Polling avoids inbound connectivity entirely: a long-running process on the VM
calls the Webex REST API every few seconds, checks for new commands, and posts
replies.

---



## Architecture

```text
┌─────────────────────────────────────────────────────────────────────────┐
│  Webex Cloud (webexapis.com)                                            │
│  • Room: The Agora (group space)                                        │
│  • Bot: Hermes (bot access token)                                      │
└───────────────────────────────▲─────────────────────────────────────────┘
                                │ outbound HTTPS only
                                │ GET  /messages?roomId=…&mentionedPeople=me
                                │ POST /messages  (reply)
┌───────────────────────────────┴─────────────────────────────────────────┐
│  Internal VM (e.g. arw-test-rhel5 @ 10.199.63.201)                      │
│                                                                         │
│  systemd: webex-health-bot.service                                      │
│    └─ python /opt/webex-health-bot/bot.py                               │
│         • poll loop every BOT_POLL_INTERVAL_SEC (default 3s)            │
│         • state: /var/lib/webex-health-bot/state.json                   │
│         • config: /etc/webex-health-bot/env                             │
└─────────────────────────────────────────────────────────────────────────┘

User in Webex ──► @Hermes /ping ──► bot polls API ──► replies "pong (…)"
```

---



## Webex bot API restrictions (important)

Bots are **not** full room members for message history purposes.


| Room type                     | What the bot can read via API           |
| ----------------------------- | --------------------------------------- |
| **Direct (1:1)** with the bot | All messages                            |
| **Group space**               | Only messages that **@mention** the bot |


In a group space, calling `messages.list(roomId=…)` **without**
`mentionedPeople=me` returns:

```text
403 Forbidden - Failed to get activity
```

Even when the bot appears in the space's People list. Our bot handles this by
passing `mentionedPeople="me"` for group rooms (see `list_room_messages()` in
`bot.py`).

**User-facing implication:** in The Agora, send:

```text
@Hermes /ping
```

Plain `/ping` (without mentioning the bot) is invisible to the bot in group
spaces.

---



## Prerequisites



### Webex side

1. A **bot** registered at [developer.webex.com/my-apps](https://developer.webex.com/my-apps).
2. Bot **access token** (from the bot's configuration page).
3. Target **room ID** — the space where the bot will listen.
4. Bot **added to that room** (People → Add people → search bot email).



### VM side


| Requirement                       | Notes                                                          |
| --------------------------------- | -------------------------------------------------------------- |
| RHEL 9 (or RHEL-like)             | Tested on `arw-test-rhel5`.                                    |
| Python 3.9+                       | RHEL 9 ships Python 3.9.                                       |
| Outbound HTTPS to `webexapis.com` | Verify: `curl -sI https://webexapis.com` → `HTTP/2 401` is OK. |
| No inbound firewall rules         | Polling needs no open ports.                                   |




### Python SDK version

Use `webexteamssdk` **1.x** (`>=1.7,<2`), not `webexpythonsdk` 2.x, which
requires Python 3.10+.

---



## One-time Webex setup



### 1. Create the bot

1. Go to [developer.webex.com/my-apps](https://developer.webex.com/my-apps).
2. Create a **Bot** (not an Integration).
3. Copy the **Bot Access Token** — store it only in `/etc/webex-health-bot/env`
  on the VM, never in git.



### 2. Find the room ID

**Option A — Webex client:** open the space → Room Info → copy Room ID.

**Option B — API helper** (after token is on the VM):

```bash
sudo bash -c 'set -a; source /etc/webex-health-bot/env; set +a; \
  /opt/webex-health-bot/venv/bin/python /opt/webex-health-bot/list_rooms.py agora'
```



### 3. Add the bot to the room

In Webex: open the target space → **People** → **Add people** → add the bot
(e.g. `hermes-trader@webex.bot`).

Verify membership:

```bash
sudo bash -c 'set -a; source /etc/webex-health-bot/env; set +a; \
  /opt/webex-health-bot/venv/bin/python - <<PY
from webexteamssdk import WebexTeamsAPI
import os
api = WebexTeamsAPI(access_token=os.environ["WEBEX_ACCESS_TOKEN"])
me = api.people.me()
room_id = os.environ["WEBEX_ROOM_ID"]
members = list(api.memberships.list(roomId=room_id))
print("Bot in room:", any(m.personId == me.id for m in members))
PY'
```

---



## Deploy to the VM



### 1. Copy app files to the VM

From the repo root on your workstation (adjust SSH target as needed):

```bash
scp -F config/ssh/config -J svl-fab7-svc-a-infra-001 -r \
  apps/webex-health-bot arwinder@10.199.63.201:/tmp/webex-health-bot
```



### 2. Create environment file on the VM

```bash
sudo mkdir -p /etc/webex-health-bot
sudo cp /tmp/webex-health-bot/env.example /etc/webex-health-bot/env
sudo chmod 600 /etc/webex-health-bot/env
sudo editor /etc/webex-health-bot/env   # set WEBEX_ACCESS_TOKEN, WEBEX_ROOM_ID
```

Example `/etc/webex-health-bot/env`:

```bash
WEBEX_ACCESS_TOKEN=<bot-token-from-developer.webex.com>
WEBEX_ROOM_ID=<room-id>
BOT_POLL_INTERVAL_SEC=3
BOT_STATE_FILE=/var/lib/webex-health-bot/state.json
```



### 3. Install and start

```bash
cd /tmp/webex-health-bot
sudo bash install.sh
```

`install.sh` creates:


| Path                                           | Purpose                       |
| ---------------------------------------------- | ----------------------------- |
| `/opt/webex-health-bot/`                       | App code + Python venv        |
| `/etc/webex-health-bot/env`                    | Secrets and config (mode 600) |
| `/var/lib/webex-health-bot/`                   | Poll state file               |
| `/etc/systemd/system/webex-health-bot.service` | systemd unit                  |




### 4. Verify service

```bash
sudo systemctl status webex-health-bot
sudo journalctl -u webex-health-bot -n 20 --no-pager
```

Expected startup log lines:

```text
Listening in room The Agora (<room-id>, type=group)
Bot running as Hermes (hermes-trader@webex.bot)
```

No repeating `403 Forbidden` errors after the fixed `bot.py` is installed.

---



## How the poll loop works

Every `BOT_POLL_INTERVAL_SEC` seconds (default **3**):

1. **List messages** the bot is allowed to see:
  - Group room: `GET /messages?roomId=…&mentionedPeople=me&max=20`
  - Direct room: `GET /messages?roomId=…&max=20`
2. **Compare** against the last processed message ID in
  `/var/lib/webex-health-bot/state.json`.
3. **Parse** new messages for a `/command` token (supports `@Hermes /ping`).
4. **Ignore** messages from the bot itself.
5. **Run** the command handler and **post** the reply via `POST /messages`.
6. **Save** the newest message ID to state.
7. **Sleep** and repeat.

On shutdown (`systemctl stop`), the bot saves state so it does not re-process
old messages after restart.

---



## Commands


| Command        | Response                            |
| -------------- | ----------------------------------- |
| `/ping`        | `pong (<UTC timestamp>)`            |
| `/health`      | Hostname, platform, load, disk free |
| `/healthcheck` | Alias for `/health`                 |
| `/help`        | Command list                        |


In **group spaces**, prefix with a bot mention: `@Hermes /ping`.

---



## Updating bot code

After pulling changes to `bot.py` in the repo:

```bash
# Workstation
scp -F config/ssh/config -J svl-fab7-svc-a-infra-001 \
  apps/webex-health-bot/bot.py arwinder@10.199.63.201:/tmp/webex-health-bot/bot.py

# VM — confirm the fix is present before installing
grep mentionedPeople /tmp/webex-health-bot/bot.py

sudo cp /tmp/webex-health-bot/bot.py /opt/webex-health-bot/bot.py
sudo systemctl restart webex-health-bot
```

To re-process recent messages after a logic change, clear state:

```bash
sudo rm -f /var/lib/webex-health-bot/state.json
sudo systemctl restart webex-health-bot
```

---



## Troubleshooting



### `403 Forbidden - Failed to get activity`

**Cause:** Bot tried to list all messages in a group space without
`mentionedPeople=me`.

**Fix:** Deploy current `bot.py` (must contain `mentionedPeople="me"`). Users
must @mention the bot in group spaces.

**Verify API directly:**

```bash
# Should succeed (may return 0+ messages)
sudo bash -c 'set -a; source /etc/webex-health-bot/env; set +a; \
  /opt/webex-health-bot/venv/bin/python - <<PY
from webexteamssdk import WebexTeamsAPI
import os
api = WebexTeamsAPI(access_token=os.environ["WEBEX_ACCESS_TOKEN"])
msgs = list(api.messages.list(
    roomId=os.environ["WEBEX_ROOM_ID"], max=5, mentionedPeople="me"))
print("Mentioned messages:", len(msgs))
PY'

# Should fail with 403 in group spaces
sudo bash -c 'set -a; source /etc/webex-health-bot/env; set +a; \
  /opt/webex-health-bot/venv/bin/python - <<PY
from webexteamssdk import WebexTeamsAPI
import os
api = WebexTeamsAPI(access_token=os.environ["WEBEX_ACCESS_TOKEN"])
list(api.messages.list(roomId=os.environ["WEBEX_ROOM_ID"], max=5))
PY'
```



### Old code still running

Journal stack traces showing `poll_room(api, room_id, state, …)` without
`room_type`, or line numbers calling `messages.list(roomId=room_id, max=20)`
with no `mentionedPeople`, mean `/opt/webex-health-bot/bot.py` was not updated.

```bash
grep -E 'list_room_messages|mentionedPeople|room_type' /opt/webex-health-bot/bot.py
```



### Bot not replying to `/ping`

1. Confirm you used `@Hermes /ping` (group space).
2. Check logs: `sudo journalctl -u webex-health-bot -f`
3. Confirm bot is in room (membership check above).
4. Confirm `WEBEX_ROOM_ID` matches the intended space.



### `WEBEX_ACCESS_TOKEN is not set`

Create/fix `/etc/webex-health-bot/env` and restart:

```bash
sudo systemctl restart webex-health-bot
```



### Webhooks / ngrok not viable on internal VM

Corporate DNS on `cloud-svldev-1` VMs resolves `webexapis.com` but not
`connect.ngrok-agent.com`. Tunnel-based push is blocked; use polling.

---



## Why we rejected webhooks for this deployment

1. **No public URL** — VM is on `tenant-internal-direct-net` (`10.199.x.x`).
2. **ngrok blocked** — DNS lookup for ngrok fails; outbound tunnel unusable.
3. **Polling is sufficient** — ~3 s latency, simple systemd service, no inbound
  firewall rules.
4. **Same bot restrictions apply** — webhooks for group spaces would still
  require `mentionedPeople=me` filter; users would still @mention the bot.

Webhooks remain an option if a **public HTTPS endpoint** (load balancer, small
cloud VM, approved tunnel) becomes available.

---



## File reference


| Repo path                                        | Installed path                                 |
| ------------------------------------------------ | ---------------------------------------------- |
| `apps/webex-health-bot/bot.py`                   | `/opt/webex-health-bot/bot.py`                 |
| `apps/webex-health-bot/list_rooms.py`            | `/opt/webex-health-bot/list_rooms.py`          |
| `apps/webex-health-bot/requirements.txt`         | `/opt/webex-health-bot/requirements.txt`       |
| `apps/webex-health-bot/webex-health-bot.service` | `/etc/systemd/system/webex-health-bot.service` |
| `apps/webex-health-bot/env.example`              | `/etc/webex-health-bot/env` (manual)           |
| `tests/test_webex_health_bot.py`                 | (dev only)                                     |


---



## Related links

- [Webex Bots guide](https://developer.webex.com/docs/bots)
- [Webex Messages API](https://developer.webex.com/docs/api/v1/messages)
- [Webex Webhooks guide](https://developer.webex.com/docs/api/guides/webhooks) (not used here)

