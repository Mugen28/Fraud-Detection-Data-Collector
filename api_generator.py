#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api_generator.py  (AUTO-GENERATED - do not edit by hand)

Replays the arkm.com API calls captured in the browser, without Playwright.

Captured at: 2026-10-21T14:26:53+00:00
Source page: https://arkm.com/visualizer

Auth model used by arkm.com (reverse engineered from the web app):
  * session cookie  : `arkham_session` (domain .arkm.com) + `cf_clearance`
  * request signing : X-Timestamp = unix seconds
                      X-Payload   = sha256(KEY + ":" + sha256(path + ":" + ts + ":" + KEY))
    where KEY = NEXT_PUBLIC_WEBAPP_CLIENT_KEY (public constant, see CLIENT_KEY)
  * transport       : Cloudflare checks the TLS fingerprint, so curl_cffi with
                      `impersonate="chrome"` is used when available.

This file contains live session cookies. Keep it private.
Re-run `python arkm_capture.py` when the session expires.

Usage
-----
    python api_generator.py                     # replay everything
    python api_generator.py --delay 3           # slower, safer
    python api_generator.py --dry-run           # show what would be sent
    python api_generator.py --list
    python api_generator.py --only graph
    python api_generator.py --session-file storage_state.json   # fresh cookies
    python api_generator.py --impersonate safari17_0

Search / investigate one or more inputs (entity, address, ENS, token):
    python api_generator.py search tornado\ cash 0x722122dF12D4e14e13Ac3b6895a86e84145b6967
    python api_generator.py search --from-file targets.txt --limit 10
    python api_generator.py search tornado-cash --no-details --json

Session handling:
    * first run without cookies, or 401/403 (expired / captcha) -> real Chrome opens
      so you can log in and solve the captcha; the client then retries automatically.
    * `python api_generator.py login` only logs in and saves storage_state.json.
    * `--no-auto-login` disables the browser, `--login-timeout 900` waits longer.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


def _sibling_venv_python() -> Path | None:
    """Project-local .venv interpreter, if this script is run with another python."""
    here = Path(__file__).resolve().parent
    venv_root = here / ".venv"
    try:
        if Path(sys.prefix).resolve() == venv_root.resolve():
            return None  # already running inside the project venv
    except OSError:
        pass
    for candidate in (
        venv_root / "bin" / "python",
        venv_root / "Scripts" / "python.exe",
    ):
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


try:  # Chrome-like TLS fingerprint: required to pass Cloudflare
    from curl_cffi import requests as http
except ImportError:  # pragma: no cover - fallback
    _venv_python = _sibling_venv_python()
    if _venv_python and os.environ.get("ARKM_NO_REEXEC") != "1":
        # The user ran `python api_generator.py` instead of the project venv:
        # switch to the interpreter that has curl_cffi + playwright installed.
        os.environ["ARKM_NO_REEXEC"] = "1"
        os.execv(str(_venv_python), [str(_venv_python), *sys.argv])

    import requests as http  # type: ignore[no-redef]

    print(
        "warning: curl_cffi is missing -> Cloudflare will answer 403.\n"
        "  fix: pip install curl_cffi playwright\n"
        "       playwright install chrome",
        file=sys.stderr,
    )

GENERATED_AT = "2026-10-21T14:26:53+00:00"
CAPTURE_SOURCE = "https://arkm.com/visualizer"

