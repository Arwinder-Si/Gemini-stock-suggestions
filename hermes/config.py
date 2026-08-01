"""
Configuration management using pydantic-settings.

Uses a lazy-loading pattern so that importing this module does NOT
crash when a .env file is absent (e.g., during unit tests).
"""

import datetime
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    # Dhan API
    dhan_client_id: str = Field(default="", alias="DHAN_CLIENT_ID")
    dhan_pin: str = Field(default="", alias="DHAN_PIN")
    dhan_totp_secret: str = Field(default="", alias="DHAN_TOTP_SECRET")

    # Comma-separated list of "NAME:SECURITY_ID" pairs
    # e.g. "RELIANCE:11536,TCS:3456"
    symbol_security_ids: str = Field(default="", alias="SYMBOL_SECURITY_IDS")

    # Strategy settings
    orb_start_time: str = Field(default="09:15", alias="ORB_START_TIME")
    orb_end_time: str = Field(default="09:30", alias="ORB_END_TIME")
    min_volume_threshold: int = Field(default=10000, alias="MIN_VOLUME_THRESHOLD")
    risk_reward_ratio: float = Field(default=1.0, alias="RISK_REWARD_RATIO")
    time_based_exit: str = Field(default="15:15", alias="TIME_BASED_EXIT")
    screener_top_n: int = Field(default=5, alias="SCREENER_TOP_N")

    # Webex
    webex_token: str = Field(default="", alias="WEBEX_TOKEN")
    webex_room_id: str = Field(default="", alias="WEBEX_ROOM_ID")
    bot_public_url: str = Field(default="", alias="BOT_PUBLIC_URL")
    bot_port: int = Field(default=5050, alias="BOT_PORT")
    bot_poll_interval_sec: float = Field(default=5.0, alias="BOT_POLL_INTERVAL_SEC")
    bot_state_file: str = Field(default="", alias="BOT_STATE_FILE")

    # Paper Trading / Agent
    paper_starting_capital: float = Field(default=1_000_000.0, alias="PAPER_STARTING_CAPITAL")
    max_daily_trades: int = Field(default=5, alias="MAX_DAILY_TRADES")
    max_daily_loss_rupees: float = Field(default=10_000.0, alias="MAX_DAILY_LOSS_RUPEES")
    risk_per_trade_pct: float = Field(default=0.01, alias="RISK_PER_TRADE_PCT")
    max_sector_exposure_pct: float = Field(default=0.30, alias="MAX_SECTOR_EXPOSURE_PCT")
    trading_mode: str = Field(default="paper", alias="TRADING_MODE")
    # auto = Dhan if credentials present, else yfinance (paper-friendly)
    feed_source: str = Field(default="auto", alias="FEED_SOURCE")

    # Analytics persistence (MongoDB Atlas)
    mongodb_uri: str = Field(default="", alias="MONGODB_URI")
    # Last resort on corporate VMs with SSL inspection — not for production
    mongodb_tls_insecure: bool = Field(default=False, alias="MONGODB_TLS_INSECURE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ── Derived helpers ──────────────────────────────────────────────

    @staticmethod
    def _resolve_trade_plan_path(file_path: str) -> str:
        """Prefer the latest Hermes run's plan, falling back to the repo root."""
        import os

        var_dir = os.environ.get("HERMES_VAR_DIR", "var")
        latest = os.path.join(var_dir, "state", "latest", os.path.basename(file_path))
        if os.path.exists(latest):
            return latest
        return file_path

    def load_trade_plan(self, file_path: str = "trade_plan.json", required: bool = False) -> dict[str, str]:
        """
        Loads structured trade plan file with freshness check.
        Format: {"trading_date": "YYYY-MM-DD", "symbols": {"RELIANCE": "11536"}}
        Legacy format supported for backwards compatibility.

        Resolution order: the current Hermes run (``var/state/latest/<file>``)
        first, then the repo-root copy for backward compatibility.
        """
        import os
        import json
        from hermes.clock import trading_date_ist

        file_path = self._resolve_trade_plan_path(file_path)

        if not os.path.exists(file_path):
            if required:
                raise FileNotFoundError(f"Required trade plan {file_path} does not exist!")
            return {}

        try:
            with open(file_path, "r") as f:
                data = json.load(f)

            if isinstance(data, dict):
                # New structured format
                if "symbols" in data and "trading_date" in data:
                    plan_date_str = data["trading_date"]
                    today_str = trading_date_ist().strftime("%Y-%m-%d")
                    if required and plan_date_str < today_str:
                        raise ValueError(f"Trade plan {file_path} is stale! Date: {plan_date_str}, Today: {today_str}")
                    return data["symbols"]
                # Legacy raw dict format
                return data
        except Exception as e:
            if required:
                raise RuntimeError(f"Failed to load required trade plan {file_path}: {e}") from e

        return {}

    def load_active_trade_plan(self, required: bool = False) -> dict[str, str]:
        """
        Load the plan the live agent should use today.

        Prefers ``morning_trade_plan.json`` when its trading_date matches today;
        otherwise falls back to the evening ``trade_plan.json``.
        """
        import os
        import json
        from hermes.clock import trading_date_ist

        today = trading_date_ist().strftime("%Y-%m-%d")
        morning_path = self._resolve_trade_plan_path("morning_trade_plan.json")

        if os.path.exists(morning_path):
            try:
                with open(morning_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("trading_date") == today and data.get("symbols"):
                    return data["symbols"]
            except Exception:
                pass

        return self.load_trade_plan("trade_plan.json", required=required)

    @property
    def security_id_map(self) -> dict[str, str]:
        """Returns {human_name: security_id} mapping from active trade plan or fallback to .env."""
        plan = self.load_active_trade_plan(required=False)
        if plan:
            return plan

        mapping: dict[str, str] = {}
        for token in self.symbol_security_ids.split(","):
            token = token.strip()
            if not token:
                continue
            if ":" in token:
                name, sec_id = token.split(":", 1)
                mapping[name.strip()] = sec_id.strip()
            else:
                mapping[token] = token
        return mapping

    @property
    def security_ids(self) -> list[str]:
        """Flat list of security IDs."""
        return list(self.security_id_map.values())

    @property
    def security_id_to_name(self) -> dict[str, str]:
        """Reverse mapping: security_id → human name."""
        return {v: k for k, v in self.security_id_map.items()}

    @property
    def orb_start_time_parsed(self) -> datetime.time:
        return datetime.datetime.strptime(self.orb_start_time, "%H:%M").time()

    @property
    def orb_end_time_parsed(self) -> datetime.time:
        return datetime.datetime.strptime(self.orb_end_time, "%H:%M").time()

    @property
    def time_based_exit_parsed(self) -> datetime.time:
        return datetime.datetime.strptime(self.time_based_exit, "%H:%M").time()


@lru_cache(maxsize=1)
def get_config() -> Settings:
    """Lazy singleton — only reads .env when first called."""
    return Settings()
