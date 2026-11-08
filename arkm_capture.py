#!/usr/bin/env python3
"""
arkm_capture.py
===============

Capture arkm.com Visualizer API traffic with a real (non-headless) Chrome and
emit a standalone replay client (`api_generator.py`) that uses plain `requests`.

Flow
----
1. Launch real Chrome (channel="chrome"), persistent profile -> Cloudflare friendly.
2. Open the login page and pause on input() so the user can log in by hand
   (username / password / 2FA / captcha). Press Enter when done.
3. Navigate to /visualizer, record requests + responses, filter internal APIs.
4. Press Enter again when finished interacting (search an address, open a graph...).
5. Save:
       captured_requests.json   full capture (headers incl. cookie + payloads + previews)
       storage_state.json       Playwright cookie snapshot (arkham_session, cf_clearance)
       api_generator.py         generated replay client (requests/curl_cffi)

Replay without a browser
------------------------
arkm.com signs every API call in JS (see `constructHeaders` in its bundle):

    X-Timestamp = unix seconds
    X-Payload   = sha256(KEY + ":" + sha256(pathname + ":" + ts + ":" + KEY))
    KEY         = NEXT_PUBLIC_WEBAPP_CLIENT_KEY (public constant)

The generated client re-computes that signature per request and uses
curl_cffi's `impersonate="chrome"` to satisfy Cloudflare's TLS fingerprinting.
A plain `requests` client gets 403 from Cloudflare (and expires signatures).

Rebuild the client from an old capture without opening a browser:

    python arkm_capture.py --regenerate

Notes
-----
* Auth endpoints (login / captcha / otp / mfa) are deliberately NOT captured:
  they cannot be replayed without the human challenge.
* captured_requests.json / storage_state.json / api_generator.py contain live
  cookies -> written with mode 600, never commit them.
* cf_clearance + signatures are time-bound: when replay starts returning 403,
  log in again and re-run the capture.

Usage
-----
    pip install -r requirements.txt
    playwright install chrome
    python arkm_capture.py
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    from playwright.async_api import (
        BrowserContext,
        Page,
        Playwright,
        Request,
        Response,
        async_playwright,
    )
except ModuleNotFoundError:  # pragma: no cover - dependency guard
    sys.exit(
        "playwright is missing.\n"
        "  pip install -r requirements.txt\n"
        "  playwright install chrome"
    )

BASE_DIR = Path(__file__).resolve().parent
CAPTURE_FILE = BASE_DIR / "captured_requests.json"
STORAGE_FILE = BASE_DIR / "storage_state.json"
PROFILE_DIR = BASE_DIR / "chrome_profile"
GENERATED_FILE = BASE_DIR / "api_generator.py"

DEFAULT_LOGIN_URL = "https://arkm.com/login"
DEFAULT_VISUALIZER_URL = "https://arkm.com/visualizer"

# Hosts we consider "internal arkm API".
HOST_SUFFIXES = ("arkm.com", "arkhamintelligence.com")

# URLs that look like internal API / graph traffic.
INCLUDE_PATTERNS = (
    r"/api/",
    r"/graphql",
    r"/trpc",
    r"/v\d+/",
    r"visuali[sz]er",
    r"graph",
    r"search",
    r"cluster",
    r"wallet",
    r"address",
    r"entit",
    r"label",
    r"token",
    r"flow",
    r"transaction",
    r"transfer",
)

# Static assets, analytics and telemetry we never want.
EXCLUDE_PATTERNS = (
    r"\.(?:js|mjs|css|map|png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|otf|mp4|webm|wasm)(?:\?|$)",
    r"(?:google-analytics|googletagmanager|doubleclick|sentry\.io|cloudflareinsights"
    r"|hotjar|segment\.io|mixpanel|amplitude|datadoghq|intercom|fullstory)",
)

# Headers that are either recomputed by requests/httpx or pure browser noise.
DROP_HEADERS = {
    "host",
    "content-length",
    "connection",
    "accept-encoding",
    "priority",
    "dnt",
    "upgrade-insecure-requests",
}
DROP_HEADER_PREFIXES = (":",)  # HTTP/2 pseudo headers

AUTH_URL_RE = re.compile(
    r"/(?:login|logout|signin|signup|register|captcha|otp|mfa|2fa|challenge)(?:[/?#]|$)",
    re.IGNORECASE,
)

# Only real XHR traffic: skips document navigations, scripts, images, beacons.
RECORDED_RESOURCE_TYPES = {"xhr", "fetch"}

RESPONSE_PREVIEW_CHARS = 2000
MAX_BODY_CHARS = 2_000_000
DEFAULT_CAPTURE_SECONDS = 120

# NEXT_PUBLIC_WEBAPP_CLIENT_KEY from arkm.com's JS bundle: public constant used to
# sign every API request. Extracted from _next/static/chunks/0c2cfpcc2i97h.js.
DEFAULT_CLIENT_KEY = "gh67j345kl6hj5k432"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[arkm] {msg}", flush=True)


def is_api_call(url: str) -> bool:
    """True when *url* points at an internal arkm API endpoint we want."""
    host = (urlsplit(url).hostname or "").lower()
    if not any(host == suffix or host.endswith("." + suffix) for suffix in HOST_SUFFIXES):
        return False

    low = url.lower()
    if any(re.search(pattern, low) for pattern in EXCLUDE_PATTERNS):
        return False
    return any(re.search(pattern, low) for pattern in INCLUDE_PATTERNS)


def pick_headers(headers: dict[str, str]) -> dict[str, str]:
    """Keep every real header (cookie, auth, signatures, client hints), drop recomputed ones."""
    kept: dict[str, str] = {}
    for name, value in headers.items():
        low = name.lower()
        if low in DROP_HEADERS or low.startswith(DROP_HEADER_PREFIXES):
            continue
        if not value:
            continue
        kept[name] = value
    return kept


def read_arkm_cookies(storage_file: Path) -> dict[str, str]:
    """Pull arkm.com cookies out of a Playwright storage_state snapshot."""
    try:
        state = json.loads(storage_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cookies: dict[str, str] = {}
    for cookie in state.get("cookies", []):
        name, value = cookie.get("name"), cookie.get("value")
        if not name or value is None or "arkm.com" not in (cookie.get("domain") or ""):
            continue
        cookies[name] = value
    return cookies


def signature(method: str, url: str, body: str | None) -> str:
    raw = f"{method.upper()} {url} {body or ''}".encode("utf-8", "replace")
    return hashlib.sha1(raw).hexdigest()


def parse_json_body(body: str | None) -> Any | None:
    if not body:
        return None
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return None


@dataclass
class Capture:
    method: str
    url: str
    headers: dict[str, str]
    body: str | None
    body_json: Any = None
    resource_type: str = ""
    status: int | None = None
    response_mime: str | None = None
    response_chars: int | None = None
    response_preview: str | None = None
    hits: int = 1
    first_seen: str = field(default_factory=now_iso)
    last_seen: str = field(default_factory=now_iso)

    @property
    def path(self) -> str:
        parts = urlsplit(self.url)
        return parts.path or "/"

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "path": self.path,
            "headers": self.headers,
            "body": self.body,
            "body_json": self.body_json,
            "resource_type": self.resource_type,
            "status": self.status,
            "response_mime": self.response_mime,
            "response_chars": self.response_chars,
            "response_preview": self.response_preview,
            "hits": self.hits,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    def replay_spec(self) -> dict[str, Any]:
        """Minimal spec embedded in the generated replay client."""
        return {
            "label": f"{self.method} {self.path}",
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "body": self.body,
            "body_json": self.body_json,
            "status_in_capture": self.status,
        }


class Recorder:
    """Collects filtered requests and their response bodies."""

    def __init__(self) -> None:
        self.records: dict[str, Capture] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self.skipped_auth = 0

    def attach(self, page: Page) -> None:
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def __len__(self) -> int:
        return len(self.records)

    async def _on_request(self, request: Request) -> None:
        try:
            if request.resource_type not in RECORDED_RESOURCE_TYPES:
                return
            if not is_api_call(request.url):
                return
            if AUTH_URL_RE.search(urlsplit(request.url).path):
                self.skipped_auth += 1
                return

            try:
                body = request.post_data
            except Exception:  # binary / already discarded payload
                body = None
            if body and len(body) > MAX_BODY_CHARS:
                body = body[:MAX_BODY_CHARS]

            sig = signature(request.method, request.url, body)
            try:
                # all_headers() includes browser-added headers (cookie, sec-*, cf state);
                # request.headers only exposes what the page's JS set.
                raw_headers = await request.all_headers()
            except Exception:
                raw_headers = dict(request.headers)
            headers = pick_headers(dict(raw_headers))

            existing = self.records.get(sig)
            if existing is not None:
                existing.hits += 1
                existing.last_seen = now_iso()
                existing.headers = headers  # freshest cookies win
                existing.body = body
                existing.body_json = parse_json_body(body)
                return

            capture = Capture(
                method=request.method.upper(),
                url=request.url,
                headers=headers,
                body=body,
                body_json=parse_json_body(body),
                resource_type=request.resource_type,
            )
            self.records[sig] = capture
        except Exception as exc:  # never let a handler kill the event loop
            log(f"request handler error: {exc!r}")

    async def _on_response(self, response: Response) -> None:
        try:
            request = response.request
            if request.resource_type not in RECORDED_RESOURCE_TYPES:
                return
            if not is_api_call(request.url):
                return
            try:
                body = request.post_data
            except Exception:
                body = None
            if body and len(body) > MAX_BODY_CHARS:
                body = body[:MAX_BODY_CHARS]

            sig = signature(request.method, request.url, body)
            # The request handler awaits all_headers(); wait briefly for it to land.
            for _ in range(20):
                if sig in self.records:
                    break
                await asyncio.sleep(0.05)
            else:
                return
            task = asyncio.create_task(self._read_body(sig, response))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except Exception as exc:
            log(f"response handler error: {exc!r}")

    async def _read_body(self, sig: str, response: Response) -> None:
        capture = self.records.get(sig)
        if capture is None:
            return
        try:
            raw = await response.body()
        except Exception:
            # body unavailable (redirect, aborted, navigation race) -> headers only
            capture.status = response.status
            capture.response_mime = response.headers.get("content-type")
            return

        text = raw.decode("utf-8", "replace")
        capture.status = response.status
        capture.response_mime = response.headers.get("content-type")
        capture.response_chars = len(text)
        capture.response_preview = text[:RESPONSE_PREVIEW_CHARS]

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


# ---------------------------------------------------------------------------
# Replay client template
# ---------------------------------------------------------------------------

REPLAY_TEMPLATE = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api_generator.py  (AUTO-GENERATED - do not edit by hand)

Replays the arkm.com API calls captured in the browser, without Playwright.

Captured at: __GENERATED_AT__
Source page: __CAPTURE_SOURCE__

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

GENERATED_AT = "__GENERATED_AT__"
CAPTURE_SOURCE = "__CAPTURE_SOURCE__"

# Captured specs are stored as JSON so arbitrary quotes/bodies cannot break the module.
_CAPTURE: dict[str, Any] = json.loads(
    r"""
