#!/usr/bin/env python3
"""
run_pipeline.py
===============
Master Pipeline Runner for Iranian Exchanges Intelligence Suite.

Executes all extraction stages sequentially:
  Stage 1: Multi-Chain & Depth-2 Arkham Crawling (deep_arkm_crawler.py)
  Stage 2: Direct On-Chain Gateway Sweeping (onchain_wallet_sweeper.py)
  Stage 3: Hot Wallet Convergence, EVM Expansion & Master Aggregation (extract_hot_wallets_and_aggregate.py)
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from api_generator import arkham_session_ready

BASE_DIR = Path(__file__).resolve().parent

def log(msg: str) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'='*70}\n[{now}] {msg}\n{'='*70}")

def run_step(step_name: str, cmd: list[str]) -> bool:
    log(f"STAGE: {step_name}")
    start = time.time()
    try:
        res = subprocess.run(cmd, cwd=str(BASE_DIR), check=True)
        elapsed = time.time() - start
        print(f"\n[OK] {step_name} completed successfully in {elapsed:.1f}s.")
        return True
    except subprocess.CalledProcessError as err:
        elapsed = time.time() - start
        print(f"\n[FAIL] {step_name} failed with exit code {err.returncode} ({elapsed:.1f}s).", file=sys.stderr)
        return False
    except OSError as err:
        elapsed = time.time() - start
        print(f"\n[FAIL] {step_name} could not be started ({elapsed:.1f}s): {err}", file=sys.stderr)
        return False

def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Master Pipeline Runner for Iranian Exchanges Crawler.")
    parser.add_argument("--skip-arkm", action="store_true", help="Skip Arkham Multi-Chain/Depth-2 crawling step.")
    parser.add_argument("--skip-onchain", action="store_true", help="Skip direct TronGrid/Blockstream on-chain sweeping step.")
    parser.add_argument("--skip-aggregate", action="store_true", help="Skip hot wallet extraction and aggregation step.")
    parser.add_argument("--skip-db", action="store_true", help="Skip dual database synchronization step (Local SQLite + ClickHouse).")
    parser.add_argument("--db-strict", action="store_true", help="Fail pipeline if ClickHouse database sync fails.")
    parser.add_argument("--onchain-pages", type=positive_int, default=5, help="Number of pages per hot wallet in on-chain sweeper.")
    parser.add_argument("--depth2-limit", type=positive_int, default=50, help="Limit of incoming transfers in depth-2 scraping.")
    parser.add_argument("--delay", type=float, default=1.2, help="Delay between Arkham API requests (seconds).")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    if args.delay < 0:
        print("ERROR: --delay must be >= 0.", file=sys.stderr)
        return 2

    python_bin = sys.executable

    print(f"""
======================================================================
 Iranian Exchanges Intelligence Pipeline - Full Execution
======================================================================
 Python Interpreter: {python_bin}
 Root Workspace:     {BASE_DIR}
 Timestamp:          {datetime.now().isoformat()}
======================================================================
""")

    # Stage 1: Arkham Deep Crawl
    if not args.skip_arkm:
        session_file = BASE_DIR / "storage_state.json"
        if not arkham_session_ready(session_file):
            print(
                "ERROR: storage_state.json has no usable arkham_session cookie. "
                "Run `python3 api_generator.py login` or `./run.sh --login`. Skipping Arkham stage.",
                file=sys.stderr,
            )
        else:
            cmd_arkm = [
                python_bin,
                str(BASE_DIR / "deep_arkm_crawler.py"),
                "--depth2-limit", str(args.depth2_limit),
                "--transfers-per-chain", "100",
                "--delay", str(args.delay),
            ]
            if not run_step("1. Arkham Multi-Chain & Depth-2 Crawler", cmd_arkm):
                print("Warning: Arkham crawler stage encountered errors. Continuing pipeline...")

    # Stage 2: Direct On-Chain Sweeper
    if not args.skip_onchain:
        cmd_onchain = [
            python_bin,
            str(BASE_DIR / "onchain_wallet_sweeper.py"),
            "--pages", str(args.onchain_pages),
            "--limit", "50",
        ]
        if not run_step("2. On-Chain TronGrid & Bitcoin Sweeper", cmd_onchain):
            print("Warning: On-chain sweeper stage encountered errors. Continuing pipeline...")

    # Stage 3: Master Aggregation & Hot Wallet Detection
    if not args.skip_aggregate:
        cmd_agg = [
            python_bin,
            str(BASE_DIR / "extract_hot_wallets_and_aggregate.py"),
        ]
        if not run_step("3. Hot Wallet Convergence & Master Aggregation", cmd_agg):
            return 1

    # Stage 4: Dual Database Synchronization (Local SQLite + ClickHouse/LightHouse)
    if not args.skip_db:
        cmd_db = [
            python_bin,
            str(BASE_DIR / "db_sync.py"),
        ]
        if args.db_strict:
            cmd_db.append("--strict")
        if not run_step("4. Dual Database Sync (Local SQLite + ClickHouse/LightHouse)", cmd_db):
            if args.db_strict:
                return 1
            print("Warning: Database synchronization encountered non-fatal errors. Continuing...")

    log("PIPELINE EXECUTION COMPLETE")
    print("""
All stages have finished. Datasets are written under api_output/:
  - iranian_exchanges_hot_wallets.json
  - iranian_exchanges_hot_wallets.md
  - deep_iranian_exchanges_all_wallets.json
  - onchain_swept_wallets.json
  - crawler_backup.db (Local SQLite Database Backup)
""")
    return 0

if __name__ == "__main__":
    sys.exit(main())

