"""Tests for feed source resolution in the live agent."""

from __future__ import annotations

import pytest

from hermes.live.agent import _resolve_feed_source


class _Cfg:
    def __init__(self, feed_source="auto", dhan_client_id="", dhan_pin="", dhan_totp_secret=""):
        self.feed_source = feed_source
        self.dhan_client_id = dhan_client_id
        self.dhan_pin = dhan_pin
        self.dhan_totp_secret = dhan_totp_secret


def test_feed_auto_without_dhan_uses_yfinance():
    assert _resolve_feed_source(_Cfg()) == "yfinance"


def test_feed_auto_with_dhan_creds():
    assert _resolve_feed_source(_Cfg(dhan_client_id="x", dhan_pin="y", dhan_totp_secret="z")) == "dhan"


def test_feed_explicit_yfinance():
    assert _resolve_feed_source(_Cfg(feed_source="yfinance", dhan_client_id="x")) == "yfinance"