__CAPTURE__
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
            log(f"channel='chrome' unavailable ({exc}); using bundled chromium")
            context = await playwright.chromium.launch_persistent_context(
                str(profile_dir), **common
            )

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
            storage_file.chmod(0o600)
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
        delay: float = 2.0,
        jitter: float = 1.0,
        retries: int = 3,
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

        self.auto_login = auto_login
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
                time.sleep(min(120, max(1, int(retry_after))))
                return
        time.sleep(min(60.0, (2 ** attempt) + random.uniform(0, 1.5)))

    def _send(self, spec: dict[str, Any]) -> Any:
        method = str(spec.get("method", "GET")).upper()
        url = spec["url"]

        for attempt in range(1, self.retries + 1):
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
        self._sleep_between()  # search calls go through the same rate limiter
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

            if position < len(selected):
                self._sleep_between()

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
'''


def build_replay_spec(record: dict[str, Any]) -> dict[str, Any]:
    """Replay spec from a captured_requests.json record (used by --regenerate)."""
    return {
        "label": f"{record['method']} {record['path']}",
        "method": record["method"],
        "url": record["url"],
        "headers": record["headers"],
        "body": record.get("body"),
        "body_json": record.get("body_json"),
        "status_in_capture": record.get("status"),
    }


def render_api_generator(
    specs: list[dict[str, Any]],
    source_url: str,
    cookies: dict[str, str] | None = None,
    client_key: str = DEFAULT_CLIENT_KEY,
) -> str:
    generated_at = now_iso()
    capture = {
        "requests": specs,
        "cookies": cookies or {},
        "client_key": client_key,
        "generated_at": generated_at,
        "source": source_url,
    }
    blob = json.dumps(capture, ensure_ascii=False, indent=2)
    return (
        REPLAY_TEMPLATE.replace("__GENERATED_AT__", generated_at)
        .replace("__CAPTURE_SOURCE__", source_url)
        .replace("__CAPTURE__", blob)
    )


def write_replay_client(
    specs: list[dict[str, Any]],
    source_url: str,
    client_key: str,
) -> Path:
    cookies = read_arkm_cookies(STORAGE_FILE)
    if cookies:
        log(f"embedding {len(cookies)} arkm.com cookie(s) in the replay client")
    else:
        log("no cookies found - generated client will need --session-file")
    GENERATED_FILE.write_text(
        render_api_generator(specs, source_url, cookies, client_key), encoding="utf-8"
    )
    GENERATED_FILE.chmod(0o600)  # embeds cookies/tokens
    return GENERATED_FILE


def regenerate(client_key: str) -> int:
    """Rebuild api_generator.py from captured_requests.json, no browser needed."""
    if not CAPTURE_FILE.exists():
        log(f"{CAPTURE_FILE.name} not found - run a capture first")
        return 1
    try:
        payload = json.loads(CAPTURE_FILE.read_text(encoding="utf-8"))
    except ValueError as exc:
        log(f"could not parse {CAPTURE_FILE.name}: {exc}")
        return 1

    records = payload.get("requests") or []
    if not records:
        log("capture file has no requests")
        return 2

    specs = [build_replay_spec(record) for record in records]
    path = write_replay_client(specs, payload.get("source_url") or DEFAULT_VISUALIZER_URL, client_key)
    log(f"regenerated {path.name} from {CAPTURE_FILE.name} ({len(specs)} endpoints)")
    return 0


# ---------------------------------------------------------------------------
# Browser side
# ---------------------------------------------------------------------------


async def launch_context(playwright: Playwright) -> BrowserContext:
    """Real Chrome + persistent profile: fewer anti-bot / Cloudflare problems."""
    args = [
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
    ]
    common: dict[str, Any] = {
        "headless": False,
        "args": args,
        "ignore_default_args": ["--enable-automation"],
        "no_viewport": True,
    }

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            **common,
        )
        log(f"real Chrome launched (profile: {PROFILE_DIR.name})")
        return context
    except Exception as exc:
        log(f"channel='chrome' unavailable ({exc}); falling back to bundled chromium")
        return await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            **common,
        )


async def goto(page: Page, url: str) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    except Exception as exc:
        # Cloudflare interstitials often make 'load' time out; the page is still usable.
        log(f"navigation to {url} finished with: {type(exc).__name__}")
    await page.bring_to_front()


def stdin_is_tty() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def is_auth_url(url: str) -> bool:
    return bool(AUTH_URL_RE.search(urlsplit(url).path or ""))


async def login_page_visible(page: Page) -> bool:
    """Heuristic: login form still on screen (password field present)."""
    try:
        return await page.locator('input[type="password"]').count() > 0
    except Exception:
        return False


async def wait_for_login(page: Page, timeout: float = 600.0) -> bool:
    """Block until the user is logged in (stdin Enter, or auto-detect without a TTY)."""
    if not stdin_is_tty():
        log(
            f"no interactive terminal: log in inside the Chrome window, "
            f"waiting up to {int(timeout)}s..."
        )
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if not is_auth_url(page.url) and not await login_page_visible(page):
                await asyncio.sleep(3)  # make sure it is not a transient redirect
                if not is_auth_url(page.url) and not await login_page_visible(page):
                    log(f"login detected at {page.url}")
                    return True
            await asyncio.sleep(2)
        log("login timeout reached")
        return False

    for _ in range(3):
        try:
            await asyncio.to_thread(
                input,
                "\n>>> Log in manually in the browser (user/password/2FA, solve Cloudflare).\n"
                "    Press Enter here once you are inside your account... ",
            )
        except EOFError:
            log("stdin closed; falling back to automatic login detection")
            return await wait_for_login(page, timeout)
        if not is_auth_url(page.url):
            log(f"continuing from {page.url}")
            return True
        log("still on the login page - finish login (or press Enter again to force continue)")
    log("proceeding anyway; captured traffic may be unauthenticated")
    return False


async def wait_for_traffic(args: argparse.Namespace) -> None:
    if args.capture_seconds > 0:
        log(f"capturing for {args.capture_seconds}s - interact with the visualizer now")
        await asyncio.sleep(args.capture_seconds)
        return

    if not stdin_is_tty():
        seconds = DEFAULT_CAPTURE_SECONDS
        log(f"no interactive terminal: auto-capturing for {seconds}s - interact now")
        await asyncio.sleep(seconds)
        return

    try:
        await asyncio.to_thread(
            input,
            "\n>>> Visualizer is open and recording.\n"
            "    Interact now: search an address, open entity/graph pages, switch tabs...\n"
            "    Press Enter here when you are done capturing... ",
        )
    except EOFError:
        log(f"stdin closed: auto-capturing for {DEFAULT_CAPTURE_SECONDS}s instead")
        await asyncio.sleep(DEFAULT_CAPTURE_SECONDS)


def summarize(records: list[Capture]) -> None:
    if not records:
        return
    print("\nCaptured endpoints:")
    for position, capture in enumerate(records, start=1):
        status = capture.status if capture.status is not None else "-"
        print(f"  {position:02d}. [{status}] {capture.method:4s} {capture.path}  (x{capture.hits})")


async def capture_session(args: argparse.Namespace) -> int:
    recorder = Recorder()

    async with async_playwright() as playwright:
        context = await launch_context(playwright)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(60_000)
            recorder.attach(page)

            log(f"opening {args.login_url}")
            await goto(page, args.login_url)
            logged_in = await wait_for_login(page, timeout=args.login_timeout)
            if not logged_in and not stdin_is_tty():
                log("aborting: login was not completed in time")
                return 3

            log(f"opening {args.visualizer_url}")
            await goto(page, args.visualizer_url)
            if is_auth_url(page.url):
                log("visualizer redirected to login - waiting for login again")
                if not await wait_for_login(page, timeout=args.login_timeout):
                    log("aborting: still not logged in")
                    return 3
                await goto(page, args.visualizer_url)
            await asyncio.sleep(3)  # let the first XHR batch start

            await wait_for_traffic(args)
            await asyncio.sleep(1.0)  # let late response handlers finish
            await recorder.drain()
            await asyncio.sleep(0.2)
            await recorder.drain()

            try:
                await context.storage_state(path=str(STORAGE_FILE))
                STORAGE_FILE.chmod(0o600)
                log(f"session snapshot -> {STORAGE_FILE.name} (contains cookies)")
            except Exception as exc:
                log(f"could not save storage state: {exc}")

            records = list(recorder.records.values())
            payload = {
                "generated_at": now_iso(),
                "source_url": args.visualizer_url,
                "request_count": len(records),
                "skipped_auth_requests": recorder.skipped_auth,
                "requests": [capture.to_dict() for capture in records],
            }
            CAPTURE_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            CAPTURE_FILE.chmod(0o600)
            log(f"capture saved -> {CAPTURE_FILE.name} ({len(records)} endpoints)")

            if recorder.skipped_auth:
                log(f"skipped {recorder.skipped_auth} auth/challenge request(s) (not replayable)")

            if not args.no_generate:
                if not records:
                    log(
                        "nothing to generate: no internal API calls matched the filter.\n"
                        "    Interact more with the visualizer and run again."
                    )
                else:
                    specs = [capture.replay_spec() for capture in records]
                    path = write_replay_client(specs, args.visualizer_url, args.client_key)
                    log(f"replay client -> {path.name}")
                    log(f"run it with: python {path.name} --delay 2")

            summarize(records)
            return 0 if records else 2
        finally:
            try:
                await context.close()
            except Exception:
                pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture arkm.com visualizer APIs and generate a requests replay client",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--login-url", default=DEFAULT_LOGIN_URL)
    parser.add_argument("--visualizer-url", default=DEFAULT_VISUALIZER_URL)
    parser.add_argument(
        "--capture-seconds",
        type=int,
        default=0,
        help="capture for N seconds instead of waiting for Enter",
    )
    parser.add_argument(
        "--login-timeout",
        type=float,
        default=600.0,
        help="seconds to wait for manual login when stdin is not a terminal",
    )
    parser.add_argument("--out", type=Path, default=CAPTURE_FILE, help="capture JSON path")
    parser.add_argument("--no-generate", action="store_true", help="capture only")
    parser.add_argument(
        "--client-key",
        default=DEFAULT_CLIENT_KEY,
        help="NEXT_PUBLIC_WEBAPP_CLIENT_KEY used for x-payload signatures",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="rebuild api_generator.py from captured_requests.json (no browser)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    global CAPTURE_FILE
    CAPTURE_FILE = Path(args.out)

    if args.regenerate:
        return regenerate(args.client_key)

    try:
        return asyncio.run(capture_session(args))
    except KeyboardInterrupt:
        log("interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