# Captured specs are stored as JSON so arbitrary quotes/bodies cannot break the module.
_CAPTURE: dict[str, Any] = json.loads(
    r"""
{
  "requests": [
    {
      "label": "GET /entitlements",
      "method": "GET",
      "url": "https://api.arkm.com/entitlements",
      "headers": {
        "x-payload": "c5b6fd86a6af0efca7f70ea5cbef95458974e46435b1eca8b9be7d2943f180ab",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588438"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /user/recent_searches",
      "method": "GET",
      "url": "https://api.arkm.com/user/recent_searches",
      "headers": {
        "x-payload": "2911498598df0cf2ffb7c7a6bd13c8ddbc61950178fae35603ce21ee583e2126",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588314"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /intelligence/search",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/search?query=&arkhamEntities=15&arkhamAddresses=15&userEntities=15&userAddresses=15&ens=15&types=15&services=15&twitter=15&opensea=15&pumpfun=15&fomo=15&tokens=15&pools=15&tags=15&polymarketEvents=15",
      "headers": {
        "x-payload": "d199aa52cfff2d68f252b5d2ca72de8d37425cb1a79e240f62ac796620b7fd3d",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588314"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /important_entities_enriched",
      "method": "GET",
      "url": "https://api.arkm.com/important_entities_enriched",
      "headers": {
        "x-payload": "3259ef4a4f8cdec8e7eb7d26ecb8b602ce283f7850d0572e73ba4c44da1ba72f",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588311"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /token/arkham_exchange_tokens",
      "method": "GET",
      "url": "https://api.arkm.com/token/arkham_exchange_tokens",
      "headers": {
        "x-payload": "02f8257b4e1ab4de7679e094f7115d4932ee52ed661c631644059b2acfdbdbc9",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588311"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /turnkey/wallet",
      "method": "GET",
      "url": "https://api.arkm.com/turnkey/wallet",
      "headers": {
        "x-payload": "db71dcca9a725080c0ada171d69050f0567b13d6b9ba6d24b999adeadcbf6713",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588314"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /transfers",
      "method": "GET",
      "url": "https://api.arkm.com/transfers?base=all&flow=all&usdGte=1&sortKey=time&sortDir=desc&limit=23&offset=0",
      "headers": {
        "x-payload": "5ad536f945edf07448f2b28d5c49681cf69e1f37b415b556413e28fad777b9ca",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588311"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /balances/entity/ftx",
      "method": "GET",
      "url": "https://api.arkm.com/balances/entity/ftx?cheap=true",
      "headers": {
        "x-payload": "5d0953b13eb427a66e7f80ad28f23365b6d12f39b201dc1d01357ae432e3f033",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /balances/entity/el-salvador",
      "method": "GET",
      "url": "https://api.arkm.com/balances/entity/el-salvador?cheap=true",
      "headers": {
        "x-payload": "5c97426fe2637777a089e5d5172becc74fbe62c52199287dfb1632642cefe69d",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /balances/entity/worldlibertyfi",
      "method": "GET",
      "url": "https://api.arkm.com/balances/entity/worldlibertyfi?cheap=true",
      "headers": {
        "x-payload": "4d5d0666f54f0315630a9d5dd1cfdbbaaf759b6a9e9d4063570539d6acdb2af8",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /balances/entity/wisdomtree",
      "method": "GET",
      "url": "https://api.arkm.com/balances/entity/wisdomtree?cheap=true",
      "headers": {
        "x-payload": "5cb60bd007925a4ad0a91431d881c7ac53624e00f62e20cb13f4a4f5a8a579da",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /balances/entity/central-bank-of-iran",
      "method": "GET",
      "url": "https://api.arkm.com/balances/entity/central-bank-of-iran?cheap=true",
      "headers": {
        "x-payload": "ff852d6a11c864737c3b271305107408c21f451f4b354b44c33f85752803bbb3",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /balances/entity/liberland",
      "method": "GET",
      "url": "https://api.arkm.com/balances/entity/liberland?cheap=true",
      "headers": {
        "x-payload": "f1f45d955d94673156c6d8f80b46d80fcdd8ba96edca3e0ae5498d8e2caebfcd",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /intelligence/entity/ftx/summary",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/entity/ftx/summary",
      "headers": {
        "x-payload": "81a890a5776a525608eb4ac6cb8c05d2a3e31663af18f68ff7c5639ff3af8914",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /intelligence/entity/el-salvador/summary",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/entity/el-salvador/summary",
      "headers": {
        "x-payload": "8ba0d026064cc28a7137afd52e1f606776fd7adc3be9c3ab930016cce89fbecf",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /intelligence/entity/worldlibertyfi/summary",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/entity/worldlibertyfi/summary",
      "headers": {
        "x-payload": "f1431251cbdd941c2ee1187a3f93b70cd3393733963d8362f84b78a27b9314f3",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /intelligence/entity/wisdomtree/summary",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/entity/wisdomtree/summary",
      "headers": {
        "x-payload": "847943409ca6de29bbe87a91477abf2e738522799c478a2c8830349551a57a36",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /intelligence/entity/central-bank-of-iran/summary",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/entity/central-bank-of-iran/summary",
      "headers": {
        "x-payload": "51c7730287621e8814ae6848aeb51cf2dd33f57cb58e62b36be1a72b227cdb50",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /intelligence/entity/liberland/summary",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/entity/liberland/summary",
      "headers": {
        "x-payload": "7563123ea9b7229743e640c1e9ead7e359e8454f7bd829638dbf8d97f6b63532",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /intelligence/token/bitcoin",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/token/bitcoin",
      "headers": {
        "x-payload": "092404bef660665c3d6e55ed056ab18f96adc97e61d8ed8a851e33476940ca01",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /token/market/bitcoin",
      "method": "GET",
      "url": "https://api.arkm.com/token/market/bitcoin",
      "headers": {
        "x-payload": "2d02e836289bbb6b433699442344e75b15794e69c739c7bb14bc9527f91d6e1b",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /token/price/history/bitcoin",
      "method": "GET",
      "url": "https://api.arkm.com/token/price/history/bitcoin?daily=false",
      "headers": {
        "x-payload": "0870d92cd641e41f907fe4fda3a026f1259770e4bc092fbfb8fc97b3fb3fc7d9",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /token/market/price/bitcoin/0",
      "method": "GET",
      "url": "https://api.arkm.com/token/market/price/bitcoin/0?index=0",
      "headers": {
        "x-payload": "4192b5739528393400455cc05bee1a919c8f46be862b97ff40fb36715c0a03af",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/entity/el-salvador.json",
      "method": "GET",
      "url": "https://arkm.com/_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/entity/el-salvador.json?entity=el-salvador",
      "headers": {
        "referer": "https://arkm.com/",
        "purpose": "prefetch",
        "x-nextjs-data": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/entity/worldlibertyfi.json",
      "method": "GET",
      "url": "https://arkm.com/_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/entity/worldlibertyfi.json?entity=worldlibertyfi",
      "headers": {
        "referer": "https://arkm.com/",
        "purpose": "prefetch",
        "x-nextjs-data": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/0xCDCCCD0f2D86E450d973dA415ad2430e5CC7935A/summary/pnl",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/0xCDCCCD0f2D86E450d973dA415ad2430e5CC7935A/summary/pnl",
      "headers": {
        "x-payload": "6e524ed56cc2c131e8bd29896d2c14325687f238672df2e14f0a5dc752e5980c",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/0x7c37b52Eb226Bcb9411375Ec48b0169663FB6aEb/summary/pnl",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/0x7c37b52Eb226Bcb9411375Ec48b0169663FB6aEb/summary/pnl",
      "headers": {
        "x-payload": "87f9d4805b71d2644bca2de43fa6cf9c3086220455c3359358d8fa8cbc1acc57",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/0xf0318C32136c2dB7feC88B84869aEE6A1106C80c/summary/pnl",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/0xf0318C32136c2dB7feC88B84869aEE6A1106C80c/summary/pnl",
      "headers": {
        "x-payload": "b5dc16facac5935837aa7f5521013e844ce745a0b4ff429f330d5fd67b83bae7",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/0x918B42A06Ff25EAAA4a79eCA9DA6a9De46f4Ea63/summary/pnl",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/0x918B42A06Ff25EAAA4a79eCA9DA6a9De46f4Ea63/summary/pnl",
      "headers": {
        "x-payload": "b7aff5ba61378242de4df6a18e71ecff4987809777fcde994fe7d9736c1adb19",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/0xCDCCCD0f2D86E450d973dA415ad2430e5CC7935A/prediction-history",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/0xCDCCCD0f2D86E450d973dA415ad2430e5CC7935A/prediction-history?sort=pnl&order=desc&limit=4",
      "headers": {
        "x-payload": "551f85c3ccf4f32a45b1bdaf6dc96954eb935faeeea248429169fa63f8191e5b",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/0x7c37b52Eb226Bcb9411375Ec48b0169663FB6aEb/prediction-history",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/0x7c37b52Eb226Bcb9411375Ec48b0169663FB6aEb/prediction-history?sort=pnl&order=desc&limit=4",
      "headers": {
        "x-payload": "390ec82fe6512bb89a72591d14ad8fd47ac3be0b19a347a606642d7dfc964079",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/0xf0318C32136c2dB7feC88B84869aEE6A1106C80c/prediction-history",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/0xf0318C32136c2dB7feC88B84869aEE6A1106C80c/prediction-history?sort=pnl&order=desc&limit=4",
      "headers": {
        "x-payload": "cffc6f79823360fadc74c632d9338bee7a15c794c8045c30310d1ff5d88cd497",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/0x918B42A06Ff25EAAA4a79eCA9DA6a9De46f4Ea63/prediction-history",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/0x918B42A06Ff25EAAA4a79eCA9DA6a9De46f4Ea63/prediction-history?sort=pnl&order=desc&limit=4",
      "headers": {
        "x-payload": "4b8e091bb0565c76023f2be4716758c032bc97c9cfd9a5b5c4fb836f5d569d4c",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/resolve-names",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/resolve-names?addresses=0x7c37b52Eb226Bcb9411375Ec48b0169663FB6aEb&addresses=0x918B42A06Ff25EAAA4a79eCA9DA6a9De46f4Ea63&addresses=0xCDCCCD0f2D86E450d973dA415ad2430e5CC7935A&addresses=0xf0318C32136c2dB7feC88B84869aEE6A1106C80c",
      "headers": {
        "x-payload": "9676fbec8d62fd8cdabed8f45533ce46078ccd39cce57231aec1d9a5015984da",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/token/bitcoin.json",
      "method": "GET",
      "url": "https://arkm.com/_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/token/bitcoin.json?token=bitcoin",
      "headers": {
        "referer": "https://arkm.com/",
        "purpose": "prefetch",
        "x-nextjs-data": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/entity/binance.json",
      "method": "GET",
      "url": "https://arkm.com/_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/entity/binance.json?entity=binance",
      "headers": {
        "referer": "https://arkm.com/",
        "purpose": "prefetch",
        "x-nextjs-data": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/entity/bitget.json",
      "method": "GET",
      "url": "https://arkm.com/_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/entity/bitget.json?entity=bitget",
      "headers": {
        "referer": "https://arkm.com/",
        "purpose": "prefetch",
        "x-nextjs-data": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/entity/relay-link.json",
      "method": "GET",
      "url": "https://arkm.com/_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/entity/relay-link.json?entity=relay-link",
      "headers": {
        "referer": "https://arkm.com/",
        "purpose": "prefetch",
        "x-nextjs-data": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/0xa38A455bbdD4b68486548B7E19da99903f4f821D/summary/pnl",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/0xa38A455bbdD4b68486548B7E19da99903f4f821D/summary/pnl",
      "headers": {
        "x-payload": "bab75c815c8c767b0a7258c3875f96ec8758027b2bcc2ce6b8ebff2a57d821b4",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/0xa38A455bbdD4b68486548B7E19da99903f4f821D/prediction-history",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/0xa38A455bbdD4b68486548B7E19da99903f4f821D/prediction-history?sort=pnl&order=desc&limit=4",
      "headers": {
        "x-payload": "541e369ebf1d272315e72d8fe065202e0d335bc199d9d13beedd48964c708a9c",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /polymarket/wallet/resolve-names",
      "method": "GET",
      "url": "https://api.arkm.com/polymarket/wallet/resolve-names?addresses=0x7c37b52Eb226Bcb9411375Ec48b0169663FB6aEb&addresses=0x918B42A06Ff25EAAA4a79eCA9DA6a9De46f4Ea63&addresses=0xCDCCCD0f2D86E450d973dA415ad2430e5CC7935A&addresses=0xa38A455bbdD4b68486548B7E19da99903f4f821D&addresses=0xf0318C32136c2dB7feC88B84869aEE6A1106C80c",
      "headers": {
        "x-payload": "9676fbec8d62fd8cdabed8f45533ce46078ccd39cce57231aec1d9a5015984da",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588312"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /visualizer/v2/all",
      "method": "GET",
      "url": "https://api.arkm.com/visualizer/v2/all",
      "headers": {
        "x-payload": "0ed7e4313d9a15d4d6b9ecd388129a7d7d956cb1c174528826c35316ef5de069",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588314"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /intelligence/search",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/search?query=t",
      "headers": {
        "x-payload": "291579eed9f80b0d43b858d0d33c0bfe307c1dd57ac91a4111920c9326ea2dcc",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588433"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": null
    },
    {
      "label": "GET /intelligence/search",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/search?query=to",
      "headers": {
        "x-payload": "291579eed9f80b0d43b858d0d33c0bfe307c1dd57ac91a4111920c9326ea2dcc",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588433"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": null
    },
    {
      "label": "GET /intelligence/search",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/search?query=tor",
      "headers": {
        "x-payload": "291579eed9f80b0d43b858d0d33c0bfe307c1dd57ac91a4111920c9326ea2dcc",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588433"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": null
    },
    {
      "label": "GET /intelligence/search",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/search?query=torn",
      "headers": {
        "x-payload": "67d44cd631352f8c11ec966df260d26a38aa0fd189e1b710afc6390709b04927",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588434"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": null
    },
    {
      "label": "GET /intelligence/search",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/search?query=torna",
      "headers": {
        "x-payload": "67d44cd631352f8c11ec966df260d26a38aa0fd189e1b710afc6390709b04927",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588434"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": null
    },
    {
      "label": "GET /intelligence/search",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/search?query=tornad",
      "headers": {
        "x-payload": "67d44cd631352f8c11ec966df260d26a38aa0fd189e1b710afc6390709b04927",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588434"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": null
    },
    {
      "label": "GET /intelligence/search",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/search?query=tornado",
      "headers": {
        "x-payload": "67d44cd631352f8c11ec966df260d26a38aa0fd189e1b710afc6390709b04927",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588434"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /_next/data/WxNNN3Ic68lfhzjRRoZyF/visualizer/scratch.json",
      "method": "GET",
      "url": "https://arkm.com/_next/data/WxNNN3Ic68lfhzjRRoZyF/visualizer/scratch.json?base=tornado-cash",
      "headers": {
        "referer": "https://arkm.com/visualizer",
        "x-nextjs-data": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /intelligence/entity/tornado-cash",
      "method": "GET",
      "url": "https://api.arkm.com/intelligence/entity/tornado-cash",
      "headers": {
        "x-payload": "a8332a71751892e2736d83caea89a2366c5666385b0dec42f78c9d99a137e44a",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588438"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /transfers",
      "method": "GET",
      "url": "https://api.arkm.com/transfers?base=tornado-cash&flow=all&usdGte=1&sortKey=time&sortDir=desc&limit=100&offset=0",
      "headers": {
        "x-payload": "dccd4308767941fc8ac516e4582074580eb9c47e18983be437c7c33cfc1b90be",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588438"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "GET /user/entities/is_not_viewable",
      "method": "GET",
      "url": "https://api.arkm.com/user/entities/is_not_viewable?entityIDs=tornado-cash",
      "headers": {
        "x-payload": "12adbfa6ecf005c4d0068a813d4b24a6fae59c2a53f060e67765bfab2a2acc1f",
        "referer": "https://arkm.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "x-timestamp": "1792588438"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    },
    {
      "label": "POST /api/consent",
      "method": "POST",
      "url": "https://api.arkm.com/api/consent",
      "headers": {
        "x-payload": "11a4588febd2a5bdf995ae742ea24c951a99aaf66df308329dace75601cef6ad",
        "referer": "https://arkm.com/",
        "x-timestamp": "1792588438",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "content-type": "application/json"
      },
      "body": "{\"analytics\":true,\"marketing\":true}",
      "body_json": {
        "analytics": true,
        "marketing": true
      },
      "status_in_capture": 200
    },
    {
      "label": "GET /_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/token/ethereum.json",
      "method": "GET",
      "url": "https://arkm.com/_next/data/WxNNN3Ic68lfhzjRRoZyF/explorer/token/ethereum.json?token=ethereum",
      "headers": {
        "referer": "https://arkm.com/visualizer/scratch?base=tornado-cash",
        "purpose": "prefetch",
        "x-nextjs-data": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
      },
      "body": null,
      "body_json": null,
      "status_in_capture": 200
    }
  ],
  "cookies": {},
  "client_key": "gh67j345kl6hj5k432",
  "generated_at": "2026-10-21T14:26:53+00:00",
  "source": "https://arkm.com/visualizer"
}
"""
)

