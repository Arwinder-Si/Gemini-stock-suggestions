#!/usr/bin/env python3
"""
VM preflight checks — run after cloning the repo and filling in .env.

    cd ~/github/Gemini-stock-suggestions
    source venv/bin/activate
    python scripts/precheck_vm.py

Exit code 0 = all required checks passed.
Exit code 1 = one or more required checks failed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo root = parent of scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))


def _ok(msg: str) -> None:
    print(f"  OK   {msg}")


def _warn(msg: str) -> None:
    print(f"  WARN {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL {msg}")


def check_env_file() -> bool:
    print("\n[1] Environment file")
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        _fail(".env missing — run: cp .env.example .env")
        return False
    _ok(".env exists")
    return True


def check_config() -> tuple[bool, object]:
    print("\n[2] Required config")
    from hermes.config import get_config

    get_config.cache_clear()
    cfg = get_config()

    ok = True
    for name, val in [
        ("WEBEX_TOKEN", cfg.webex_token),
        ("WEBEX_ROOM_ID", cfg.webex_room_id),
        ("MONGODB_URI", cfg.mongodb_uri or os.getenv("MONGODB_URI", "")),
    ]:
        if val:
            _ok(f"{name} is set")
        else:
            _fail(f"{name} is empty")
            ok = False

    _ok(f"TRADING_MODE={cfg.trading_mode}")
    _ok(f"FEED_SOURCE={cfg.feed_source}")
    _ok(f"BOT_POLL_INTERVAL_SEC={cfg.bot_poll_interval_sec}")
    return ok, cfg


def _mongodb_ssl_hints() -> None:
    _warn("TLSV1_ALERT_INTERNAL_ERROR almost always means Atlas Network Access blocked this IP.")
    _warn("Atlas rejects non-whitelisted IPs during TLS — it looks like an SSL error, not a cert issue.")
    try:
        import requests

        ip = requests.get("https://ifconfig.me/ip", timeout=5).text.strip()
        if ip:
            _warn(f"Add this outbound IP in Atlas → Network Access: {ip}/32")
    except Exception:
        _warn("Run: curl -s https://ifconfig.me/ip  and add that IP in Atlas → Network Access")
    _warn("Quick test: temporarily allow 0.0.0.0/0 in Atlas Network Access (remove after confirming)")
    _warn("Your VM and Mac have different IPs — whitelist both if you use both.")


def check_mongodb(uri: str, *, tls_insecure: bool = False) -> bool:
    print("\n[3] MongoDB Atlas")
    if not uri:
        _fail("MONGODB_URI not set — paper trades will not persist")
        return False
    try:
        import hermes.data  # noqa: F401 — ensure package exists on VM
        from hermes.data.analytics_mongo import MongoAnalyticsStore

        store = MongoAnalyticsStore(uri, tls_insecure=tls_insecure)
        store.client.admin.command("ping")
        _ok("MongoDB ping succeeded")
        cols = store.db.list_collection_names()
        _ok(f"Database '{store.db.name}' reachable ({len(cols)} collections)")
        return True
    except ModuleNotFoundError as exc:
        _fail(f"Python package missing: {exc}")
        _warn(
            "hermes/data/ was not in git (gitignore data/ bug). "
            "Run: git pull  after updating the repo, or check hermes/data/__init__.py exists."
        )
        return False
    except Exception as exc:
        err = str(exc)
        _fail(f"MongoDB connection failed: {err[:200]}")
        if "SSL" in err or "TLS" in err or "tlsv1" in err.lower():
            _mongodb_ssl_hints()
        else:
            _warn("Check Atlas Network Access allows this VM's outbound IP")
        return False


def check_webex(token: str, room_id: str) -> bool:
    print("\n[4] Webex API (polling ChatOps)")
    if not token or not room_id:
        _fail("WEBEX_TOKEN or WEBEX_ROOM_ID missing")
        return False
    try:
        import requests

        headers = {"Authorization": f"Bearer {token}"}
        me = requests.get("https://webexapis.com/v1/people/me", headers=headers, timeout=15)
        if me.status_code != 200:
            _fail(f"Bot identity failed: HTTP {me.status_code}")
            return False
        bot = me.json()
        _ok(f"Bot identity: {bot.get('displayName', 'unknown')}")

        room = requests.get(
            f"https://webexapis.com/v1/rooms/{room_id}",
            headers=headers,
            timeout=15,
        )
        if room.status_code != 200:
            _fail(f"Room lookup failed: HTTP {room.status_code}")
            return False
        room_type = room.json().get("type", "group")
        _ok(f"Room: {room.json().get('title', room_id)} (type={room_type})")

        params: dict = {"roomId": room_id, "max": 5}
        if room_type == "group":
            params["mentionedPeople"] = "me"
        msgs = requests.get(
            "https://webexapis.com/v1/messages",
            headers=headers,
            params=params,
            timeout=15,
        )
        if msgs.status_code == 403:
            _fail("403 listing messages — bot may not be in the room, or mention filter issue")
            return False
        if msgs.status_code == 429:
            _warn("Messages API rate limited (HTTP 429) — bot token and room are OK")
            _warn("Wait a minute and retry precheck, or increase BOT_POLL_INTERVAL_SEC to 5")
            if room_type == "group":
                _warn("Group space: users must send @Hermes /ping (with @mention)")
            return True
        if msgs.status_code != 200:
            _fail(f"Messages API failed: HTTP {msgs.status_code}")
            return False
        count = len(msgs.json().get("items", []))
        _ok(f"Messages API OK ({count} recent @mention messages visible)")
        if room_type == "group":
            _warn("Group space: users must send @Hermes /ping (with @mention)")
        return True
    except Exception as exc:
        _fail(f"Webex check failed: {exc}")
        return False


def check_yfinance() -> bool:
    print("\n[5] Market data (yfinance — paper feed fallback)")
    try:
        import yfinance as yf

        df = yf.download("^NSEI", period="2d", interval="1d", progress=False)
        if df is None or df.empty:
            _fail("yfinance returned no data for ^NSEI")
            return False
        _ok("yfinance fetch OK (Nifty index)")
        return True
    except Exception as exc:
        _fail(f"yfinance failed: {exc}")
        _warn("VM needs outbound HTTPS to Yahoo finance endpoints")
        return False


def check_dhan_optional(cfg) -> None:
    print("\n[6] Dhan feed (optional)")
    has_creds = bool(cfg.dhan_client_id and cfg.dhan_pin and cfg.dhan_totp_secret)
    if not has_creds:
        _warn("Dhan creds not set — paper mode will use yfinance (FEED_SOURCE=auto)")
        return
    try:
        from hermes.integrations.auth_manager import get_fresh_dhan_token

        token = get_fresh_dhan_token(cfg.dhan_client_id, cfg.dhan_pin, cfg.dhan_totp_secret)
        if token:
            _ok("Dhan TOTP token generated")
        else:
            _fail("Dhan token empty")
    except Exception as exc:
        _fail(f"Dhan auth failed: {exc}")


def check_artifacts() -> None:
    print("\n[7] Trade plan artifacts")
    for name in ("trade_plan.json", "morning_trade_plan.json", "screener_results.csv"):
        path = REPO_ROOT / name
        if path.exists():
            _ok(f"{name} exists")
        else:
            _warn(f"{name} missing — run: python -m hermes.cli evening")


def check_system_hints() -> None:
    print("\n[8] System hints (manual)")
    tz = os.environ.get("TZ", "")
    try:
        import subprocess

        timedate = subprocess.run(
            ["timedatectl", "show", "-p", "Timezone", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
        tz_val = timedate.stdout.strip() or tz or "unknown"
        if "Kolkata" in tz_val or "Asia/Kolkata" in tz_val:
            _ok(f"Timezone: {tz_val}")
        else:
            _warn(f"Timezone is {tz_val} — cron in setup_vm.sh expects IST (Asia/Kolkata)")
    except Exception:
        _warn("Could not read timezone — run: timedatectl set-timezone Asia/Kolkata")

    cron_list = REPO_ROOT / "run_evening.sh"
    if cron_list.exists():
        _ok("Cron wrapper scripts present (run setup_vm.sh if cron not installed yet)")
    else:
        _warn("run_evening.sh missing — run: bash setup_vm.sh")


def main() -> int:
    print("=" * 60)
    print("  Hermes VM preflight")
    print(f"  Repo: {REPO_ROOT}")
    print("=" * 60)

    if not check_env_file():
        return 1

    config_ok, cfg = check_config()
    mongo_ok = check_mongodb(
        cfg.mongodb_uri or os.getenv("MONGODB_URI", ""),
        tls_insecure=cfg.mongodb_tls_insecure,
    )
    webex_ok = check_webex(cfg.webex_token, cfg.webex_room_id)
    yfinance_ok = check_yfinance()
    check_dhan_optional(cfg)
    check_artifacts()
    check_system_hints()

    print("\n" + "=" * 60)
    required_ok = config_ok and mongo_ok and webex_ok and yfinance_ok
    if required_ok:
        print("  RESULT: PASS — ready to run setup_vm.sh / cron / chatops")
        print("=" * 60)
        print("\nNext steps:")
        print("  bash setup_vm.sh                    # install cron + systemd poller")
        print("  bash scripts/configure_bot_polling.sh")
        print("  python -m hermes.cli evening        # generate first trade plan")
        print("  @Hermes /ping in Webex              # test ChatOps")
        return 0

    print("  RESULT: FAIL — fix items marked FAIL above")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
