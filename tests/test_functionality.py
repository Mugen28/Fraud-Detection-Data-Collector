"""Offline tests for the crawler pipeline, aggregation, and deployment config.

These tests mock every network call. They do not read the live session file and
they do not start Docker, the scheduler loop, or a browser.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import api_generator  # noqa: E402
import arkm_capture  # noqa: E402
import deep_arkm_crawler  # noqa: E402
import extract_all_iranian_wallets  # noqa: E402
import extract_hot_wallets_and_aggregate as aggregate_mod  # noqa: E402
import onchain_wallet_sweeper as sweeper_mod  # noqa: E402
import run_pipeline  # noqa: E402
import scheduler  # noqa: E402


EVM = "0x" + "11" * 20
TRON = "T" + "A" * 33
NEW_TRON = "TNEW" + "B" * 30


class Response:
    def __init__(self, status, payload=None, raw=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        if raw is not None:
            self.text = raw
        elif isinstance(payload, str):
            self.text = payload
        else:
            self.text = json.dumps(payload)
        self.content = self.text.encode("utf-8")

    def json(self):
        return json.loads(self.text)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fake_session(path: Path, value="fake-session", domain=".arkm.com") -> Path:
    write_json(path, {
        "cookies": [{"name": "arkham_session", "value": value, "domain": domain}],
        "origins": [],
    })
    return path


class PureHelpers(unittest.TestCase):
    def test_sign_request_is_path_bound_and_stable(self):
        first = api_generator.sign_request("https://api.arkm.com/transfers?base=x", "10", "k")
        second = api_generator.sign_request("https://api.arkm.com/transfers?base=y", "10", "k")
        other = api_generator.sign_request("https://api.arkm.com/balances?base=x", "10", "k")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_money_slugify_address_and_suffix(self):
        self.assertEqual(api_generator.money(None), "-")
        self.assertEqual(api_generator.money("nope"), "-")
        self.assertEqual(api_generator.money(1500), "$1.50K")
        self.assertEqual(api_generator.money(-2_000_000_000), "$-2.00B")
        self.assertEqual(api_generator.money(12.5), "$12.50")
        self.assertEqual(api_generator.slugify("  Farhad Exchange!! "), "Farhad_Exchange")
        self.assertEqual(api_generator.slugify("***", limit=5), "reque")
        self.assertEqual(api_generator.slugify("abcdef", limit=3), "abc")
        self.assertEqual(api_generator.short_address(""), "-")
        self.assertEqual(api_generator.short_address("short"), "short")
        self.assertEqual(api_generator.short_address(EVM), EVM[:8] + "..." + EVM[-6:])
        self.assertTrue(api_generator.looks_like_address(EVM))
        self.assertTrue(api_generator.looks_like_address(TRON))
        self.assertFalse(api_generator.looks_like_address("nobitex"))
        self.assertFalse(api_generator.looks_like_address("0x1234"))
        self.assertEqual(api_generator.response_suffix("application/json; charset=utf-8"), ".json")
        self.assertEqual(api_generator.response_suffix("text/html"), ".html")
        self.assertEqual(api_generator.response_suffix("text/csv"), ".csv")
        self.assertEqual(api_generator.response_suffix(None), ".txt")

    def test_build_url_replaces_and_keeps_existing_params(self):
        built = api_generator.build_url(
            "https://api.arkm.com/intelligence/search?query=old&limit=5",
            {"query": "nobitex", "extra": 1},
        )
        self.assertIn("query=nobitex", built)
        self.assertIn("limit=5", built)
        self.assertIn("extra=1", built)
        self.assertNotIn("query=old", built)

    def test_read_terms_file_skips_comments_and_missing_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.txt"
            path.write_text("# comment\n\nnobitex\n  wallex  \n", encoding="utf-8")
            self.assertEqual(api_generator.read_terms_file(path), ["nobitex", "wallex"])
            self.assertEqual(api_generator.read_terms_file(Path(tmp) / "missing.txt"), [])

    def test_targets_file_matches_documented_count(self):
        terms = api_generator.read_terms_file(ROOT / "targets.txt")
        self.assertEqual(len(terms), 41)
        self.assertEqual(len(terms), len({term.lower() for term in terms}))
        self.assertEqual(len(extract_all_iranian_wallets.TARGETS), 43)
        self.assertEqual(
            len(extract_all_iranian_wallets.TARGETS),
            len(set(extract_all_iranian_wallets.TARGETS)),
        )
        source = (ROOT / "extract_all_iranian_wallets.py").read_text(encoding="utf-8")
        self.assertNotIn("/Users/", source)

    def test_describe_item_and_auth_page(self):
        entity = api_generator.describe_item("arkhamEntities", {"name": "Nobitex", "id": "nobitex", "type": "cex"})
        self.assertIn("Nobitex", entity)
        self.assertIn("id=nobitex", entity)
        address = api_generator.describe_item("arkhamAddresses", {
            "address": EVM,
            "chain": "ethereum",
            "arkhamEntity": {"name": "Nobitex"},
            "arkhamLabel": {"name": "Hot Wallet"},
        })
        self.assertIn(EVM, address)
        self.assertIn("Nobitex", address)
        self.assertEqual(api_generator.describe_item("ens", {"name": "a.eth", "address": EVM}), f"a.eth -> {EVM}")
        self.assertIn("$1.50K", api_generator.describe_item("tokens", {
            "name": "Ether", "symbol": "ETH", "price": 1500, "identifier": {"pricingID": "eth"},
        }))
        self.assertEqual(api_generator.describe_item("other", "plain"), "plain")
        self.assertTrue(api_generator._is_auth_page("https://arkm.com/login?next=/"))
        self.assertFalse(api_generator._is_auth_page("https://arkm.com/visualizer"))

    def test_login_window_is_limited_to_a_desktop_session(self):
        with patch.object(api_generator.sys, "platform", "linux"), \
             patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}, clear=False):
            ok, reason = api_generator.browser_display_available()
            self.assertFalse(ok)
            self.assertIn("DISPLAY", reason)
        with patch.object(api_generator.sys, "platform", "linux"), \
             patch.dict(os.environ, {"DISPLAY": ":0", "WAYLAND_DISPLAY": ""}, clear=False):
            ok, _reason = api_generator.browser_display_available()
            self.assertTrue(ok)
        with patch.object(api_generator.sys, "platform", "darwin"), \
             patch.dict(os.environ, {"DISPLAY": "", "SSH_CONNECTION": "", "WAYLAND_DISPLAY": ""}, clear=False):
            ok, _reason = api_generator.browser_display_available()
            self.assertTrue(ok)
        with patch.object(api_generator.sys, "platform", "darwin"), \
             patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": "", "SSH_CONNECTION": "1.2.3.4 1"}, clear=False):
            ok, reason = api_generator.browser_display_available()
            self.assertFalse(ok)
            self.assertIn("SSH", reason)
        with patch.object(api_generator.sys, "platform", "win32"), \
             patch.dict(os.environ, {"SESSIONNAME": "Services"}, clear=False):
            ok, reason = api_generator.browser_display_available()
            self.assertFalse(ok)
            self.assertIn("service", reason)
        with patch.object(api_generator.sys, "platform", "linux"), \
             patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}, clear=False), \
             patch("api_generator.asyncio.run", side_effect=AssertionError("browser should not launch")):
            self.assertIsNone(api_generator.browser_login(timeout=1))

    def test_login_happens_before_docker_is_required(self):
        script = (ROOT / "run.sh").read_text(encoding="utf-8")
        login_at = script.index("api_generator.py login")
        self.assertIn("\nrequire_docker\n", script[login_at:])
        self.assertIn("Scripts/python.exe", script)
        self.assertTrue(api_generator.installed_login_browser())

    def test_session_ready_rejects_incomplete_snapshots(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.json"
            self.assertFalse(api_generator.arkham_session_ready(missing))
            directory = root / "storage_state.json"
            directory.mkdir()
            self.assertFalse(api_generator.arkham_session_ready(directory))
            broken = root / "broken.json"
            broken.write_text("{", encoding="utf-8")
            self.assertFalse(api_generator.arkham_session_ready(broken))
            write_json(root / "empty.json", {"cookies": []})
            self.assertFalse(api_generator.arkham_session_ready(root / "empty.json"))
            write_json(root / "wrong-domain.json", {
                "cookies": [{"name": "arkham_session", "value": "x", "domain": "example.com"}],
            })
            self.assertFalse(api_generator.arkham_session_ready(root / "wrong-domain.json"))
            write_json(root / "no-value.json", {
                "cookies": [{"name": "arkham_session", "value": "", "domain": ".arkm.com"}],
            })
            self.assertFalse(api_generator.arkham_session_ready(root / "no-value.json"))
            ready = fake_session(root / "ready.json")
            self.assertTrue(api_generator.arkham_session_ready(ready))

    def test_capture_filters_and_replay_spec(self):
        self.assertTrue(arkm_capture.is_api_call("https://api.arkm.com/transfers?base=all"))
        self.assertTrue(arkm_capture.is_api_call("https://api.arkhamintelligence.com/intelligence/search?q=1"))
        self.assertFalse(arkm_capture.is_api_call("https://example.com/transfers"))
        self.assertFalse(arkm_capture.is_api_call("https://arkm.com/static/app.js"))
        self.assertFalse(arkm_capture.is_api_call("https://arkm.com/collect?google-analytics=1"))
        kept = arkm_capture.pick_headers({
            "Cookie": "a=b",
            "Host": "arkm.com",
            "Accept-Encoding": "gzip",
            ":method": "GET",
            "X-Empty": "",
            "X-Payload": "abc",
        })
        self.assertEqual(kept, {"Cookie": "a=b", "X-Payload": "abc"})
        self.assertEqual(len(arkm_capture.signature("get", "https://arkm.com/a", None)), 40)
        self.assertIsNone(arkm_capture.parse_json_body(None))
        self.assertIsNone(arkm_capture.parse_json_body("{"))
        self.assertEqual(arkm_capture.parse_json_body('{"a": 1}'), {"a": 1})
        spec = arkm_capture.build_replay_spec({
            "method": "GET",
            "path": "/transfers",
            "url": "https://api.arkm.com/transfers",
            "headers": {"accept": "application/json"},
            "body": None,
            "status": 200,
        })
        self.assertEqual(spec["label"], "GET /transfers")
        self.assertEqual(spec["status_in_capture"], 200)
        rendered = arkm_capture.render_api_generator(
            [spec],
            "https://arkm.com/visualizer",
            cookies={},
            client_key="unit-test-key",
        )
        self.assertIn("unit-test-key", rendered)
        self.assertIn("https://api.arkm.com/transfers", rendered)
        with TemporaryDirectory() as tmp:
            storage = Path(tmp) / "state.json"
            storage.write_text("{", encoding="utf-8")
            self.assertEqual(arkm_capture.read_arkm_cookies(storage), {})
            fake_session(storage, value="unit-cookie")
            cookies = arkm_capture.read_arkm_cookies(storage)
            self.assertEqual(cookies.get("arkham_session"), "unit-cookie")


class ReplayClientTests(unittest.TestCase):
    def _client(self, tmp: Path, **kwargs):
        session = fake_session(tmp / "session.json")
        options = dict(
            delay=0,
            jitter=0,
            retries=2,
            timeout=1,
            out_dir=tmp / "out",
            session_file=session,
            impersonate=None,
            client_key="unit-test-key",
            auto_login=False,
            storage_file=session,
        )
        options.update(kwargs)
        return api_generator.ReplayClient(**options)

    def test_rejects_negative_delay_before_touching_a_session(self):
        with self.assertRaises(ValueError):
            api_generator.ReplayClient(delay=-0.1)

    def test_retries_floor_and_signed_headers(self):
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp), retries=0)
            self.assertEqual(client.retries, 1)
            headers = client._headers({
                "url": "https://api.arkm.com/transfers?base=nobitex",
                "headers": {"x-payload": "stale", "x-timestamp": "1"},
            })
            self.assertEqual(
                headers["x-payload"],
                api_generator.sign_request(
                    "https://api.arkm.com/transfers?base=nobitex",
                    headers["x-timestamp"],
                    "unit-test-key",
                ),
            )
            self.assertNotIn("unit-cookie-value-should-not-leak", json.dumps(headers))

    def test_auth_and_cloudflare_failures_do_not_open_a_browser(self):
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp), retries=1)
            client.session.request = lambda *args, **kwargs: Response(401, raw="nope")
            response = client._send({"method": "GET", "url": "https://api.arkm.com/x", "headers": {}})
            self.assertEqual(response.status_code, 401)
            self.assertTrue(client.auth_failed)
            self.assertFalse(client.cloudflare_blocked)

            client.session.request = lambda *args, **kwargs: Response(
                403, raw="cloudflare attention", headers={"server": "cloudflare"}
            )
            blocked = client._send({"method": "GET", "url": "https://api.arkm.com/y", "headers": {}})
            self.assertEqual(blocked.status_code, 403)
            self.assertTrue(client.cloudflare_blocked)
            self.assertFalse(client.reauthorize("expired"))

    def test_rate_limit_and_network_errors_retry_then_stop(self):
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp), retries=2)
            calls = {"n": 0}

            def flaky(method, url, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    return Response(429, raw="slow", headers={"retry-after": "0"})
                return Response(200, {"ok": True})

            client.session.request = flaky
            with patch.object(client, "_backoff", return_value=None):
                response = client._send({"method": "GET", "url": "https://api.arkm.com/z", "headers": {}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(calls["n"], 2)

            def explode(method, url, **kwargs):
                raise ConnectionError("offline")

            client.retries = 2
            client.session.request = explode
            with patch.object(client, "_backoff", return_value=None):
                self.assertIsNone(client._send({"method": "GET", "url": "https://api.arkm.com/z", "headers": {}}))

    def test_fetch_json_sleeps_once_and_rejects_bad_bodies(self):
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            sleeps = {"n": 0}
            original = client._sleep_between

            def count_sleep():
                sleeps["n"] += 1
                return original()

            client._sleep_between = count_sleep
            client.session.request = lambda *args, **kwargs: Response(200, {"ok": 1})
            self.assertEqual(client.fetch_json("https://api.arkm.com/transfers"), {"ok": 1})
            self.assertEqual(sleeps["n"], 1)

            client.session.request = lambda *args, **kwargs: Response(404, raw="missing")
            self.assertIsNone(client.fetch_json("https://api.arkm.com/missing"))
            client.session.request = lambda *args, **kwargs: Response(200, raw="not-json")
            self.assertIsNone(client.fetch_json("https://api.arkm.com/bad"))

    def test_reauthorize_gives_up_without_launching_chrome(self):
        with TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            client.auto_login = True
            with patch("api_generator.browser_login", return_value=None) as login:
                self.assertFalse(client.reauthorize("expired"))
                self.assertTrue(client.auth_dead)
                self.assertFalse(client.reauthorize("again"))
                self.assertEqual(login.call_count, 1)

    def test_search_writes_results_and_cli_guards_do_not_send(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = self._client(root)
            client.fetch_json = lambda *args, **kwargs: {
                "arkhamEntities": [{"name": "Demo", "id": "demo", "type": "cex"}],
            }
            client.search(["Demo Exchange"], details=False, limit=5)
            saved = client.out_dir / "queries" / "Demo_Exchange" / "01_search.json"
            self.assertTrue(saved.is_file())
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["arkhamEntities"][0]["id"], "demo")

            session = fake_session(root / "cli-session.json")
            with patch("api_generator.ReplayClient.search", return_value=None) as search:
                code = api_generator.search_main([
                    "Foo", "foo", "--no-auto-login", "--no-details",
                    "--session-file", str(session),
                    "--out", str(root / "search-out"),
                ])
            self.assertEqual(code, 0)
            terms = next(arg for arg in search.call_args.args if isinstance(arg, list))
            self.assertEqual(terms, ["Foo"])
            self.assertEqual(api_generator.search_main(["--no-auto-login"]), 1)
            self.assertEqual(api_generator.main(["--list"]), 0)
            self.assertEqual(api_generator.main(["--dry-run"]), 0)
            self.assertEqual(api_generator.main([
                "--only", "this-path-is-not-captured",
                "--no-auto-login",
                "--session-file", str(session),
                "--delay", "0",
                "--jitter", "0",
                "--out", str(root / "replay-out"),
            ]), 1)

    def test_impersonate_fallback_and_keyboard_interrupt(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = self._client(root, impersonate="chrome")
            def request(method, url, **kwargs):
                if "impersonate" in kwargs:
                    raise TypeError("backend has no impersonate")
                return Response(200, {"ok": True})

            client.session.request = request
            response = client._request("GET", "https://api.arkm.com/entitlements")
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(client.impersonate)

            session = fake_session(root / "session.json")
            with patch("api_generator.ReplayClient.run", side_effect=KeyboardInterrupt):
                code = api_generator.main([
                    "--no-auto-login",
                    "--session-file", str(session),
                    "--delay", "0",
                    "--jitter", "0",
                    "--out", str(root / "out"),
                ])
            self.assertEqual(code, 130)

    def test_corrupt_session_file_is_ignored(self):
        with TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.json"
            broken.write_text("{", encoding="utf-8")
            client = api_generator.ReplayClient(
                delay=0,
                jitter=0,
                session_file=broken,
                storage_file=broken,
                auto_login=False,
                impersonate=None,
                client_key="unit-test-key",
                out_dir=Path(tmp) / "out",
            )
            self.assertEqual(client.cookie_override, None)


class DeepCrawlerTests(unittest.TestCase):
    def test_limits_are_clamped(self):
        with TemporaryDirectory() as tmp:
            crawler = deep_arkm_crawler.DeepArkmCrawler(
                client=object(),
                max_transfers_per_chain=500,
                depth2_limit=0,
                out_dir=Path(tmp),
            )
        self.assertEqual(crawler.max_transfers_per_chain, 100)
        self.assertEqual(crawler.depth2_limit, 1)

    def test_main_refuses_bad_delay_and_missing_session_without_requests(self):
        with patch("deep_arkm_crawler.ReplayClient", side_effect=AssertionError("should not connect")):
            self.assertEqual(deep_arkm_crawler.main(["--delay", "-1"]), 2)
            self.assertEqual(deep_arkm_crawler.main(["--depth2-wallets", "-1"]), 2)
            with TemporaryDirectory() as tmp:
                with patch("deep_arkm_crawler.BASE_DIR", Path(tmp)):
                    self.assertEqual(deep_arkm_crawler.main([]), 2)

    def test_crawl_extracts_labels_and_isolates_output(self):
        hot = EVM
        deposit = "0x" + "22" * 20
        outsider = "0x" + "33" * 20
        calls = []

        class Client:
            def _send(self, spec):
                url = spec["url"]
                calls.append(url)
                if url.endswith("/balances/entity_top_address/nobitex"):
                    return Response(200, raw=f'"{hot}"')
                if "/entity_predictions/" in url:
                    return Response(200, [])
                if "/intelligence/search" in url:
                    return Response(200, {
                        "arkhamAddresses": [
                            {
                                "address": "0x" + f"{index:040x}",
                                "chain": "ethereum",
                                "arkhamLabel": {"name": "Hot Wallet"},
                            }
                            for index in range(1, 10)
                        ],
                    })
                if "chain=ethereum" in url and "base=nobitex" in url:
                    return Response(200, {
                        "transfers": [
                            {
                                "fromAddress": {
                                    "address": deposit,
                                    "chain": "ethereum",
                                    "arkhamEntity": {"id": "nobitex"},
                                    "arkhamLabel": {"name": "Nobitex Deposit"},
                                },
                                "toAddress": {
                                    "address": outsider,
                                    "chain": "ethereum",
                                    "arkhamLabel": {"name": "Unrelated"},
                                },
                            },
                            "not-a-transfer",
                            {
                                "fromAddress": {
                                    "address": "0x" + "55" * 20,
                                    "chain": "ethereum",
                                    "arkhamLabel": {"name": "nobitex deposit"},
                                },
                            },
                        ],
                    })
                if "base=nobitex" in url:
                    return Response(200, {"transfers": []})
                if deposit.lower() in url or hot.lower() in url:
                    return Response(200, {
                        "transfers": [{
                            "fromAddress": {
                                "address": "0x" + "44" * 20,
                                "arkhamLabel": {"name": "Nobitex Deposit"},
                            },
                        }],
                    })
                return Response(200, {"transfers": []})

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_master = ROOT / "api_output" / "deep_iranian_exchanges_all_wallets.json"
            before = real_master.stat().st_mtime_ns
            entities = [{"id": "nobitex", "name": "Nobitex.ir", "type": "CEX", "description": "test"}]
            with patch.object(deep_arkm_crawler, "EXCHANGE_ENTITIES", entities):
                crawler = deep_arkm_crawler.DeepArkmCrawler(
                    client=Client(),
                    chains=["ethereum", "bsc"],
                    enable_depth2=True,
                    depth2_limit=5,
                    out_dir=root / "deep",
                )
                summary = crawler.run(master_path=root / "master.json")
            self.assertEqual(real_master.stat().st_mtime_ns, before)
            wallets = {item["address"].lower() for item in summary["entities"]["nobitex"]["wallets"]}
            self.assertIn(hot.lower(), wallets)
            self.assertIn(deposit.lower(), wallets)
            self.assertIn("0x" + "55" * 20, wallets)
            self.assertNotIn(outsider.lower(), wallets)
            self.assertIn("0x" + "44" * 20, wallets)
            depth_bases = {
                url.split("base=")[1].split("&")[0]
                for url in calls
                if "base=" in url and "base=nobitex" not in url
            }
            expected_bases = {hot.lower()} | {f"0x{index:040x}" for index in range(1, 10)}
            self.assertEqual(depth_bases, expected_bases)
            saved = json.loads((root / "deep" / "nobitex_deep.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["total_wallets"], len(saved["wallets"]))

            calls.clear()
            with patch.object(deep_arkm_crawler, "EXCHANGE_ENTITIES", entities):
                quiet = deep_arkm_crawler.DeepArkmCrawler(
                    client=Client(),
                    chains=["ethereum"],
                    enable_depth2=False,
                    out_dir=root / "deep-off",
                )
                quiet.run(master_path=root / "master-off.json")
            self.assertFalse(any("base=0x" in url for url in calls))

    def test_crawler_protects_existing_cache_on_auth_failure(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep_dir = root / "deep_iranian_wallets"
            cached_file = deep_dir / "nobitex_deep.json"
            write_json(cached_file, {
                "entity_id": "nobitex",
                "entity_name": "Nobitex.ir",
                "wallets": [{"address": EVM, "chain": "ethereum"}],
            })

            class FailingClient:
                auth_failed = True
                cloudflare_blocked = False

                def _send(self, spec):
                    return Response(401, raw="Unauthorized")

            crawler = deep_arkm_crawler.DeepArkmCrawler(
                client=FailingClient(),
                chains=["ethereum"],
                out_dir=deep_dir,
            )
            master = root / "master.json"
            write_json(master, {"all_wallets": [{"address": EVM}]})
            before = master.read_bytes()
            summary = crawler.run(master_path=master)
            self.assertFalse(summary["complete"])
            self.assertEqual(summary["total_entities_crawled"], 0)
            self.assertEqual(master.read_bytes(), before)
            self.assertEqual(summary["total_unique_wallets"], 1)
            reloaded = json.loads(cached_file.read_text(encoding="utf-8"))
            self.assertEqual(len(reloaded["wallets"]), 1)


    def test_missing_responses_surface_in_cli_and_leave_existing_files_intact(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "api_output"
            master = out / "deep_iranian_exchanges_all_wallets.json"
            cached = out / "deep_iranian_wallets" / "nobitex_deep.json"
            write_json(master, {"all_wallets": [{"address": EVM}]})
            write_json(cached, {"wallets": [{"address": EVM}]})
            before = (master.read_bytes(), cached.read_bytes())
            entities = [{"id": "nobitex", "name": "Nobitex"}]
            with (
                patch.object(deep_arkm_crawler, "BASE_DIR", root),
                patch.object(deep_arkm_crawler, "EXCHANGE_ENTITIES", entities),
                patch("deep_arkm_crawler.arkham_session_ready", return_value=True),
                patch("deep_arkm_crawler.ReplayClient") as replay,
            ):
                replay.return_value.auth_failed = False
                replay.return_value.cloudflare_blocked = False
                replay.return_value._send.return_value = None
                self.assertEqual(deep_arkm_crawler.main(["--chains", "ethereum"]), 1)
            self.assertEqual((master.read_bytes(), cached.read_bytes()), before)


class OnChainTests(unittest.TestCase):
    def setUp(self):
        self._sleep = patch("onchain_wallet_sweeper.time.sleep", return_value=None)
        self._sleep.start()

    def tearDown(self):
        self._sleep.stop()

    def _sweeper(self, tmp: Path):
        return sweeper_mod.OnChainSweeper(max_pages=3, limit_per_page=2, out_dir=tmp / "parts")

    def test_http_errors_return_none(self):
        with patch("onchain_wallet_sweeper.urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(sweeper_mod.http_get_json("https://example.invalid/x"))

        class Body:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{"

        with patch("onchain_wallet_sweeper.urllib.request.urlopen", return_value=Body()):
            self.assertIsNone(sweeper_mod.http_get_json("https://example.invalid/y"))

        class Ok(Body):
            def read(self):
                return b'{"ok": true}'

        with patch("onchain_wallet_sweeper.urllib.request.urlopen", return_value=Ok()):
            self.assertEqual(sweeper_mod.http_get_json("https://example.invalid/z"), {"ok": True})

    def test_tron_pagination_dedup_and_bitcoin_inputs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sweeper = self._sweeper(root)
            pages = [
                {
                    "data": [
                        {"from": "TDEPOSIT" + "C" * 26, "token_info": {"symbol": "USDT"}},
                        {"from": TRON, "token_info": {}},
                        "skip-me",
                    ],
                    "meta": {"fingerprint": "next"},
                },
                {
                    "data": [
                        {"from": "TDEPOSIT" + "C" * 26, "token_info": {"symbol": "USDT"}},
                        {"from": "TSECOND" + "D" * 27},
                    ],
                    "meta": {},
                },
            ]

            def fake_http(url, timeout=12.0):
                self.assertIn("only_to=true", url)
                return pages.pop(0)

            with patch("onchain_wallet_sweeper.http_get_json", side_effect=fake_http):
                found = sweeper.sweep_tron({
                    "address": TRON,
                    "name": "Nobitex.ir",
                    "chain": "tron",
                    "exchange": "nobitex",
                })
            self.assertEqual(found, 2)
            self.assertEqual(len(sweeper.discovered_wallets), 2)
            self.assertNotIn(f"tron:{TRON}", sweeper.discovered_wallets)

            def btc_http(url, timeout=12.0):
                return [{
                    "vin": [
                        {"prevout": {"scriptpubkey_address": "bc1qdepositor"}},
                        {"prevout": None},
                    ],
                    "vout": [{"scriptpubkey_address": "bc1qhot", "value": 1000}],
                }, {
                    "vin": [
                        {"prevout": {"scriptpubkey_address": "bc1qhot"}},
                        {"prevout": {"scriptpubkey_address": "bc1qcosigner"}},
                    ],
                    "vout": [{"scriptpubkey_address": "bc1qhot", "value": 1000}],
                }, {
                    "vin": [{"prevout": {"scriptpubkey_address": "bc1qwithdrawal"}}],
                    "vout": [{"scriptpubkey_address": "bc1qother", "value": 1000}],
                }, {
                    "vin": [{"prevout": {"scriptpubkey_address": "bc1qzero"}}],
                    "vout": [{"scriptpubkey_address": "bc1qhot", "value": 0}],
                }, "bad-tx"]

            with patch("onchain_wallet_sweeper.http_get_json", side_effect=btc_http):
                added = sweeper.sweep_bitcoin({
                    "address": "bc1qhot",
                    "name": "Nobitex.ir",
                    "chain": "bitcoin",
                    "exchange": "nobitex",
                })
            self.assertEqual(added, 1)
            bitcoin = [w for w in sweeper.discovered_wallets.values() if w["chain"] == "bitcoin"]
            self.assertEqual([w["address"] for w in bitcoin], ["bc1qdepositor"])
            self.assertEqual(bitcoin[0]["source"], sweeper_mod.BITCOIN_INBOUND_SOURCE)
            with patch("onchain_wallet_sweeper.http_get_json", return_value={"error": True}):
                self.assertEqual(sweeper.sweep_bitcoin({
                    "address": "bc1qhot", "name": "Nobitex.ir", "chain": "bitcoin", "exchange": "nobitex",
                }), 0)

    def test_run_skips_unsupported_chains_and_does_not_touch_real_output(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = ROOT / "api_output" / "onchain_swept_wallets.json"
            before = real.stat().st_mtime_ns
            sweeper = self._sweeper(root)

            def fake_http(url, timeout=12.0):
                if "trongrid" in url:
                    return {"data": [{"from": "TUSER" + "E" * 29, "token_info": {"symbol": "USDT"}}], "meta": {}}
                return []

            sender = "0x" + "ab" * 20

            def fake_post(url, payload, timeout=12.0):
                method = payload["method"]
                if method == "eth_blockNumber":
                    return {"jsonrpc": "2.0", "id": 1, "result": "0x1000"}
                if method == "eth_getLogs":
                    return {"jsonrpc": "2.0", "id": 1, "result": [{
                        "topics": [
                            sweeper_mod.TRANSFER_TOPIC,
                            "0x" + sender[2:].zfill(64),
                            "0x" + EVM[2:].lower().zfill(64),
                        ],
                    }]}
                return {"jsonrpc": "2.0", "id": 1, "error": {"message": "no"}}

            targets = [
                {"exchange": "nobitex", "name": "Nobitex.ir", "chain": "tron", "address": TRON, "role": "hot"},
                {"exchange": "nobitex", "name": "Nobitex.ir", "chain": "ethereum", "address": EVM, "role": "hot"},
                {"exchange": "nobitex", "name": "Nobitex.ir", "chain": "solana", "address": "not-sol", "role": "hot"},
                {"exchange": "nobitex", "name": "Nobitex.ir", "chain": "bitcoin", "address": "16Zp5T3w51D2aRjR2QyqD3Z2jF5", "role": "bad"},
            ]
            with patch("onchain_wallet_sweeper.http_get_json", side_effect=fake_http), \
                 patch("onchain_wallet_sweeper.http_post_json", side_effect=fake_post):
                summary = sweeper.run(summary_path=root / "out.json", targets=targets)
            self.assertEqual(real.stat().st_mtime_ns, before)
            self.assertEqual(summary["total_swept_wallets"], 2)
            skipped = {(item["chain"], item["reason"]) for item in summary["skipped_targets"]}
            self.assertIn(("solana", "no on-chain sweeper for this chain"), skipped)
            self.assertIn(("bitcoin", "invalid bitcoin address"), skipped)
            self.assertEqual(json.loads((root / "out.json").read_text(encoding="utf-8"))["total_swept_wallets"], 2)

    def test_cli_rejects_non_positive_pages(self):
        with self.assertRaises(SystemExit) as caught:
            sweeper_mod.main(["--pages", "0"])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_reports_failed_sources_and_accepts_empty_responses(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = next(w for w in sweeper_mod.ROOT_HOT_WALLETS if w["chain"] == "bitcoin")
            output = root / "api_output" / "onchain_swept_wallets.json"
            with patch.object(sweeper_mod, "BASE_DIR", root), (
                patch.object(sweeper_mod, "ROOT_HOT_WALLETS", [target])
            ), patch("onchain_wallet_sweeper.http_get_json", side_effect=[None, []]):
                self.assertEqual(sweeper_mod.main([]), 1)
                failed = json.loads(output.read_text())["failed_targets"]
                self.assertEqual([item["chain"] for item in failed], ["bitcoin"])
                self.assertEqual(sweeper_mod.main([]), 0)
                self.assertEqual(json.loads(output.read_text())["failed_targets"], [])

    def test_root_addresses_are_sweepable(self):
        defects = [
            (wallet["chain"], wallet["address"])
            for wallet in sweeper_mod.ROOT_HOT_WALLETS
            if sweeper_mod.address_problem(wallet["chain"], wallet["address"])
        ]
        self.assertEqual(defects, [])
        self.assertIsNone(sweeper_mod.address_problem("bitcoin", "bc1qgr3d2uwesguppck3mmdzk63p2n42788a87pczr"))
        self.assertEqual(
            sweeper_mod.address_problem("bitcoin", "16Zp5T3w51D2aRjR2QyqD3Z2jF5"),
            "invalid bitcoin address",
        )

    def test_onchain_sweeper_preserves_historical_wallets(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_file = root / "swept.json"
            write_json(out_file, {
                "wallets": [
                    {
                        "address": "T" + "X" * 33,
                        "chain": "tron",
                        "exchange": "Nobitex.ir",
                        "label": "Old deposit",
                    },
                    {"address": "bc1qlegacy", "chain": "bitcoin", "source": sweeper_mod.LEGACY_BITCOIN_SOURCE},
                ]
            })
            sweeper = self._sweeper(root)
            with patch("onchain_wallet_sweeper.http_get_json", return_value={"data": [], "meta": {}}):
                summary = sweeper.run(summary_path=out_file, targets=[])
            self.assertEqual(summary["total_swept_wallets"], 1)
            self.assertEqual(summary["wallets"][0]["address"], "T" + "X" * 33)


class AggregateTests(unittest.TestCase):
    def test_aggregation_repairs_counts_and_survives_corrupt_inputs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep = root / "api_output" / "deep_iranian_wallets"
            write_json(deep / "sample_deep.json", {
                "entity_id": "sample",
                "entity_name": "Sample",
                "wallets": [
                    {
                        "address": f'  "{EVM}"  ',
                        "chain": " Ethereum ",
                        "label": "Primary Master Hot Wallet",
                        "source": "balances/entity_top_address",
                    },
                    {
                        "address": TRON,
                        "chain": "TRON",
                        "label": "User Deposit",
                        "source": "transfers",
                    },
                    {
                        "address": "not-a-wallet",
                        "chain": "ethereum",
                        "label": "Treasury reserve",
                        "source": "manual",
                    },
                    {"address": "", "chain": "ethereum", "label": "Hot Wallet"},
                    "bad-row",
                ],
            })
            (deep / "broken_deep.json").write_text("{", encoding="utf-8")
            write_json(deep / "not-an-object_deep.json", [1, 2, 3])
            write_json(root / "api_output" / "onchain_swept_wallets.json", {
                "wallets": [
                    {
                        "address": NEW_TRON,
                        "chain": "tron",
                        "exchange": "Nobitex.ir",
                        "label": "deposit",
                        "source": "onchain/trongrid",
                    },
                    {"address": TRON, "chain": "tron", "exchange": "Nobitex.ir"},
                    "bad",
                    {"address": "", "chain": "tron", "exchange": "Nope"},
                    {
                        "address": "0x" + "22" * 20,
                        "chain": "ethereum",
                        "exchange": "UnknownDesk",
                    },
                ],
            })
            real_master = ROOT / "api_output" / "deep_iranian_exchanges_all_wallets.json"
            real_hot = ROOT / "api_output" / "iranian_exchanges_hot_wallets.json"
            before = (real_master.stat().st_mtime_ns, real_hot.stat().st_mtime_ns)

            stats = aggregate_mod.aggregate(root)

            self.assertEqual((real_master.stat().st_mtime_ns, real_hot.stat().st_mtime_ns), before)
            master = json.loads((root / "api_output" / "deep_iranian_exchanges_all_wallets.json").read_text(encoding="utf-8"))
            hot = json.loads((root / "api_output" / "iranian_exchanges_hot_wallets.json").read_text(encoding="utf-8"))
            self.assertEqual(master["total_unique_wallets"], len(master["all_wallets"]))
            self.assertEqual(master["total_hot_wallets"], len(master["hot_wallets"]))
            self.assertEqual(
                master["total_unique_wallets"],
                master["hot_wallets_in_master"] + master["total_deposit_wallets"] + master["total_other_wallets"],
            )
            self.assertEqual(stats["unique"], master["total_unique_wallets"])
            chains = {
                item["chain"]
                for item in hot["hot_wallets"]
                if item["address"].lower() == EVM.lower()
            }
            self.assertEqual(chains, {"ethereum"})
            categories = {
                (item["address"].lower(), item["chain"]): item["category"]
                for item in master["all_wallets"]
            }
            self.assertEqual(categories[(TRON.lower(), "tron")], "Deposit / User Wallet")
            self.assertEqual(categories[(NEW_TRON.lower(), "tron")], "On-Chain Active Deposit Wallet")
            unknown = next(item for item in master["all_wallets"] if item["exchange_name"] == "UnknownDesk")
            self.assertEqual(unknown["exchange_id"], "iranian_exchange")
            report = (root / "api_output" / "iranian_exchanges_hot_wallets.md").read_text(encoding="utf-8")
            rows = [line for line in report.splitlines() if line.startswith("| ") and "`" in line]
            self.assertEqual(len(rows), len(hot["hot_wallets"]))

    def test_legacy_expansions_are_removed_but_independent_observations_survive(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            master_path = root / "api_output" / "deep_iranian_exchanges_all_wallets.json"
            legacy = {"address": EVM, "chain": "polygon", "source": aggregate_mod.LEGACY_EVM_SOURCE}
            write_json(master_path, {
                "hot_wallets": [legacy, {**legacy, "chain": "optimism"}],
                "all_wallets": [
                    {**legacy, "category": "Hot Wallet"},
                    {**legacy, "chain": "optimism", "category": "Hot Wallet"},
                ],
                "entities": {"test": {
                    "entity_name": "Test Exchange",
                    "wallets": [
                        {"address": EVM, "chain": "ethereum", "label": "Hot Wallet"},
                        {"address": EVM, "chain": "polygon", "label": "Exchange Labeled Wallet"},
                        {"address": EVM, "chain": "base", "label": "Hot Wallet"},
                    ],
                }},
            })

            for _ in range(2):
                aggregate_mod.aggregate(root)
                master = json.loads(master_path.read_text())
                categories = {w["chain"]: w["category"] for w in master["all_wallets"] if w["address"] == EVM}
                self.assertEqual(categories, {
                    "ethereum": "Hot Wallet",
                    "polygon": "Exchange Wallet",
                    "base": "Hot Wallet",
                })

    def test_corrupt_onchain_file_does_not_abort(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "api_output").mkdir()
            (root / "api_output" / "onchain_swept_wallets.json").write_text("[", encoding="utf-8")
            stats = aggregate_mod.aggregate(root)
            self.assertGreater(stats["hot"], 0)
            self.assertEqual(stats["added_from_onchain"], 0)

    def test_aggregation_indexes_all_hot_wallets_in_master_registry(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            stats = aggregate_mod.aggregate(root)
            master = json.loads((root / "api_output" / "deep_iranian_exchanges_all_wallets.json").read_text(encoding="utf-8"))
            self.assertEqual(master["total_hot_wallets"], master["hot_wallets_in_master"])
            self.assertGreater(master["total_hot_wallets"], 0)
            self.assertEqual(master["total_unique_wallets"], len(master["all_wallets"]))


class PipelineTests(unittest.TestCase):
    def test_skip_all_stages_exits_clean(self):
        with patch("run_pipeline.subprocess.run", side_effect=AssertionError("should not run")):
            self.assertEqual(run_pipeline.main(["--skip-arkm", "--skip-onchain", "--skip-aggregate", "--skip-db"]), 0)

    def test_invalid_cli_and_delay(self):
        self.assertEqual(run_pipeline.main(["--onchain-pages", "0"]), 2)
        self.assertEqual(run_pipeline.main(["--delay", "-0.1"]), 2)

    def test_missing_session_fails_pipeline_without_spawning_arkham(self):
        with patch("run_pipeline.arkham_session_ready", return_value=False), \
             patch("run_pipeline.subprocess.run", side_effect=AssertionError("should not run")):
            self.assertEqual(run_pipeline.main(["--skip-onchain", "--skip-aggregate", "--skip-db"]), 1)

    def test_stage_failures_and_command_wiring(self):
        calls = []

        def fake_run(cmd, cwd, check):
            calls.append(cmd)
            if "deep_arkm_crawler.py" in cmd[1]:
                raise subprocess.CalledProcessError(2, cmd)
            if "onchain_wallet_sweeper.py" in cmd[1]:
                raise OSError("missing binary")
            return subprocess.CompletedProcess(cmd, 0)

        with patch("run_pipeline.arkham_session_ready", return_value=True), \
             patch("run_pipeline.subprocess.run", side_effect=fake_run):
            code = run_pipeline.main(["--onchain-pages", "3", "--depth2-limit", "7", "--delay", "0.5"])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 4)
        self.assertIn("--depth2-limit", calls[0])
        self.assertIn("7", calls[0])
        self.assertIn("0.5", calls[0])
        self.assertIn("--pages", calls[1])
        self.assertIn("3", calls[1])
        self.assertTrue(calls[2][1].endswith("extract_hot_wallets_and_aggregate.py"))
        self.assertTrue(calls[3][1].endswith("db_sync.py"))

        with patch("run_pipeline.arkham_session_ready", return_value=True), \
             patch("run_pipeline.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["agg"])):
            self.assertEqual(run_pipeline.main(["--skip-arkm", "--skip-onchain"]), 1)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        scheduler.RUNNING = True

    def tearDown(self):
        scheduler.RUNNING = True

    def test_wallet_count_and_sleep_math(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.json"
            with patch.object(scheduler, "MASTER_DB", missing):
                self.assertEqual(scheduler.get_current_wallet_count(), 0)
            broken = root / "broken.json"
            broken.write_text("{", encoding="utf-8")
            with patch.object(scheduler, "MASTER_DB", broken):
                self.assertEqual(scheduler.get_current_wallet_count(), 0)
            listed = root / "list.json"
            write_json(listed, [])
            with patch.object(scheduler, "MASTER_DB", listed):
                self.assertEqual(scheduler.get_current_wallet_count(), 0)
            counted = root / "count.json"
            write_json(counted, {"total_unique_wallets": 5, "all_wallets": []})
            with patch.object(scheduler, "MASTER_DB", counted):
                self.assertEqual(scheduler.get_current_wallet_count(), 5)
            fallback = root / "fallback.json"
            write_json(fallback, {"all_wallets": [{}, {}, {}]})
            with patch.object(scheduler, "MASTER_DB", fallback):
                self.assertEqual(scheduler.get_current_wallet_count(), 3)

        class Fixed:
            def uniform(self, low, high):
                return high

        sleep_for, jitter = scheduler.next_sleep_seconds(100, 10, Fixed(), floor=60)
        self.assertEqual((sleep_for, jitter), (110, 10))
        sleep_for, jitter = scheduler.next_sleep_seconds(10, 0, Fixed(), floor=60)
        self.assertEqual(sleep_for, 60)

    def test_cycle_delta_never_goes_negative_and_errors_are_caught(self):
        counts = iter([10, 4])
        with patch.object(scheduler, "get_current_wallet_count", side_effect=lambda: next(counts)), \
             patch("scheduler.subprocess.run", return_value=subprocess.CompletedProcess(["x"], 0)):
            self.assertTrue(scheduler.run_crawler_pipeline(["--skip-arkm"]))
        with patch("scheduler.subprocess.run", side_effect=subprocess.CalledProcessError(3, ["x"])):
            self.assertFalse(scheduler.run_crawler_pipeline([]))
        with patch("scheduler.subprocess.run", side_effect=OSError("absent")):
            self.assertFalse(scheduler.run_crawler_pipeline([]))

    def test_run_immediately_and_deferred_start(self):
        ran = []

        def stop(extra):
            ran.append(extra)
            scheduler.RUNNING = False
            return True

        args = argparse.Namespace(
            skip_arkm=True,
            skip_onchain=False,
            interval_seconds=5,
            interval_hours=24,
            jitter_hours=1,
            run_immediately=True,
        )
        with patch.object(scheduler, "run_crawler_pipeline", side_effect=stop), \
             patch("scheduler.time.sleep", return_value=None):
            scheduler.serve(args)
        self.assertEqual(ran, [["--skip-arkm"]])

        scheduler.RUNNING = True
        ran.clear()

        def stop_on_sleep(_seconds):
            scheduler.RUNNING = False

        args.run_immediately = False
        with patch.object(scheduler, "run_crawler_pipeline", side_effect=stop), \
             patch("scheduler.time.sleep", side_effect=stop_on_sleep):
            scheduler.serve(args)
        self.assertEqual(ran, [])

    def test_signal_and_invalid_interval(self):
        scheduler.RUNNING = True
        scheduler.signal_handler(signal.SIGTERM, None)
        self.assertFalse(scheduler.RUNNING)
        with self.assertRaises(SystemExit) as caught:
            scheduler.main(["--interval-seconds", "0"])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_parses_no_run_immediately(self):
        previous_int = signal.getsignal(signal.SIGINT)
        previous_term = signal.getsignal(signal.SIGTERM)
        try:
            with patch.object(scheduler, "serve") as serve:
                scheduler.main(["--no-run-immediately", "--interval-seconds", "5", "--skip-onchain"])
            args = serve.call_args.args[0]
            self.assertFalse(args.run_immediately)
            self.assertTrue(args.skip_onchain)
        finally:
            signal.signal(signal.SIGINT, previous_int)
            signal.signal(signal.SIGTERM, previous_term)
            scheduler.RUNNING = True


class DeploymentTests(unittest.TestCase):
    def test_shell_and_entrypoint(self):
        syntax = subprocess.run(["bash", "-n", str(ROOT / "run.sh")], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        script = (ROOT / "run.sh").read_text(encoding="utf-8")
        self.assertIn("arkm.com", script)
        self.assertIn("scheduler.py", script)
        entry = ROOT / "docker-entrypoint.sh"
        syntax = subprocess.run(["sh", "-n", str(entry)], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            as_dir = root / "state-dir"
            as_dir.mkdir()
            failed = subprocess.run(
                ["sh", str(entry), "python3", "-c", "import sys; sys.exit(0)"],
                capture_output=True,
                text=True,
                env={**os.environ, "ARKM_STORAGE_FILE": str(as_dir)},
            )
            self.assertEqual(failed.returncode, 1)
            self.assertIn("directory", failed.stderr)

            ready = root / "state.json"
            ready.write_text("{}", encoding="utf-8")
            ok = subprocess.run(
                ["sh", str(entry), "python3", "-c", "import sys; sys.exit(0)"],
                capture_output=True,
                text=True,
                env={**os.environ, "ARKM_STORAGE_FILE": str(ready)},
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            spaced = subprocess.run(
                ["sh", str(entry), 'python3 -c "import sys; sys.exit(0)"'],
                capture_output=True,
                text=True,
                env={**os.environ, "ARKM_STORAGE_FILE": str(ready)},
            )
            self.assertEqual(spaced.returncode, 0, spaced.stderr)

    def test_run_sh_supports_help_and_local(self):
        help_res = subprocess.run(["bash", str(ROOT / "run.sh"), "--help"], capture_output=True, text=True)
        self.assertEqual(help_res.returncode, 0)
        self.assertIn("--local", help_res.stdout)
        self.assertIn("--login", help_res.stdout)

    def test_docker_files_keep_secrets_out_and_do_not_restart_success(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn('ENTRYPOINT ["/app/docker-entrypoint.sh"]', dockerfile)
        self.assertIn("python:3.11-slim", dockerfile)
        self.assertIn("restart: on-failure:3", compose)
        self.assertNotIn("unless-stopped", compose)
        for entry in ("storage_state.json", "api_output", ".env", "captured_requests.json", ".venv"):
            self.assertIn(entry, ignore)
        self.assertNotIn("storage_state.template.json", ignore)

    def test_saved_datasets_parse_and_reconcile(self):
        output = ROOT / "api_output"
        json_files = sorted(output.rglob("*.json"))
        self.assertGreater(len(json_files), 40)
        for path in json_files:
            with self.subTest(path=str(path.relative_to(ROOT))):
                json.loads(path.read_text(encoding="utf-8"))

        master = json.loads((output / "deep_iranian_exchanges_all_wallets.json").read_text(encoding="utf-8"))
        wallets = master["all_wallets"]
        self.assertEqual(master["total_unique_wallets"], len(wallets))
        self.assertEqual(master["total_hot_wallets"], len(master["hot_wallets"]))
        keys = [((item.get("address") or "").lower(), (item.get("chain") or "").lower()) for item in wallets]
        self.assertEqual(len(keys), len(set(keys)))
        if "hot_wallets_in_master" in master:
            self.assertEqual(
                master["total_unique_wallets"],
                master["hot_wallets_in_master"] + master["total_deposit_wallets"] + master["total_other_wallets"],
            )
        else:
            self.assertEqual(
                master["total_deposit_wallets"],
                master["total_unique_wallets"] - master["total_hot_wallets"],
            )

        hot = json.loads((output / "iranian_exchanges_hot_wallets.json").read_text(encoding="utf-8"))
        self.assertEqual(hot["total_hot_wallets"], len(hot["hot_wallets"]))
        self.assertEqual(hot["hot_wallets"], master["hot_wallets"])
        self.assertFalse(any(w.get("source") in aggregate_mod.STALE_WALLET_SOURCES for w in hot["hot_wallets"] + wallets))
        report = (output / "iranian_exchanges_hot_wallets.md").read_text(encoding="utf-8")
        rows = [line for line in report.splitlines() if line.startswith("| ") and "`" in line]
        self.assertEqual(len(rows), len(hot["hot_wallets"]))

        swept = json.loads((output / "onchain_swept_wallets.json").read_text(encoding="utf-8"))
        self.assertEqual(swept["total_swept_wallets"], len(swept["wallets"]))

        for path in (output / "deep_iranian_wallets").glob("*_deep.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["total_wallets"], len(payload["wallets"]), path.name)

        legacy = json.loads((output / "iranian_exchanges_all_wallets.json").read_text(encoding="utf-8"))
        self.assertEqual(legacy["total_targets_scanned"], len(legacy["targets"]))


if __name__ == "__main__":
    unittest.main()