REQUESTS: list[dict[str, Any]] = _CAPTURE.get("requests") or []
COOKIES: dict[str, str] = _CAPTURE.get("cookies") or {}
CLIENT_KEY: str = _CAPTURE.get("client_key") or ""

OUT_DIR = Path(__file__).resolve().parent / "api_output"
DEFAULT_IMPERSONATE = "chrome"
DEFAULT_LOGIN_URL = "https://arkm.com/login"
DEFAULT_LOGIN_TIMEOUT = 600.0
DEFAULT_PROFILE_DIR = Path(__file__).resolve().parent / "chrome_profile"
DEFAULT_STORAGE_FILE = Path(__file__).resolve().parent / "storage_state.json"
SESSION_COOKIE_NAME = "arkham_session"

# Search endpoint template + headers taken from the capture (query is replaced per term).
_SEARCH_SPEC = next((spec for spec in REQUESTS if "/intelligence/search" in spec["url"]), None)
SEARCH_URL = (
    _SEARCH_SPEC["url"]
    if _SEARCH_SPEC
    else "https://api.arkm.com/intelligence/search?query=&arkhamEntities=15&arkhamAddresses=15"
)
SEARCH_HEADERS: dict[str, str] = dict(_SEARCH_SPEC["headers"]) if _SEARCH_SPEC else {}
_PARTS = urlsplit(SEARCH_URL)
API_BASE = f"{_PARTS.scheme}://{_PARTS.netloc}"

