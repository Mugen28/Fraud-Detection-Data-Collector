#!/usr/bin/env python3
"""
db_sync.py
==========
Dual Database Synchronization Engine for Iranian Exchanges Intelligence Suite.

Synchronizes crawled exchange datasets into:
  1. Local Backup Database: SQLite (atomic, file-based, zero-dependency).
  2. Remote ClickHouse / LightHouse Database: High-performance columnar analytics,
     compatible with VKCOM/lighthouse web interface.

Key Features:
  - Schema Auto-Creation: If tables do not exist, they are created automatically.
  - Safe Append & Upsert: If tables exist, new data is appended and updated idempotently.
  - Configurable via Environment: Supports full endpoint URL or separate credentials.
  - Resilient Fallback: Local backup is always saved even if remote ClickHouse is offline.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent

# ==============================================================================
# Helper Functions & Utilities
# ==============================================================================

def clean_address(addr: str) -> str:
    """Sanitize cryptocurrency addresses by stripping whitespace and escaped quotes."""
    if not addr:
        return ""
    return str(addr).strip().strip('"\'').strip()

def parse_iso_datetime(val: Any) -> datetime:
    """Parse various datetime representations into a UTC datetime object."""
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            return val.astimezone(timezone.utc).replace(tzinfo=None)
        return val
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=timezone.utc).replace(tzinfo=None)
    if isinstance(val, str) and val.strip():
        s = val.strip()
        try:
            # Handle ISO-8601 strings with Z or timezone offset
            s_clean = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s_clean)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            pass
    return datetime.now(timezone.utc).replace(tzinfo=None)

def load_env_file(path: Path) -> None:
    """Lightweight .env loader that populates os.environ without overwriting existing keys."""
    if not path.exists():
        return
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"\'')
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as exc:
        print(f"[!] Warning: Could not read .env file at {path}: {exc}", file=sys.stderr)

# ==============================================================================
# Database Configuration
# ==============================================================================

@dataclass
class DatabaseConfig:
    # Local SQLite
    local_db_path: Path
    enable_local: bool = True

    # Remote ClickHouse / LightHouse
    ch_host: str = ""
    ch_port: int = 8123
    ch_user: str = "default"
    ch_password: str = ""
    ch_database: str = "default"
    ch_secure: bool = False
    enable_ch: bool = False
    strict: bool = False

    @classmethod
    def from_env(cls, base_dir: Path | None = None) -> "DatabaseConfig":
        root = base_dir or BASE_DIR
        load_env_file(root / ".env")

        # Local SQLite path
        local_path_raw = os.environ.get("LOCAL_DB_PATH", "api_output/crawler_backup.db")
        local_path = Path(local_path_raw)
        if not local_path.is_absolute():
            local_path = root / local_path

        enable_local = os.environ.get("ENABLE_LOCAL_DB", "true").lower() in ("1", "true", "yes")

        # ClickHouse / LightHouse Endpoint Parsing
        # Supports CLICKHOUSE_ENDPOINT or LIGHTHOUSE_ENDPOINT
        endpoint = os.environ.get("CLICKHOUSE_ENDPOINT") or os.environ.get("LIGHTHOUSE_ENDPOINT") or ""
        host = os.environ.get("CLICKHOUSE_HOST") or os.environ.get("LIGHTHOUSE_HOST") or ""
        port_raw = os.environ.get("CLICKHOUSE_PORT") or os.environ.get("LIGHTHOUSE_PORT") or "8123"
        user = os.environ.get("CLICKHOUSE_USER") or os.environ.get("LIGHTHOUSE_USER") or "default"
        password = os.environ.get("CLICKHOUSE_PASSWORD") or os.environ.get("LIGHTHOUSE_PASSWORD") or ""
        database = os.environ.get("CLICKHOUSE_DATABASE") or os.environ.get("LIGHTHOUSE_DATABASE") or "default"
        secure_raw = os.environ.get("CLICKHOUSE_SECURE") or os.environ.get("LIGHTHOUSE_SECURE") or ""
        strict = os.environ.get("CLICKHOUSE_STRICT", "false").lower() in ("1", "true", "yes")

        try:
            port = int(port_raw)
        except ValueError:
            port = 8123

        secure = False
        if secure_raw:
            secure = secure_raw.lower() in ("1", "true", "yes")
        elif port == 8443:
            secure = True

        # Parse full endpoint URL if supplied
        if endpoint:
            parsed = urlparse(endpoint)
            if parsed.hostname:
                host = parsed.hostname
            if parsed.port:
                port = parsed.port
            if parsed.username:
                user = unquote(parsed.username)
            if parsed.password:
                password = unquote(parsed.password)
            if parsed.path and parsed.path.strip("/"):
                database = parsed.path.strip("/")
            if parsed.scheme == "https":
                secure = True

        # Auto-enable ClickHouse if host or endpoint is specified
        enable_ch_env = os.environ.get("ENABLE_CLICKHOUSE") or os.environ.get("ENABLE_LIGHTHOUSE")
        if enable_ch_env is not None:
            enable_ch = enable_ch_env.lower() in ("1", "true", "yes")
        else:
            enable_ch = bool(host.strip())

        return cls(
            local_db_path=local_path,
            enable_local=enable_local,
            ch_host=host.strip(),
            ch_port=port,
            ch_user=user,
            ch_password=password,
            ch_database=database,
            ch_secure=secure,
            enable_ch=enable_ch,
            strict=strict,
        )

# ==============================================================================
# Dataset Ingestion & Normalization
# ==============================================================================

EXCHANGE_NAME_TO_ID = {
    "Nobitex.ir": "nobitex",
    "Wallex": "wallex-ir",
    "Bitpin": "bitpin",
    "Bit24": "bit24",
    "Ramzinex": "ramzinex",
    "AbanTether": "abantether",
    "Excoino": "excoino",
    "ArzPaya": "arzpaya-com",
    "Farhad Exchange": "farhad-exchange",
}

def load_crawl_datasets(base_dir: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Ingest all generated crawler files and produce unified record lists.
    Returns:
      (wallets_list, hot_wallets_list, summary_dict)
    """
    deep_path = base_dir / "api_output" / "deep_iranian_exchanges_all_wallets.json"
    hot_path = base_dir / "api_output" / "iranian_exchanges_hot_wallets.json"
    swept_path = base_dir / "api_output" / "onchain_swept_wallets.json"

    deep_data: Dict[str, Any] = {}
    hot_data: Dict[str, Any] = {}
    swept_data: Dict[str, Any] = {}

    if deep_path.exists():
        try:
            deep_data = json.loads(deep_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[!] Warning reading {deep_path.name}: {exc}", file=sys.stderr)

    if hot_path.exists():
        try:
            hot_data = json.loads(hot_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[!] Warning reading {hot_path.name}: {exc}", file=sys.stderr)

    if swept_path.exists():
        try:
            swept_data = json.loads(swept_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[!] Warning reading {swept_path.name}: {exc}", file=sys.stderr)

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 1. Process Hot Wallets
    hot_wallets_clean: List[Dict[str, Any]] = []
    hot_keys: Set[Tuple[str, str, str]] = set()

    for item in hot_data.get("hot_wallets", []):
        addr = clean_address(item.get("address", ""))
        chain = str(item.get("chain", "")).strip().lower()
        ex_id = str(item.get("exchange_id", "")).strip().lower()
        ex_name = str(item.get("exchange_name") or item.get("exchange") or ex_id).strip()
        if not addr or not chain or not ex_id:
            continue
        key = (ex_id, chain, addr.lower())
        if key in hot_keys:
            continue
        hot_keys.add(key)
        hot_wallets_clean.append({
            "exchange_id": ex_id,
            "exchange_name": ex_name,
            "address": addr,
            "chain": chain,
            "role": str(item.get("role", "Master Hot Wallet")).strip(),
            "label": str(item.get("label", "")).strip(),
            "source": str(item.get("source", "")).strip(),
            "updated_at": now,
        })

    # 2. Unified Master Wallets Map
    wallets_map: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    # Ingest from deep_iranian_exchanges_all_wallets.json
    for eid, edata in deep_data.get("entities", {}).items():
        ex_id = str(eid).strip().lower()
        ex_name = str(edata.get("entity_name") or ex_id).strip()
        for w in edata.get("wallets", []):
            addr = clean_address(w.get("address", ""))
            chain = str(w.get("chain", "unknown")).strip().lower()
            if not addr:
                continue
            key = (ex_id, chain, addr.lower())
            label = str(w.get("label", "")).strip()
            role = str(w.get("role", "")).strip()
            source = str(w.get("source", "")).strip()

            if key in hot_keys:
                wtype = "hot_wallet"
            elif "deposit" in label.lower() or "deposit" in role.lower():
                wtype = "deposit_wallet"
            else:
                wtype = "exchange_wallet"

            wallets_map[key] = {
                "address": addr,
                "exchange_id": ex_id,
                "exchange_name": ex_name,
                "chain": chain,
                "wallet_type": wtype,
                "role": role,
                "label": label,
                "source": source,
                "balance_usd": 0.0,
                "target_hot_wallet": "",
                "token_transferred": "",
                "first_seen": now,
                "updated_at": now,
            }

    # Ingest from onchain_swept_wallets.json
    for ow in swept_data.get("wallets", []):
        addr = clean_address(ow.get("address", ""))
        chain = str(ow.get("chain", "unknown")).strip().lower()
        if not addr:
            continue
        ex_name = str(ow.get("exchange", "Unknown Exchange")).strip()
        ex_id = EXCHANGE_NAME_TO_ID.get(ex_name, ex_name.lower().replace(" ", "_").replace(".", "_"))
        key = (ex_id, chain, addr.lower())

        target_hw = clean_address(ow.get("target_hot_wallet", ""))
        token = str(ow.get("token_transferred", "")).strip()
        first_seen = parse_iso_datetime(ow.get("first_seen"))
        label = str(ow.get("label", "User Deposit / Sweeper Wallet")).strip()
        source = str(ow.get("source", "onchain/sweeper")).strip()

        if key in wallets_map:
            # Update metadata
            wallets_map[key]["target_hot_wallet"] = target_hw
            wallets_map[key]["token_transferred"] = token
            wallets_map[key]["updated_at"] = now
            if not wallets_map[key]["source"]:
                wallets_map[key]["source"] = source
        else:
            wtype = "hot_wallet" if key in hot_keys else "deposit_sweeper"
            wallets_map[key] = {
                "address": addr,
                "exchange_id": ex_id,
                "exchange_name": ex_name,
                "chain": chain,
                "wallet_type": wtype,
                "role": "Deposit Swept Wallet",
                "label": label,
                "source": source,
                "balance_usd": 0.0,
                "target_hot_wallet": target_hw,
                "token_transferred": token,
                "first_seen": first_seen,
                "updated_at": now,
            }

    # Also make sure all hot wallets exist in the wallets_map
    for hw in hot_wallets_clean:
        key = (hw["exchange_id"], hw["chain"], hw["address"].lower())
        if key not in wallets_map:
            wallets_map[key] = {
                "address": hw["address"],
                "exchange_id": hw["exchange_id"],
                "exchange_name": hw["exchange_name"],
                "chain": hw["chain"],
                "wallet_type": "hot_wallet",
                "role": hw["role"],
                "label": hw["label"],
                "source": hw["source"],
                "balance_usd": 0.0,
                "target_hot_wallet": "",
                "token_transferred": "",
                "first_seen": now,
                "updated_at": now,
            }

    all_wallets = list(wallets_map.values())

    summary = {
        "total_wallets": len(all_wallets),
        "total_hot_wallets": len(hot_wallets_clean),
        "total_onchain_swept": swept_data.get("total_swept_wallets", 0),
        "generated_at": now.isoformat(),
    }

    return all_wallets, hot_wallets_clean, summary

# ==============================================================================
# Local SQLite Synchronization
# ==============================================================================

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    address TEXT NOT NULL,
    exchange_id TEXT NOT NULL,
    exchange_name TEXT NOT NULL,
    chain TEXT NOT NULL,
    wallet_type TEXT NOT NULL,
    role TEXT DEFAULT '',
    label TEXT DEFAULT '',
    source TEXT DEFAULT '',
    balance_usd REAL DEFAULT 0.0,
    target_hot_wallet TEXT DEFAULT '',
    token_transferred TEXT DEFAULT '',
    first_seen TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (exchange_id, chain, address)
);

CREATE TABLE IF NOT EXISTS hot_wallets (
    exchange_id TEXT NOT NULL,
    exchange_name TEXT NOT NULL,
    address TEXT NOT NULL,
    chain TEXT NOT NULL,
    role TEXT DEFAULT '',
    label TEXT DEFAULT '',
    source TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (exchange_id, chain, address)
);

CREATE TABLE IF NOT EXISTS sync_history (
    sync_id TEXT PRIMARY KEY,
    synced_at TEXT NOT NULL,
    total_wallets INTEGER NOT NULL,
    total_hot_wallets INTEGER NOT NULL,
    total_swept INTEGER NOT NULL,
    status TEXT NOT NULL,
    details TEXT DEFAULT ''
);
"""

def sync_local_sqlite(
    wallets: List[Dict[str, Any]],
    hot_wallets: List[Dict[str, Any]],
    summary: Dict[str, Any],
    db_path: Path,
) -> Dict[str, Any]:
    """Synchronize crawled datasets into local SQLite backup database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        # Create tables if not exist
        cursor.executescript(SQLITE_SCHEMA)

        # Prepare wallet rows
        wallet_rows = [
            (
                w["address"],
                w["exchange_id"],
                w["exchange_name"],
                w["chain"],
                w["wallet_type"],
                w["role"],
                w["label"],
                w["source"],
                float(w.get("balance_usd", 0.0)),
                w["target_hot_wallet"],
                w["token_transferred"],
                w["first_seen"].isoformat() if isinstance(w["first_seen"], datetime) else str(w["first_seen"]),
                w["updated_at"].isoformat() if isinstance(w["updated_at"], datetime) else str(w["updated_at"]),
            )
            for w in wallets
        ]

        # Upsert wallets
        cursor.executemany(
            """
            INSERT INTO wallets (
                address, exchange_id, exchange_name, chain, wallet_type,
                role, label, source, balance_usd, target_hot_wallet,
                token_transferred, first_seen, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange_id, chain, address) DO UPDATE SET
                exchange_name = excluded.exchange_name,
                wallet_type = excluded.wallet_type,
                role = excluded.role,
                label = excluded.label,
                source = excluded.source,
                balance_usd = excluded.balance_usd,
                target_hot_wallet = excluded.target_hot_wallet,
                token_transferred = excluded.token_transferred,
                updated_at = excluded.updated_at
            """,
            wallet_rows,
        )

        # Prepare hot wallet rows
        hot_rows = [
            (
                hw["exchange_id"],
                hw["exchange_name"],
                hw["address"],
                hw["chain"],
                hw["role"],
                hw["label"],
                hw["source"],
                hw["updated_at"].isoformat() if isinstance(hw["updated_at"], datetime) else str(hw["updated_at"]),
            )
            for hw in hot_wallets
        ]

        # Upsert hot wallets
        cursor.executemany(
            """
            INSERT INTO hot_wallets (
                exchange_id, exchange_name, address, chain, role, label, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange_id, chain, address) DO UPDATE SET
                exchange_name = excluded.exchange_name,
                role = excluded.role,
                label = excluded.label,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            hot_rows,
        )

        # Record in sync_history
        sync_id = str(uuid.uuid4())
        now_str = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            INSERT INTO sync_history (
                sync_id, synced_at, total_wallets, total_hot_wallets, total_swept, status, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sync_id,
                now_str,
                len(wallets),
                len(hot_wallets),
                summary.get("total_onchain_swept", 0),
                "SUCCESS",
                f"Local backup synced to {db_path.name}",
            ),
        )

        conn.commit()

        # Count total in tables
        cursor.execute("SELECT count(*) FROM wallets")
        total_wallets_db = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM hot_wallets")
        total_hot_db = cursor.fetchone()[0]

        return {
            "status": "SUCCESS",
            "db_path": str(db_path),
            "wallets_upserted": len(wallets),
            "hot_wallets_upserted": len(hot_wallets),
            "total_wallets_in_db": total_wallets_db,
            "total_hot_in_db": total_hot_db,
        }
    finally:
        conn.close()

# ==============================================================================
# Remote ClickHouse / LightHouse Synchronization
# ==============================================================================

def get_clickhouse_client(config: DatabaseConfig) -> Any:
    """Instantiate and test a ClickHouse client via clickhouse-connect."""
    try:
        import clickhouse_connect
    except ImportError as exc:
        raise RuntimeError(
            "clickhouse-connect is not installed. Install it via `pip install clickhouse-connect`."
        ) from exc

    # 1. Connect first to verify and create target database if needed
    client = clickhouse_connect.get_client(
        host=config.ch_host,
        port=config.ch_port,
        username=config.ch_user,
        password=config.ch_password,
        secure=config.ch_secure,
        connect_timeout=15,
        send_receive_timeout=30,
    )

    if config.ch_database and config.ch_database != "default":
        client.command(f"CREATE DATABASE IF NOT EXISTS `{config.ch_database}`")
        # Reconnect directly to target database
        client = clickhouse_connect.get_client(
            host=config.ch_host,
            port=config.ch_port,
            username=config.ch_user,
            password=config.ch_password,
            database=config.ch_database,
            secure=config.ch_secure,
            connect_timeout=15,
            send_receive_timeout=30,
        )

    return client

def sync_remote_clickhouse(
    wallets: List[Dict[str, Any]],
    hot_wallets: List[Dict[str, Any]],
    summary: Dict[str, Any],
    config: DatabaseConfig,
) -> Dict[str, Any]:
    """
    Synchronize crawled datasets into remote ClickHouse / LightHouse.
    Creates tables if not exists, and appends/updates records idempotently.
    """
    if not config.enable_ch or not config.ch_host:
        return {
            "status": "SKIPPED",
            "message": "ClickHouse / LightHouse sync disabled or host not provided.",
        }

    client = get_clickhouse_client(config)
    db = config.ch_database or "default"

    # Schema Definitions using ReplacingMergeTree for automatic deduplication & append
    create_wallets_sql = f"""
    CREATE TABLE IF NOT EXISTS `{db}`.`wallets` (
        address String,
        exchange_id String,
        exchange_name String,
        chain String,
        wallet_type String,
        role String DEFAULT '',
        label String DEFAULT '',
        source String DEFAULT '',
        balance_usd Float64 DEFAULT 0.0,
        target_hot_wallet String DEFAULT '',
        token_transferred String DEFAULT '',
        first_seen DateTime,
        updated_at DateTime
    ) ENGINE = ReplacingMergeTree(updated_at)
    ORDER BY (exchange_id, chain, address);
    """

    create_hot_wallets_sql = f"""
    CREATE TABLE IF NOT EXISTS `{db}`.`hot_wallets` (
        exchange_id String,
        exchange_name String,
        address String,
        chain String,
        role String DEFAULT '',
        label String DEFAULT '',
        source String DEFAULT '',
        updated_at DateTime
    ) ENGINE = ReplacingMergeTree(updated_at)
    ORDER BY (exchange_id, chain, address);
    """

    create_sync_history_sql = f"""
    CREATE TABLE IF NOT EXISTS `{db}`.`sync_history` (
        sync_id String,
        synced_at DateTime,
        total_wallets UInt32,
        total_hot_wallets UInt32,
        total_swept UInt32,
        status String,
        details String
    ) ENGINE = MergeTree()
    ORDER BY (synced_at, sync_id);
    """

    # 1. Create tables if not exist
    client.command(create_wallets_sql)
    client.command(create_hot_wallets_sql)
    client.command(create_sync_history_sql)

    # 2. Insert wallets
    wallet_cols = [
        "address", "exchange_id", "exchange_name", "chain", "wallet_type",
        "role", "label", "source", "balance_usd", "target_hot_wallet",
        "token_transferred", "first_seen", "updated_at",
    ]
    wallet_types = [
        "String", "String", "String", "String", "String",
        "String", "String", "String", "Float64", "String",
        "String", "DateTime", "DateTime",
    ]
    wallet_rows = [
        [
            w["address"],
            w["exchange_id"],
            w["exchange_name"],
            w["chain"],
            w["wallet_type"],
            w["role"],
            w["label"],
            w["source"],
            float(w.get("balance_usd", 0.0)),
            w["target_hot_wallet"],
            w["token_transferred"],
            parse_iso_datetime(w["first_seen"]),
            parse_iso_datetime(w["updated_at"]),
        ]
        for w in wallets
    ]

    if wallet_rows:
        client.insert(
            "wallets",
            wallet_rows,
            column_names=wallet_cols,
            column_type_names=wallet_types,
            database=db,
        )

    # 3. Insert hot wallets
    hot_cols = [
        "exchange_id", "exchange_name", "address", "chain",
        "role", "label", "source", "updated_at",
    ]
    hot_types = [
        "String", "String", "String", "String",
        "String", "String", "String", "DateTime",
    ]
    hot_rows = [
        [
            hw["exchange_id"],
            hw["exchange_name"],
            hw["address"],
            hw["chain"],
            hw["role"],
            hw["label"],
            hw["source"],
            parse_iso_datetime(hw["updated_at"]),
        ]
        for hw in hot_wallets
    ]

    if hot_rows:
        client.insert(
            "hot_wallets",
            hot_rows,
            column_names=hot_cols,
            column_type_names=hot_types,
            database=db,
        )

    # 4. Insert sync record
    sync_id = str(uuid.uuid4())
    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    client.insert(
        "sync_history",
        [[
            sync_id,
            now_dt,
            len(wallets),
            len(hot_wallets),
            summary.get("total_onchain_swept", 0),
            "SUCCESS",
            "Pipeline synced to ClickHouse/LightHouse",
        ]],
        column_names=["sync_id", "synced_at", "total_wallets", "total_hot_wallets", "total_swept", "status", "details"],
        column_type_names=["String", "DateTime", "UInt32", "UInt32", "UInt32", "String", "String"],
        database=db,
    )

    return {
        "status": "SUCCESS",
        "endpoint": f"{config.ch_host}:{config.ch_port}/{db}",
        "wallets_inserted": len(wallet_rows),
        "hot_wallets_inserted": len(hot_rows),
    }

# ==============================================================================
# Master Synchronization Orchestrator
# ==============================================================================

def execute_dual_sync(
    base_dir: Path | None = None,
    config: DatabaseConfig | None = None,
    local_only: bool = False,
) -> Dict[str, Any]:
    """Execute both local SQLite and remote ClickHouse/LightHouse synchronizations."""
    root = base_dir or BASE_DIR
    cfg = config or DatabaseConfig.from_env(root)

    t0 = time.time()
    now_str = datetime.now().strftime("%H:%M:%S")

    print(f"\n{'='*70}")
    print(f"[{now_str}] Dual Database Sync Engine (Local SQLite + ClickHouse / LightHouse)")
    print(f"{'='*70}")
    print(f"  Root Directory: {root}")
    print(f"  Local DB Target: {cfg.local_db_path}")
    if cfg.enable_ch and not local_only:
        scheme = "https" if cfg.ch_secure else "http"
        print(f"  ClickHouse Target: {scheme}://{cfg.ch_user}@{cfg.ch_host}:{cfg.ch_port}/{cfg.ch_database}")
    else:
        print("  ClickHouse Target: [Disabled / No Host Configured]")
    print(f"{'='*70}\n")

    # Ingest datasets
    wallets, hot_wallets, summary = load_crawl_datasets(root)
    print(f"📊 Loaded Crawled Datasets:")
    print(f"   • Total Master Wallets : {len(wallets):,}")
    print(f"   • Confirmed Hot Wallets: {len(hot_wallets):,}")
    print(f"   • On-Chain Swept Count : {summary.get('total_onchain_swept', 0):,}\n")

    results: Dict[str, Any] = {
        "summary": summary,
        "local_sqlite": None,
        "clickhouse": None,
    }

    # 1. Local SQLite Sync
    if cfg.enable_local:
        try:
            loc_res = sync_local_sqlite(wallets, hot_wallets, summary, cfg.local_db_path)
            results["local_sqlite"] = loc_res
            print(f"✅ Local SQLite Backup Synced: {cfg.local_db_path.name}")
            print(f"   • Wallets in DB: {loc_res['total_wallets_in_db']:,}")
            print(f"   • Hot Wallets in DB: {loc_res['total_hot_in_db']:,}")
        except Exception as exc:
            results["local_sqlite"] = {"status": "FAILED", "error": str(exc)}
            print(f"❌ Local SQLite Backup Error: {exc}", file=sys.stderr)
            if cfg.strict:
                raise
    else:
        results["local_sqlite"] = {"status": "SKIPPED"}
        print("⏩ Local SQLite Backup: Disabled")

    # 2. Remote ClickHouse / LightHouse Sync
    if cfg.enable_ch and not local_only:
        try:
            ch_res = sync_remote_clickhouse(wallets, hot_wallets, summary, cfg)
            results["clickhouse"] = ch_res
            print(f"✅ ClickHouse / LightHouse Synced Successfully:")
            print(f"   • Endpoint: {ch_res.get('endpoint')}")
            print(f"   • Wallets Appended/Updated: {ch_res.get('wallets_inserted'):,}")
            print(f"   • Hot Wallets Appended/Updated: {ch_res.get('hot_wallets_inserted'):,}")
        except Exception as exc:
            results["clickhouse"] = {"status": "FAILED", "error": str(exc)}
            print(f"❌ ClickHouse / LightHouse Sync Failed: {exc}", file=sys.stderr)
            if cfg.strict:
                raise
            else:
                print("   ℹ️  Continuing since ClickHouse is optional and local backup succeeded.")
    else:
        results["clickhouse"] = {"status": "SKIPPED"}
        if local_only:
            print("⏩ ClickHouse Sync: Skipped (--local-only flag).")
        else:
            print("⏩ ClickHouse Sync: Skipped (no host configured in .env).")

    elapsed = time.time() - t0
    print(f"\n[OK] Database synchronization completed in {elapsed:.2f}s.\n")
    return results

# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dual Database Synchronizer for Iranian Exchanges Intelligence Suite.")
    parser.add_argument("--local-only", action="store_true", help="Sync only the local SQLite database.")
    parser.add_argument("--strict", action="store_true", help="Fail with exit code 1 if ClickHouse sync fails.")
    parser.add_argument("--base-dir", type=str, default="", help="Path to project root directory.")
    parser.add_argument("--check", action="store_true", help="Test database connection and verify schemas.")
    args = parser.parse_args(argv)

    base_path = Path(args.base_dir).resolve() if args.base_dir else BASE_DIR
    config = DatabaseConfig.from_env(base_path)
    if args.strict:
        config.strict = True

    if args.check:
        print("\n🔍 Checking Database Connections & Schemas...")
        # Check Local SQLite
        if config.local_db_path.exists():
            try:
                conn = sqlite3.connect(str(config.local_db_path))
                c = conn.cursor()
                c.execute("SELECT count(*) FROM wallets")
                w_cnt = c.fetchone()[0]
                c.execute("SELECT count(*) FROM hot_wallets")
                h_cnt = c.fetchone()[0]
                conn.close()
                print(f"  • Local SQLite [{config.local_db_path.name}]: Connected (Wallets: {w_cnt:,}, Hot: {h_cnt:,})")
            except Exception as e:
                print(f"  • Local SQLite [{config.local_db_path.name}]: Error reading ({e})")
        else:
            print(f"  • Local SQLite: File {config.local_db_path} does not exist yet (will be created on first sync).")

        # Check ClickHouse
        if config.enable_ch and config.ch_host:
            try:
                client = get_clickhouse_client(config)
                v = client.command("SELECT version()")
                print(f"  • ClickHouse / LightHouse [{config.ch_host}:{config.ch_port}]: Connected (Version: {v})")
            except Exception as e:
                print(f"  • ClickHouse / LightHouse [{config.ch_host}:{config.ch_port}]: Connection failed ({e})")
        else:
            print("  • ClickHouse / LightHouse: Not configured in .env.")
        return 0

    try:
        res = execute_dual_sync(base_path, config, local_only=args.local_only)
        local_ok = res.get("local_sqlite", {}).get("status") in ("SUCCESS", "SKIPPED")
        ch_ok = res.get("clickhouse", {}).get("status") in ("SUCCESS", "SKIPPED")
        if not local_ok or (config.strict and not ch_ok):
            return 1
        return 0
    except Exception as exc:
        print(f"\nFATAL: Database synchronization failed: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
