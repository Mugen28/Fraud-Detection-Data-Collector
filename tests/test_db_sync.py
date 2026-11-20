"""Comprehensive unit and end-to-end tests for Dual Database Synchronization (SQLite + ClickHouse / LightHouse).

Includes:
  - Configuration parsing from .env and environment variables.
  - SQLite table auto-creation, upsert, and idempotency tests.
  - Live HTTP mock server simulating ClickHouse / LightHouse API.
  - Table auto-creation and append behavior in ClickHouse.
  - Resilient error handling (graceful fallback vs strict mode).
  - Integration with run_pipeline.py.
"""

from __future__ import annotations

import http.server
import json
import os
import sqlite3
import sys
import threading
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import db_sync  # noqa: E402
import run_pipeline  # noqa: E402


class TestDatabaseConfig(unittest.TestCase):
    def test_default_config(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg = db_sync.DatabaseConfig.from_env(tmp)
            self.assertTrue(cfg.enable_local)
            self.assertFalse(cfg.enable_ch)
            self.assertEqual(cfg.ch_port, 8123)
            self.assertEqual(cfg.ch_user, "default")
            self.assertEqual(cfg.ch_database, "default")

    def test_custom_environment_variables(self):
        env = {
            "CLICKHOUSE_HOST": "clickhouse.internal",
            "CLICKHOUSE_PORT": "9000",
            "CLICKHOUSE_USER": "admin",
            "CLICKHOUSE_PASSWORD": "secret_password",
            "CLICKHOUSE_DATABASE": "arkm_intel",
            "CLICKHOUSE_SECURE": "true",
            "CLICKHOUSE_STRICT": "true",
            "LOCAL_DB_PATH": "custom_output/backup.sqlite",
            "ENABLE_LOCAL_DB": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            with TemporaryDirectory() as tmpdir:
                cfg = db_sync.DatabaseConfig.from_env(Path(tmpdir))
                self.assertEqual(cfg.ch_host, "clickhouse.internal")
                self.assertEqual(cfg.ch_port, 9000)
                self.assertEqual(cfg.ch_user, "admin")
                self.assertEqual(cfg.ch_password, "secret_password")
                self.assertEqual(cfg.ch_database, "arkm_intel")
                self.assertTrue(cfg.ch_secure)
                self.assertTrue(cfg.enable_ch)
                self.assertTrue(cfg.strict)
                self.assertEqual(cfg.local_db_path.name, "backup.sqlite")

    def test_lighthouse_aliases_support(self):
        env = {
            "LIGHTHOUSE_HOST": "lh.internal",
            "LIGHTHOUSE_PORT": "8123",
            "LIGHTHOUSE_USER": "lh_user",
            "LIGHTHOUSE_PASSWORD": "lh_pass",
            "LIGHTHOUSE_DATABASE": "lh_db",
        }
        with patch.dict(os.environ, env, clear=True):
            with TemporaryDirectory() as tmpdir:
                cfg = db_sync.DatabaseConfig.from_env(Path(tmpdir))
                self.assertEqual(cfg.ch_host, "lh.internal")
                self.assertEqual(cfg.ch_user, "lh_user")
                self.assertEqual(cfg.ch_password, "lh_pass")
                self.assertEqual(cfg.ch_database, "lh_db")
                self.assertTrue(cfg.enable_ch)

    def test_single_endpoint_url_parsing(self):
        env = {
            "CLICKHOUSE_ENDPOINT": "https://api_key:my_secret@ch-cloud.example.com:8443/production_db",
        }
        with patch.dict(os.environ, env, clear=True):
            with TemporaryDirectory() as tmpdir:
                cfg = db_sync.DatabaseConfig.from_env(Path(tmpdir))
                self.assertEqual(cfg.ch_host, "ch-cloud.example.com")
                self.assertEqual(cfg.ch_port, 8443)
                self.assertEqual(cfg.ch_user, "api_key")
                self.assertEqual(cfg.ch_password, "my_secret")
                self.assertEqual(cfg.ch_database, "production_db")
                self.assertTrue(cfg.ch_secure)
                self.assertTrue(cfg.enable_ch)

    def test_load_env_file_parser(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            env_file = tmp / ".env"
            env_file.write_text(
                "# Comment\n"
                "CLICKHOUSE_HOST=dotenv.host.local\n"
                "CLICKHOUSE_PORT=8123\n"
                "CLICKHOUSE_DATABASE=env_db\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                cfg = db_sync.DatabaseConfig.from_env(tmp)
                self.assertEqual(cfg.ch_host, "dotenv.host.local")
                self.assertEqual(cfg.ch_database, "env_db")


class TestHelpersAndIngestion(unittest.TestCase):
    def test_clean_address(self):
        self.assertEqual(db_sync.clean_address('  0x1111"  '), "0x1111")
        self.assertEqual(db_sync.clean_address(" '0x2222' "), "0x2222")
        self.assertEqual(db_sync.clean_address(""), "")
        self.assertEqual(db_sync.clean_address(None), "")

    def test_parse_iso_datetime(self):
        dt = db_sync.parse_iso_datetime("2026-11-20T12:00:00Z")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.hour, 12)
        self.assertIsNone(dt.tzinfo)

        now_dt = datetime.now()
        self.assertEqual(db_sync.parse_iso_datetime(now_dt), now_dt)
        self.assertIsInstance(db_sync.parse_iso_datetime("invalid-string"), datetime)

    def test_load_crawl_datasets(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            api_out = tmp / "api_output"
            api_out.mkdir()

            deep = {
                "entities": {
                    "nobitex": {
                        "entity_name": "Nobitex.ir",
                        "wallets": [
                            {"address": "0x1111", "chain": "ethereum", "label": "Hot Wallet", "role": "Master"},
                            {"address": "0x2222", "chain": "ethereum", "label": "Nobitex Deposit"},
                        ],
                    }
                }
            }
            hot = {
                "hot_wallets": [
                    {
                        "exchange_id": "nobitex",
                        "exchange_name": "Nobitex.ir",
                        "address": "0x1111",
                        "chain": "ethereum",
                        "role": "Master Hot Wallet",
                        "label": "Nobitex Hot",
                        "source": "arkham",
                    }
                ]
            }
            swept = {
                "total_swept_wallets": 1,
                "wallets": [
                    {
                        "address": "T3333",
                        "chain": "tron",
                        "exchange": "Nobitex.ir",
                        "target_hot_wallet": "TPMF2n3",
                        "token_transferred": "USDT",
                    }
                ],
            }

            (api_out / "deep_iranian_exchanges_all_wallets.json").write_text(json.dumps(deep), encoding="utf-8")
            (api_out / "iranian_exchanges_hot_wallets.json").write_text(json.dumps(hot), encoding="utf-8")
            (api_out / "onchain_swept_wallets.json").write_text(json.dumps(swept), encoding="utf-8")

            wallets, hot_wallets, summary = db_sync.load_crawl_datasets(tmp)
            self.assertEqual(len(hot_wallets), 1)
            self.assertEqual(len(wallets), 3)
            self.assertEqual(summary["total_onchain_swept"], 1)

            # Check wallet classifications
            by_addr = {w["address"]: w for w in wallets}
            self.assertEqual(by_addr["0x1111"]["wallet_type"], "hot_wallet")
            self.assertEqual(by_addr["0x2222"]["wallet_type"], "deposit_wallet")
            self.assertEqual(by_addr["T3333"]["wallet_type"], "deposit_sweeper")
            self.assertEqual(by_addr["T3333"]["target_hot_wallet"], "TPMF2n3")
            self.assertEqual(by_addr["T3333"]["token_transferred"], "USDT")


class TestLocalSQLiteSync(unittest.TestCase):
    def test_sync_local_sqlite_create_and_append(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = tmp / "backup.db"

            sample_wallets = [
                {
                    "address": "0x1111",
                    "exchange_id": "nobitex",
                    "exchange_name": "Nobitex.ir",
                    "chain": "ethereum",
                    "wallet_type": "hot_wallet",
                    "role": "Master",
                    "label": "Nobitex Hot",
                    "source": "arkham",
                    "balance_usd": 150000.0,
                    "target_hot_wallet": "",
                    "token_transferred": "",
                    "first_seen": datetime(2026, 1, 1),
                    "updated_at": datetime(2026, 1, 1),
                }
            ]
            sample_hot = [
                {
                    "exchange_id": "nobitex",
                    "exchange_name": "Nobitex.ir",
                    "address": "0x1111",
                    "chain": "ethereum",
                    "role": "Master Hot Wallet",
                    "label": "Nobitex Hot",
                    "source": "arkham",
                    "updated_at": datetime(2026, 1, 1),
                }
            ]
            summary = {"total_onchain_swept": 0}

            # First run: tables should be created and 1 record inserted
            res1 = db_sync.sync_local_sqlite(sample_wallets, sample_hot, summary, db_path)
            self.assertEqual(res1["status"], "SUCCESS")
            self.assertEqual(res1["total_wallets_in_db"], 1)
            self.assertEqual(res1["total_hot_in_db"], 1)

            # Second run with new wallet added: should append without error
            sample_wallets.append({
                "address": "0x2222",
                "exchange_id": "nobitex",
                "exchange_name": "Nobitex.ir",
                "chain": "ethereum",
                "wallet_type": "deposit_wallet",
                "role": "",
                "label": "Deposit",
                "source": "transfers",
                "balance_usd": 0.0,
                "target_hot_wallet": "0x1111",
                "token_transferred": "USDT",
                "first_seen": datetime(2026, 2, 1),
                "updated_at": datetime(2026, 2, 1),
            })
            res2 = db_sync.sync_local_sqlite(sample_wallets, sample_hot, summary, db_path)
            self.assertEqual(res2["status"], "SUCCESS")
            self.assertEqual(res2["total_wallets_in_db"], 2)

            # Check database contents directly
            conn = sqlite3.connect(str(db_path))
            c = conn.cursor()
            c.execute("SELECT count(*) FROM sync_history")
            self.assertEqual(c.fetchone()[0], 2)

            c.execute("SELECT address, wallet_type, target_hot_wallet FROM wallets WHERE address='0x2222'")
            row = c.fetchone()
            self.assertEqual(row, ("0x2222", "deposit_wallet", "0x1111"))
            conn.close()


class MockClickHouseHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler simulating ClickHouse HTTP protocol."""

    queries_received: list[bytes] = []

    def do_GET(self):
        if self.path.startswith("/ping"):
            self.send_response(200)
            self.send_header("Content-Length", "3")
            self.end_headers()
            self.wfile.write(b"Ok\n")
        else:
            resp = b"24.3.1.1\tUTC\n"
            self.send_response(200)
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

    def do_POST(self):
        te = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in te:
            body = bytearray()
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                chunk_len = int(line.strip().split(b";")[0], 16)
                if chunk_len == 0:
                    self.rfile.readline()
                    break
                chunk = self.rfile.read(chunk_len)
                body.extend(chunk)
                self.rfile.readline()
            payload = bytes(body)
        else:
            length = int(self.headers.get("Content-Length", 0))
            payload = self.rfile.read(length) if length > 0 else b""

        self.__class__.queries_received.append(payload)

        self.send_response(200)
        if b"version()" in payload:
            resp = b"24.3.1.1\tUTC\n"
        else:
            resp = b""
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, format, *args):
        pass


class TestRemoteClickHouseSyncMocked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        MockClickHouseHandler.queries_received = []
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), MockClickHouseHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        MockClickHouseHandler.queries_received.clear()

    def test_clickhouse_full_sync_mocked(self):
        cfg = db_sync.DatabaseConfig(
            local_db_path=Path("/tmp/dummy.db"),
            enable_local=False,
            ch_host="127.0.0.1",
            ch_port=self.port,
            ch_user="test_user",
            ch_password="test_password",
            ch_database="default",
            ch_secure=False,
            enable_ch=True,
            strict=True,
        )

        sample_wallets = [
            {
                "address": "0x1111",
                "exchange_id": "nobitex",
                "exchange_name": "Nobitex.ir",
                "chain": "ethereum",
                "wallet_type": "hot_wallet",
                "role": "Master",
                "label": "Nobitex Hot",
                "source": "arkham",
                "balance_usd": 150000.0,
                "target_hot_wallet": "",
                "token_transferred": "",
                "first_seen": datetime(2026, 1, 1),
                "updated_at": datetime(2026, 1, 1),
            }
        ]
        sample_hot = [
            {
                "exchange_id": "nobitex",
                "exchange_name": "Nobitex.ir",
                "address": "0x1111",
                "chain": "ethereum",
                "role": "Master Hot Wallet",
                "label": "Nobitex Hot",
                "source": "arkham",
                "updated_at": datetime(2026, 1, 1),
            }
        ]
        summary = {"total_onchain_swept": 0}

        res = db_sync.sync_remote_clickhouse(sample_wallets, sample_hot, summary, cfg)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["wallets_inserted"], 1)
        self.assertEqual(res["hot_wallets_inserted"], 1)

        # Inspect queries received by ClickHouse mock
        all_payloads = b"".join(MockClickHouseHandler.queries_received)
        self.assertIn(b"CREATE TABLE IF NOT EXISTS", all_payloads)
        self.assertIn(b"wallets", all_payloads)
        self.assertIn(b"hot_wallets", all_payloads)
        self.assertIn(b"sync_history", all_payloads)

    def test_clickhouse_unreachable_strict_mode(self):
        # Point to closed port
        cfg = db_sync.DatabaseConfig(
            local_db_path=Path("/tmp/dummy.db"),
            enable_local=False,
            ch_host="127.0.0.1",
            ch_port=65432,  # Closed port
            ch_user="default",
            enable_ch=True,
            strict=True,
        )
        with self.assertRaises(Exception):
            db_sync.sync_remote_clickhouse([], [], {}, cfg)

    def test_execute_dual_sync_orchestrator(self):
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            api_out = tmp / "api_output"
            api_out.mkdir()
            (api_out / "deep_iranian_exchanges_all_wallets.json").write_text(
                json.dumps({"entities": {}}), encoding="utf-8"
            )
            (api_out / "iranian_exchanges_hot_wallets.json").write_text(
                json.dumps({"hot_wallets": []}), encoding="utf-8"
            )

            cfg = db_sync.DatabaseConfig(
                local_db_path=api_out / "crawler_backup.db",
                enable_local=True,
                ch_host="127.0.0.1",
                ch_port=self.port,
                ch_user="test_user",
                ch_password="test_password",
                ch_database="default",
                enable_ch=True,
                strict=False,
            )

            results = db_sync.execute_dual_sync(base_dir=tmp, config=cfg)
            self.assertEqual(results["local_sqlite"]["status"], "SUCCESS")
            self.assertEqual(results["clickhouse"]["status"], "SUCCESS")
            self.assertTrue((api_out / "crawler_backup.db").exists())


class TestPipelineDatabaseStage(unittest.TestCase):
    def test_run_pipeline_arguments_parsing(self):
        code = run_pipeline.main(["--skip-arkm", "--skip-onchain", "--skip-aggregate", "--skip-db"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