# Endpoint headers are identical for every api.arkm.com call; borrow the captured set.
_API_HEADERS = next(
    (dict(spec["headers"]) for spec in REQUESTS if "x-payload" in spec.get("headers", {})),
    dict(SEARCH_HEADERS),
)

DROP_HEADERS = {"host", "content-length", "connection", "accept-encoding"}


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def slugify(text: str, limit: int = 60) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", text).strip("_")
    return (cleaned or "request")[:limit]


def response_suffix(content_type: str | None) -> str:
    content_type = (content_type or "").lower()
    if "json" in content_type:
        return ".json"
    if "html" in content_type:
        return ".html"
    if "csv" in content_type:
        return ".csv"
    return ".txt"


def sign_request(url: str, timestamp: str, client_key: str) -> str:
    """sha256(key + ":" + sha256(path + ":" + ts + ":" + key)) - matches the web app."""
    path = urlsplit(url).path
    inner = hashlib.sha256(f"{path}:{timestamp}:{client_key}".encode("utf-8")).hexdigest()
    return hashlib.sha256(f"{client_key}:{inner}".encode("utf-8")).hexdigest()


def money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(number) >= size:
            return f"${number / size:.2f}{unit}"
    return f"${number:,.2f}"


def short_address(value: str | None) -> str:
    if not value:
        return "-"
    return value if len(value) <= 14 else f"{value[:8]}...{value[-6:]}"


def looks_like_address(term: str) -> bool:
    term = term.strip()
    if re.fullmatch(r"0x[a-fA-F0-9]{40}", term):
        return True
    # solana / base58-style addresses (32-44 chars, no 0/O/I/l)
    return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", term))


def arkham_session_ready(path: Path) -> bool:
    """True when path is a Playwright snapshot that contains a usable Arkham session cookie."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    cookies = data.get("cookies") if isinstance(data, dict) else None
    if not isinstance(cookies, list):
        return False
    return any(
        isinstance(cookie, dict)
        and cookie.get("name") == SESSION_COOKIE_NAME
        and cookie.get("value")
        and "arkm.com" in (cookie.get("domain") or "")
        for cookie in cookies
    )


def browser_display_available() -> tuple[bool, str]:
    """A visible login window is possible only in an interactive desktop session."""
    if sys.platform == "darwin":
        if os.environ.get("SSH_CONNECTION") and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        ):
            return False, (
                "This macOS shell is an SSH session with no display. "
                "Run `python3 api_generator.py login` from the desktop itself."
            )
        return True, ""
    if sys.platform.startswith("linux"):
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            return True, ""
        return False, (
            "No DISPLAY or WAYLAND_DISPLAY, so Chrome cannot open a login window. "
            "Run `./run.sh --login` in a desktop session. "
            "Docker, systemd, and SSH without X11 cannot show the browser."
        )
    if sys.platform == "win32":
        if os.environ.get("SESSIONNAME", "").lower() == "services":
            return False, (
                "This Windows session is a service and cannot show a login window. "
                "Run `python api_generator.py login` from an interactive desktop."
            )
        return True, ""
    return True, ""


def installed_login_browser() -> str | None:
    """Path or cache name of a browser Playwright can show for login."""
    candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    roots = [
        Path.home() / "Library" / "Caches" / "ms-playwright",
        Path.home() / ".cache" / "ms-playwright",
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "ms-playwright")
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in ("chromium-*/chrome-mac*/**/Chromium", "chromium-*/chrome-linux*/chrome", "chromium-*/chrome-win*/chrome.exe", "chromium-*/chrome-win*/chrome"):
            if any(root.glob(pattern)):
                return str(root)
    return None


def _missing_browser_binary(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "executable doesn't exist",
            "executable does not exist",
            "please run the following",
            "browser is not installed",
            "failed to find",
        )
    )


def _is_auth_page(url: str) -> bool:
    path = (urlsplit(url).path or "").lower()
    return any(token in path for token in ("/login", "/signin", "/auth", "/challenge"))


async def _has_password_field(page: Any) -> bool:
    try:
        return await page.locator('input[type="password"]').count() > 0
    except Exception:
        return False


async def _wait_for_manual_login(page: Any, context: Any, timeout: float) -> bool:
    """Wait until a real `arkham_session` cookie exists (login / captcha solved)."""
    interactive = False
    try:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        interactive = False

    if interactive:
        try:
            await asyncio.to_thread(
                input,
                "\n>>> Chrome is open. Log in (and solve any captcha), then press Enter... ",
            )
        except EOFError:
            interactive = False

    log("waiting for a valid arkm session in the browser (login / captcha)...")
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            cookies = await context.cookies()
        except Exception:
            log("browser window was closed")
            return False

        has_session = any(
            cookie.get("name") == SESSION_COOKIE_NAME
            and "arkm.com" in (cookie.get("domain") or "")
            and cookie.get("value")
            for cookie in cookies
        )
        try:
            on_auth_page = _is_auth_page(page.url)
            has_password = await _has_password_field(page)
        except Exception:
            log("browser window was closed")
            return False

        if has_session and not on_auth_page and not has_password:
            return True
        await asyncio.sleep(2)

    log("login timeout reached")
    return False


async def _browser_login(
    login_url: str,
    profile_dir: Path,
    storage_file: Path,
    timeout: float,
) -> dict[str, str] | None:
    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError:
        log("playwright is not installed: pip install playwright && playwright install chrome")
        return None

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
    ]
    common: dict[str, Any] = {
        "headless": False,
        "args": launch_args,
        "ignore_default_args": ["--enable-automation"],
        "no_viewport": True,
    }
    profile_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        try:
            context = await playwright.chromium.launch_persistent_context(
                str(profile_dir), channel="chrome", **common
            )
        except Exception as exc:
            if not _missing_browser_binary(exc):
                log(f"could not open a visible browser: {type(exc).__name__}: {exc}")
                return None
            log(f"Google Chrome is not installed ({exc}); trying bundled Chromium")
            try:
                context = await playwright.chromium.launch_persistent_context(
                    str(profile_dir), **common
                )
            except Exception as chromium_exc:
                log(
                    "could not open Chromium either: "
                    f"{type(chromium_exc).__name__}: {chromium_exc}. "
                    "Install Google Chrome, or run `playwright install chromium` "
                    "on a machine with a desktop session."
                )
                return None

        try:
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(login_url, wait_until="domcontentloaded", timeout=90_000)
            except Exception as exc:
                log(f"  navigation warning: {type(exc).__name__}")
            await page.bring_to_front()

            if not await _wait_for_manual_login(page, context, timeout):
                return None

            state = await context.storage_state()
            storage_file.parent.mkdir(parents=True, exist_ok=True)
            storage_file.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            try:
                storage_file.chmod(0o600)
            except OSError as exc:
                log(f"could not restrict permissions on {storage_file.name}: {exc}")
            cookies = {
                cookie["name"]: cookie["value"]
                for cookie in state.get("cookies", [])
                if "arkm.com" in (cookie.get("domain") or "")
            }
            log(f"session saved -> {storage_file.name} ({len(cookies)} cookies)")
            return cookies
        finally:
            try:
                await context.close()
            except Exception:
                pass


def browser_login(
    login_url: str = DEFAULT_LOGIN_URL,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    storage_file: Path = DEFAULT_STORAGE_FILE,
    timeout: float = DEFAULT_LOGIN_TIMEOUT,
) -> dict[str, str] | None:
    """Open real Chrome, let the user log in / solve a captcha, return fresh cookies."""
    available, reason = browser_display_available()
    if not available:
        log(reason)
        return None
    try:
        return asyncio.run(_browser_login(login_url, profile_dir, storage_file, timeout))
    except KeyboardInterrupt:
        log("login interrupted")
        return None
    except Exception as exc:
        log(f"browser login failed: {type(exc).__name__}: {exc}")
        return None


def describe_item(group: str, item: Any) -> str:
    """Human-readable one-liner for a search-result entry."""
    if not isinstance(item, dict):
        return str(item)[:140]

    if group in ("arkhamEntities", "twitter", "services"):
        bits = [str(item.get("name") or item.get("username") or "-")]
        if item.get("id"):
            bits.append(f"id={item['id']}")
        if item.get("type"):
            bits.append(f"type={item['type']}")
        if item.get("twitter"):
            bits.append(f"@{item['twitter']}")
        return "  ".join(bits)

    if group in ("arkhamAddresses", "opensea", "pumpfun", "fomo", "polymarketWallets"):
        bits = [str(item.get("address") or "-")]
        if item.get("chain"):
            bits.append(f"[{item['chain']}]")
        entity = (item.get("arkhamEntity") or {}).get("name")
        label = (item.get("arkhamLabel") or {}).get("name")
        if entity:
            bits.append(f"- {entity}")
        if label:
            bits.append(f"/ {label}")
        if item.get("username"):
            bits.append(f"(@{item['username']})")
        return " ".join(bits)

    if group == "ens":
        return f"{item.get('name')} -> {item.get('address')}"

    if group == "tokens":
        identifier = (item.get("identifier") or {}).get("pricingID")
        return (
            f"{item.get('name')} ({item.get('symbol')})"
            f" price={money(item.get('price'))} id={identifier or '-'}"
        )

    for key in ("name", "title", "label", "address", "id"):
        if item.get(key):
            return str(item[key])
    return json.dumps(item, ensure_ascii=False)[:140]


def build_url(base: str, overrides: dict[str, Any]) -> str:
    """Keep the captured query params, replace/append the given ones."""
    parts = urlsplit(base)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in overrides
    ]
    query.extend((key, str(value)) for key, value in overrides.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class ReplayClient:
    """Sequential replayer with fresh signing, retries and polite rate limiting."""

    def __init__(
        self,
        *,
        delay: float = 1.0,
        jitter: float = 0.5,
        retries: int = 5,
        timeout: float = 45.0,
        out_dir: Path = OUT_DIR,
        session_file: str | None = None,
        impersonate: str | None = DEFAULT_IMPERSONATE,
        client_key: str | None = None,
        auto_login: bool = True,
        login_url: str = DEFAULT_LOGIN_URL,
        login_timeout: float = DEFAULT_LOGIN_TIMEOUT,
        profile_dir: Path = DEFAULT_PROFILE_DIR,
        storage_file: Path = DEFAULT_STORAGE_FILE,
    ) -> None:
        if delay < 0:
            raise ValueError("delay must be >= 0")
        self.delay = delay
        self.jitter = max(0.0, jitter)
        self.retries = max(1, retries)
        self.timeout = timeout
        self.out_dir = Path(out_dir)
        self.impersonate = impersonate
        self.client_key = client_key if client_key is not None else CLIENT_KEY
        self.cookies: dict[str, str] = dict(COOKIES)
        self.cookie_override: str | None = None
        self.auth_failed = False
        self.cloudflare_blocked = False
        self.session = http.Session()

        self.auto_login = auto_login and os.environ.get("ARKM_NO_AUTO_LOGIN") != "1"
        self.login_url = login_url
        self.login_timeout = login_timeout
        self.profile_dir = Path(profile_dir)
        self.storage_file = Path(storage_file)
        self.reauth_count = 0
        self.max_reauths = 3
        self.auth_dead = False

        # A previously refreshed session beats the cookies baked into this file.
        target = Path(session_file) if session_file else self.storage_file
        if target.exists():
            self.load_storage_state(target)
        elif not self.cookies:
            log("no session cookies found - a Chrome login window will open")

    # -- session -----------------------------------------------------------
    def reauthorize(self, reason: str) -> bool:
        """Open Chrome for manual login / captcha, then swap in the fresh cookies."""
        if not self.auto_login or self.auth_dead:
            return False
        if self.reauth_count >= self.max_reauths:
            log("too many login attempts - giving up on automatic re-auth")
            self.auth_dead = True
            return False

        self.reauth_count += 1
        log(f"session needs refresh ({reason}) -> opening Chrome")
        cookies = browser_login(
            self.login_url,
            self.profile_dir,
            self.storage_file,
            self.login_timeout,
        )
        if not cookies:
            self.auth_dead = True
            log("no session obtained; remaining requests will fail fast "
                "(try again without --no-auto-login)")
            return False

        self.cookies = cookies
        self.cookie_override = "; ".join(f"{name}={value}" for name, value in cookies.items())
        self.auth_failed = False
        self.cloudflare_blocked = False
        return True

    def load_storage_state(self, path: Path) -> None:
        """Import cookies from a Playwright storage_state.json snapshot."""
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log(f"could not read session file {path}: {exc}")
            return

        collected: dict[str, str] = {}
        for cookie in state.get("cookies", []):
            name, value = cookie.get("name"), cookie.get("value")
            domain = cookie.get("domain") or ""
            if not name or value is None or "arkm.com" not in domain:
                continue
            collected[name] = value
        if not collected:
            log(f"no arkm.com cookies found in {path.name}")
            return
        self.cookies = collected
        self.cookie_override = "; ".join(f"{name}={value}" for name, value in collected.items())
        log(f"loaded {len(collected)} arkm.com cookie(s) from {path.name}")

    # -- plumbing ----------------------------------------------------------
    def _headers(self, spec: dict[str, Any]) -> dict[str, str]:
        headers = {
            name: value
            for name, value in (spec.get("headers") or {}).items()
            if name.lower() not in DROP_HEADERS and not name.startswith(":")
        }

        cookie_header = self.cookie_override or headers.get("cookie") or ""
        if not cookie_header and self.cookies:
            cookie_header = "; ".join(f"{name}={value}" for name, value in self.cookies.items())
        if cookie_header:
            headers["cookie"] = cookie_header
        else:
            headers.pop("cookie", None)

        lowered = {name.lower() for name in headers}
        if self.client_key and ("x-payload" in lowered or "x-timestamp" in lowered):
            timestamp = str(int(time.time()))
            headers["x-timestamp"] = timestamp
            headers["x-payload"] = sign_request(spec["url"], timestamp, self.client_key)

        return headers

    def _prepare(self, spec: dict[str, Any]) -> dict[str, Any]:
        headers = self._headers(spec)
        kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": self.timeout,
            "allow_redirects": True,
        }
        body_json = spec.get("body_json")
        raw_body = spec.get("body")
        if body_json is not None:
            kwargs["json"] = body_json
            if not any(name.lower() == "content-type" for name in headers):
                headers["content-type"] = "application/json"
        elif raw_body:
            kwargs["data"] = raw_body.encode("utf-8")
        return kwargs

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        if self.impersonate:
            try:
                return self.session.request(
                    method, url, impersonate=self.impersonate, **kwargs
                )
            except TypeError:  # backend without impersonate support
                self.impersonate = None
        return self.session.request(method, url, **kwargs)

    def _sleep_between(self) -> None:
        pause = self.delay + random.uniform(0, self.jitter)
        if pause > 0:
            time.sleep(pause)

    def _backoff(self, attempt: int, response: Any) -> None:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                sleep_sec = min(120, max(2, int(retry_after)))
                log(f"  ⏳ Rate limit: respecting Retry-After header -> sleeping {sleep_sec}s...")
                time.sleep(sleep_sec)
                return
            if response.status_code == 429:
                sleep_sec = min(90.0, (6.0 * attempt) + random.uniform(2.0, 5.0))
                log(f"  ⏳ HTTP 429 Rate limit: backing off for {sleep_sec:.1f}s before retry {attempt+1}...")
                time.sleep(sleep_sec)
                return
        time.sleep(min(60.0, (2 ** attempt) + random.uniform(0.5, 2.0)))

    def _send(self, spec: dict[str, Any]) -> Any:
        method = str(spec.get("method", "GET")).upper()
        url = spec["url"]

        for attempt in range(1, self.retries + 1):
            # Enforce polite delay between requests to avoid burst rate limiting
            self._sleep_between()

            try:
                response = self._request(method, url, **self._prepare(spec))
            except Exception as exc:  # network / TLS / DNS
                log(f"  ! attempt {attempt}/{self.retries} failed: {type(exc).__name__}: {exc}")
                if attempt == self.retries:
                    return None
                self._backoff(attempt, None)
                continue

            if response.status_code in (401, 403):
                body = (response.text or "")[:400].lower()
                blocked = (
                    "cloudflare" in body
                    or response.headers.get("server", "").lower() == "cloudflare"
                )
                if blocked:
                    self.cloudflare_blocked = True
                    log(f"  ! Cloudflare {response.status_code} - challenge / TLS rejected")
                else:
                    self.auth_failed = True
                    log(f"  ! auth rejected ({response.status_code}) - session expired")

                if self.auto_login and not self.auth_dead and attempt < self.retries:
                    reason = "Cloudflare challenge" if blocked else f"HTTP {response.status_code}"
                    if self.reauthorize(reason):
                        log("  -> retrying with the fresh session")
                        continue
                return response

            if response.status_code == 429 or 500 <= response.status_code < 600:
                log(f"  ! HTTP {response.status_code}, retrying ({attempt}/{self.retries})")
                if attempt == self.retries:
                    return response
                self._backoff(attempt, response)
                continue

            return response

        return None

    def _save(self, index: int, spec: dict[str, Any], response: Any) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        name = slugify(f"{index:02d}_{spec.get('method', 'GET')}_{spec['url'].split('?')[0]}")
        suffix = response_suffix(response.headers.get("content-type"))
        path = self.out_dir / f"{name}{suffix}"
        try:
            if suffix == ".json":
                try:
                    payload = response.json()
                except ValueError:
                    path = path.with_suffix(".txt")
                    path.write_text(response.text, encoding="utf-8")
                else:
                    path.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
            else:
                path.write_text(response.text, encoding="utf-8")
        except OSError as exc:
            log(f"  ! could not save {path.name}: {exc}")
        return path

    # -- search / investigate ----------------------------------------------
    def fetch_json(self, url: str, headers: dict[str, str] | None = None) -> Any | None:
        spec = {
            "method": "GET",
            "url": url,
            "headers": headers if headers is not None else _API_HEADERS,
            "body": None,
            "body_json": None,
        }
        response = self._send(spec)
        if response is None:
            return None
        if not 200 <= response.status_code < 400:
            log(f"  ! {response.status_code} {urlsplit(url).path}")
            return None
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _save_json(folder: Path, name: str, data: Any) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def search(
        self,
        terms: list[str],
        *,
        limit: int = 5,
        details: bool = True,
        chain: str = "ethereum",
        raw_json: bool = False,
        all_groups: bool = False,
    ) -> None:
        self._ensure_session()

        for term in terms:
            print(f"\n=== {term} ===")
            data = self.fetch_json(build_url(SEARCH_URL, {"query": term}), SEARCH_HEADERS)
            if data is None:
                log("  search failed")
                continue

            folder = self.out_dir / "queries" / slugify(term)
            self._save_json(folder, "01_search.json", data)

            if raw_json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                self._print_groups(data, limit, all_groups)

            if details:
                self._investigate(term, data, folder, chain)
            log(f"saved -> {folder}")

    @staticmethod
    def _print_groups(data: dict[str, Any], limit: int, all_groups: bool = False) -> None:
        preferred = (
            ["arkhamEntities", "arkhamAddresses", "ens", "tokens"]
            if not all_groups
            else ["arkhamEntities", "arkhamAddresses", "ens", "tokens", "services"]
        )
        groups = [key for key in preferred if isinstance(data.get(key), list) and data[key]]
        if all_groups:
            groups += [
                key
                for key, value in data.items()
                if isinstance(value, list) and value and key not in groups
            ]
        for key in groups:
            print(f"  {key}:")
            for item in data[key][:limit]:
                print(f"    - {describe_item(key, item)}")

    def _investigate(
        self, term: str, data: dict[str, Any], folder: Path, chain: str
    ) -> None:
        entities = data.get("arkhamEntities") or []
        addresses = data.get("arkhamAddresses") or []
        tokens = data.get("tokens") or []
        ens = data.get("ens") or []

        exact = next(
            (a for a in addresses if (a.get("address") or "").lower() == term.strip().lower()),
            None,
        )
        if exact:
            self._address_report(exact["address"], exact.get("chain") or chain, folder)
            return

        if looks_like_address(term):
            self._address_report(term.strip(), chain, folder)
            return

        if term.strip().lower().endswith(".eth") and ens:
            hit = next(
                (e for e in ens if (e.get("name") or "").lower() == term.strip().lower()),
                ens[0],
            )
            if hit.get("address"):
                self._address_report(hit["address"], chain, folder)
                return

        if entities:
            self._entity_report(entities[0]["id"], folder)
        elif addresses:
            self._address_report(addresses[0]["address"], addresses[0].get("chain") or chain, folder)
        elif tokens:
            token_id = (tokens[0].get("identifier") or {}).get("pricingID")
            if token_id:
                self._token_report(token_id, folder)

    def _entity_report(self, entity_id: str, folder: Path) -> None:
        ident = quote(entity_id, safe="")
        detail = self.fetch_json(f"{API_BASE}/intelligence/entity/{ident}")
        if detail:
            self._save_json(folder, "02_entity.json", detail)

        summary = self.fetch_json(f"{API_BASE}/intelligence/entity/{ident}/summary")
        if summary:
            self._save_json(folder, "03_entity_summary.json", summary)

        balances = self.fetch_json(f"{API_BASE}/balances/entity/{ident}?cheap=true")
        if balances:
            self._save_json(folder, "04_entity_balances.json", balances)

        transfers = self.fetch_json(
            f"{API_BASE}/transfers?"
            + urlencode(
                {
                    "base": entity_id,
                    "flow": "all",
                    "usdGte": 1,
                    "sortKey": "time",
                    "sortDir": "desc",
                    "limit": 10,
                    "offset": 0,
                }
            )
        )
        if transfers:
            self._save_json(folder, "05_entity_transfers.json", transfers)

        if detail:
            print(f"  entity  : {detail.get('name')} [{detail.get('type')}]  id={detail.get('id')}")
            tags = ", ".join(
                str(tag.get("label", "")) for tag in (detail.get("populatedTags") or [])[:8]
            )
            if tags:
                print(f"  tags    : {tags}")
            if detail.get("website") or detail.get("twitter"):
                print(f"  links   : {detail.get('website') or '-'} | {detail.get('twitter') or '-'}")
        if summary:
            print(
                f"  volume  : {money(summary.get('volumeUsd'))}"
                f"   balance: {money(summary.get('balanceUsd'))}"
            )
            print(
                f"  addrs   : {summary.get('numAddresses')}"
                f"   first/last: {str(summary.get('firstTx') or '-')[:10]}"
                f" / {str(summary.get('lastTx') or '-')[:10]}"
            )
        self._print_balances(balances)
        self._print_transfers(transfers)

    def _address_report(self, address: str, chain: str, folder: Path) -> None:
        ident = quote(address, safe="")
        detail = self.fetch_json(f"{API_BASE}/intelligence/address/{ident}")
        if detail:
            self._save_json(folder, "02_address.json", detail)

        balances = self.fetch_json(f"{API_BASE}/balances/address/{ident}?cheap=true")
        if balances:
            self._save_json(folder, "03_address_balances.json", balances)

        transfers = self.fetch_json(
            f"{API_BASE}/transfers?"
            + urlencode(
                {
                    "base": address,
                    "chain": chain,
                    "flow": "all",
                    "usdGte": 1,
                    "sortKey": "time",
                    "sortDir": "desc",
                    "limit": 10,
                    "offset": 0,
                }
            )
        )
        if transfers:
            self._save_json(folder, "04_address_transfers.json", transfers)

        if detail:
            entity = (detail.get("arkhamEntity") or {}).get("name")
            label = (detail.get("arkhamLabel") or {}).get("name")
            kind = "contract" if detail.get("contract") else "wallet"
            print(f"  address : {detail.get('address')} [{detail.get('chain')}] {kind}")
            if entity or label:
                print(f"  owner   : {entity or '-'} / {label or '-'}")
        self._print_balances(balances)
        self._print_transfers(transfers)

    def _token_report(self, token_id: str, folder: Path) -> None:
        ident = quote(token_id, safe="")
        detail = self.fetch_json(f"{API_BASE}/intelligence/token/{ident}")
        if detail:
            self._save_json(folder, "02_token.json", detail)

        market = self.fetch_json(f"{API_BASE}/token/market/{ident}")
        if market:
            self._save_json(folder, "03_token_market.json", market)

        if detail:
            print(
                f"  token   : {detail.get('name')} ({detail.get('symbol')})"
                f"  price={money(detail.get('price'))}"
            )
        if market:
            print(
                f"  market  : cap={money(market.get('marketCap'))}"
                f"   volume={money(market.get('totalVolume'))}"
                f"   supply={market.get('circulatingSupply')}"
            )

    @staticmethod
    def _print_balances(data: dict[str, Any] | None) -> None:
        totals = (data or {}).get("totalBalance") or {}
        numeric = {
            chain: value
            for chain, value in totals.items()
            if isinstance(value, (int, float)) and value
        }
        ranked = sorted(numeric.items(), key=lambda pair: pair[1], reverse=True)[:5]
        if ranked:
            print("  top     : " + ", ".join(f"{chain} {money(usd)}" for chain, usd in ranked))
        total = sum(numeric.values())
        if total:
            print(f"  total   : {money(total)} across {len(numeric)} chains")

    @staticmethod
    def _print_transfers(data: dict[str, Any] | None) -> None:
        items = (data or {}).get("transfers") or []
        if not items:
            return
        count = (data or {}).get("count")
        print(f"  transfers (latest {len(items)} of {count if count is not None else '?'}):")
        for transfer in items[:5]:
            source = (transfer.get("fromAddress") or {}).get("address")
            target = (transfer.get("toAddress") or {}).get("address")
            print(
                f"    {str(transfer.get('blockTimestamp') or '')[:19]}"
                f" {money(transfer.get('historicalUSD')):>10}"
                f" {str(transfer.get('tokenSymbol') or ''):<6}"
                f" {short_address(source)} -> {short_address(target)}"
            )

    # -- public ------------------------------------------------------------
    def _ensure_session(self) -> None:
        if not self.auto_login or self.auth_dead:
            return
        if self.cookies.get(SESSION_COOKIE_NAME):
            return
        self.reauthorize("no valid arkm session (first run / expired)")

    def run(self, only: str | None = None) -> int:
        self._ensure_session()

        selected = REQUESTS
        if only:
            needle = only.lower()
            selected = [
                spec
                for spec in REQUESTS
                if needle in f"{spec.get('method', '')} {spec['url']}".lower()
            ]
            if not selected:
                log(f"no captured request matches {only!r}")
                return 1

        log(f"replaying {len(selected)} request(s) with {self.delay:.1f}s base delay")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        index: list[dict[str, Any]] = []
        ok = failed = 0

        for position, spec in enumerate(selected, start=1):
            label = spec.get("label") or spec["url"]
            log(f"[{position}/{len(selected)}] {label}")

            response = self._send(spec)
            entry: dict[str, Any] = {
                "index": position,
                "method": spec.get("method"),
                "url": spec["url"],
                "status": None,
                "file": None,
                "error": None,
            }

            if response is None:
                entry["error"] = "request failed after retries"
                failed += 1
            else:
                entry["status"] = response.status_code
                if 200 <= response.status_code < 400:
                    entry["file"] = self._save(position, spec, response).name
                    ok += 1
                else:
                    entry["error"] = f"HTTP {response.status_code}"
                    failed += 1
                log(f"  -> HTTP {response.status_code} ({len(response.content)} bytes)")
            index.append(entry)

        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (self.out_dir / "_index.json").write_text(
            json.dumps(
                {
                    "run_at": stamp,
                    "captured_at": GENERATED_AT,
                    "source": CAPTURE_SOURCE,
                    "ok": ok,
                    "failed": failed,
                    "results": index,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        log(f"done: {ok} ok, {failed} failed -> {self.out_dir}")
        if self.auth_failed:
            log(
                "session expired: log in again in the browser, re-run arkm_capture.py, "
                "then replay the fresh api_generator.py"
            )
        if self.cloudflare_blocked:
            log("install curl_cffi (pip install curl_cffi) or try --impersonate safari17_0")
        return 0 if failed == 0 else 1


def add_login_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-auto-login",
        action="store_true",
        help="never open Chrome automatically on missing/expired session",
    )
    parser.add_argument("--login-url", default=DEFAULT_LOGIN_URL, help="page opened for manual login")
    parser.add_argument(
        "--login-timeout",
        type=float,
        default=DEFAULT_LOGIN_TIMEOUT,
        help="seconds to wait for manual login / captcha",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Chrome profile reused for logins",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay arkm.com API calls captured by arkm_capture.py",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--delay", type=float, default=2.0, help="base sleep between requests (s)")
    parser.add_argument("--jitter", type=float, default=1.0, help="random extra sleep (s)")
    parser.add_argument("--retries", type=int, default=3, help="retries per request")
    parser.add_argument("--timeout", type=float, default=45.0, help="per-request timeout (s)")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output directory")
    parser.add_argument("--session-file", default=None, help="Playwright storage_state.json")
    parser.add_argument("--impersonate", default=DEFAULT_IMPERSONATE, help="curl_cffi TLS profile ('' to disable)")
    parser.add_argument("--client-key", default=None, help="override NEXT_PUBLIC_WEBAPP_CLIENT_KEY")
    parser.add_argument("--only", default=None, help="substring filter on method+url")
    parser.add_argument("--list", action="store_true", help="list captured requests and exit")
    parser.add_argument("--dry-run", action="store_true", help="show requests without sending")
    add_login_args(parser)
    return parser.parse_args(argv)


def parse_search_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="api_generator.py search",
        description="Search arkm.com and pull details for entities / addresses / tokens",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("terms", nargs="*", help="entity name, address, ENS or token")
    parser.add_argument("--from-file", type=Path, help="file with one term per line (# = comment)")
    parser.add_argument("--limit", type=int, default=5, help="results shown per category")
    parser.add_argument("--no-details", action="store_true", help="search only, skip detail endpoints")
    parser.add_argument("--json", action="store_true", dest="raw_json", help="dump raw search JSON")
    parser.add_argument("--all-groups", action="store_true", help="show every result category")
    parser.add_argument("--chain", default="ethereum", help="chain for address transfers")
    parser.add_argument("--delay", type=float, default=2.0, help="base sleep between requests (s)")
    parser.add_argument("--jitter", type=float, default=1.0, help="random extra sleep (s)")
    parser.add_argument("--retries", type=int, default=3, help="retries per request")
    parser.add_argument("--timeout", type=float, default=45.0, help="per-request timeout (s)")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output directory")
    parser.add_argument("--session-file", default=None, help="Playwright storage_state.json")
    parser.add_argument("--impersonate", default=DEFAULT_IMPERSONATE, help="curl_cffi TLS profile")
    parser.add_argument("--client-key", default=None, help="override signing key")
    add_login_args(parser)
    return parser.parse_args(argv)


def read_terms_file(path: Path) -> list[str]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log(f"could not read {path}: {exc}")
        return []
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def search_main(argv: list[str] | None = None) -> int:
    args = parse_search_args(argv)

    terms = list(args.terms)
    if args.from_file:
        terms.extend(read_terms_file(args.from_file))

    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(term)
    if not unique:
        print("nothing to search: pass one or more terms or --from-file FILE")
        return 1

    client = ReplayClient(
        delay=args.delay,
        jitter=args.jitter,
        retries=args.retries,
        timeout=args.timeout,
        out_dir=args.out,
        session_file=args.session_file,
        impersonate=args.impersonate or None,
        client_key=args.client_key,
        auto_login=not args.no_auto_login,
        login_url=args.login_url,
        login_timeout=args.login_timeout,
        profile_dir=args.profile_dir,
    )
    try:
        client.search(
            unique,
            limit=args.limit,
            details=not args.no_details,
            chain=args.chain,
            raw_json=args.raw_json,
            all_groups=args.all_groups,
        )
    except KeyboardInterrupt:
        log("interrupted by user")
        return 130
    return 0


def parse_login_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="api_generator.py login",
        description="Open Chrome once, log in / solve captcha, store fresh cookies",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--login-url", default=DEFAULT_LOGIN_URL)
    parser.add_argument("--login-timeout", type=float, default=DEFAULT_LOGIN_TIMEOUT)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--session-file", type=Path, default=DEFAULT_STORAGE_FILE)
    return parser.parse_args(argv)


def login_main(argv: list[str] | None = None) -> int:
    args = parse_login_args(argv)
    log("opening Chrome for manual login (solve any captcha shown)")
    cookies = browser_login(
        args.login_url, args.profile_dir, args.session_file, args.login_timeout
    )
    if not cookies:
        log("login failed or aborted")
        return 1
    log(f"logged in; {len(cookies)} cookies saved to {args.session_file}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "search":
        return search_main(argv[1:])
    if argv and argv[0] == "login":
        return login_main(argv[1:])

    args = parse_args(argv)

    if not REQUESTS:
        log("no captured requests embedded in this file")
        return 1

    if args.list:
        for position, spec in enumerate(REQUESTS, start=1):
            print(f"{position:02d}. {spec.get('method', 'GET'):4s} {spec['url']}")
        return 0

    if args.dry_run:
        for spec in REQUESTS:
            body = spec.get("body")
            body_note = f" body={len(body)}B" if body else ""
            print(f"{spec.get('method', 'GET'):4s} {spec['url']}{body_note}")
        return 0

    client = ReplayClient(
        delay=args.delay,
        jitter=args.jitter,
        retries=args.retries,
        timeout=args.timeout,
        out_dir=args.out,
        session_file=args.session_file,
        impersonate=args.impersonate or None,
        client_key=args.client_key,
        auto_login=not args.no_auto_login,
        login_url=args.login_url,
        login_timeout=args.login_timeout,
        profile_dir=args.profile_dir,
    )
    try:
        return client.run(only=args.only)
    except KeyboardInterrupt:
        log("interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
