#!/usr/bin/env python3
"""
scheduler.py
============
Automated Daily Daemon Service with Jitter for Iranian Crypto Exchanges Crawler.

Features:
1. Continuous 24h cron-like execution with randomized human-like jitter (e.g. 24h ± 2h).
2. Prevents Cloudflare detection by varying request schedules across days.
3. Automatically computes delta stats (newly discovered wallets per cycle).
4. Graceful termination on SIGINT / SIGTERM signals.
"""

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MASTER_DB = BASE_DIR / "api_output" / "deep_iranian_exchanges_all_wallets.json"

RUNNING = True

def signal_handler(signum, frame):
    global RUNNING
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Received stop signal ({signum}). Gracefully shutting down scheduler...")
    RUNNING = False

def install_signal_handlers() -> None:
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def log(msg: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

def get_current_wallet_count() -> int:
    if not MASTER_DB.exists():
        return 0
    try:
        data = json.loads(MASTER_DB.read_text(encoding="utf-8"))
        return data.get("total_unique_wallets", len(data.get("all_wallets", [])))
    except Exception:
        return 0

def run_crawler_pipeline(extra_args: list[str]) -> bool:
    log("▶️  Executing Crawler Pipeline Cycle...")
    start_time = time.time()
    initial_count = get_current_wallet_count()

    cmd = [sys.executable, str(BASE_DIR / "run_pipeline.py")] + extra_args
    try:
        res = subprocess.run(cmd, cwd=str(BASE_DIR), check=True)
        elapsed = time.time() - start_time
        new_count = get_current_wallet_count()
        delta = max(0, new_count - initial_count)
        
        log(f"✅ Cycle completed successfully in {elapsed:.1f}s.")
        log(f"📊 Cycle Statistics: Total Wallets: {new_count:,} (Newly added this cycle: +{delta})")
        return True
    except subprocess.CalledProcessError as err:
        log(f"❌ Cycle failed with exit code {err.returncode}.")
        return False
    except OSError as exc:
        log(f"❌ Could not start pipeline: {exc}")
        return False
    except Exception as exc:
        log(f"❌ Error during cycle execution: {exc}")
        return False

def next_sleep_seconds(
    base_seconds: float,
    jitter_max_seconds: float,
    rng: random.Random | None = None,
    floor: float = 60.0,
) -> tuple[float, float]:
    """Return (sleep_seconds, jitter_seconds). Floor keeps production schedules from collapsing to zero."""
    chooser = rng or random
    jitter = chooser.uniform(-float(jitter_max_seconds), float(jitter_max_seconds))
    return max(float(floor), float(base_seconds) + jitter), jitter

def serve(args: argparse.Namespace) -> None:
    pipeline_args = []
    if args.skip_arkm:
        pipeline_args.append("--skip-arkm")
    if args.skip_onchain:
        pipeline_args.append("--skip-onchain")

    if args.interval_seconds:
        base_seconds = int(args.interval_seconds)
        jitter_max_seconds = max(1, int(args.interval_seconds * 0.1))
        floor = 0.0
    else:
        base_seconds = int(args.interval_hours * 3600)
        jitter_max_seconds = int(args.jitter_hours * 3600)
        floor = 60.0

    print(f"""
======================================================================
  Iranian Exchanges Intelligence Suite - Continuous Daemon Service
======================================================================
  Base Interval: {args.interval_hours} hours ({base_seconds}s)
  Jitter Window: ±{args.jitter_hours} hours (±{jitter_max_seconds}s)
  Target DB:     {MASTER_DB}
  Initial Count: {get_current_wallet_count():,} wallets
======================================================================
""")

    cycle_count = 0
    defer_first_run = not args.run_immediately

    while RUNNING:
        if defer_first_run:
            defer_first_run = False
        else:
            cycle_count += 1
            log(f"\n{'='*65}\n🌟 STARTING SCHEDULED CYCLE #{cycle_count}\n{'='*65}")
            run_crawler_pipeline(pipeline_args)
            if not RUNNING:
                break

        sleep_duration, jitter = next_sleep_seconds(base_seconds, jitter_max_seconds, floor=floor)
        next_run_dt = datetime.now() + timedelta(seconds=sleep_duration)

        log(f"💤 Sleeping for {sleep_duration / 3600:.2f} hours ({sleep_duration:.0f}s, jitter: {jitter / 60:+.1f} min)...")
        log(f"⏰ Next scheduled sweep: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S')}")

        # Sleep in small slices to respond promptly to SIGINT/SIGTERM
        sleep_start = time.time()
        while RUNNING and (time.time() - sleep_start) < sleep_duration:
            time.sleep(min(2.0, sleep_duration - (time.time() - sleep_start)))

    log("Service daemon stopped. Goodbye.")

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Continuous Scheduler Daemon for Iranian Exchanges Crawler.")
    parser.add_argument("--interval-hours", type=float, default=float(os.environ.get("INTERVAL_HOURS", 24.0)), help="Base execution interval in hours (default: 24h).")
    parser.add_argument("--jitter-hours", type=float, default=float(os.environ.get("JITTER_HOURS", 2.0)), help="Maximum random variation / jitter in hours (default: ±2h).")
    parser.add_argument("--interval-seconds", type=int, default=None, help="Override interval in seconds (for quick testing).")
    parser.add_argument("--skip-arkm", action="store_true", help="Skip Arkham step in each cycle.")
    parser.add_argument("--skip-onchain", action="store_true", help="Skip On-chain step in each cycle.")
    parser.add_argument("--run-immediately", action=argparse.BooleanOptionalAction, default=True, help="Run the first sweep immediately on start.")
    args, _unknown = parser.parse_known_args(argv)
    if args.interval_hours < 0 or args.jitter_hours < 0 or (args.interval_seconds is not None and args.interval_seconds < 1):
        log("ERROR: interval-hours and jitter-hours must be >= 0, and interval-seconds must be >= 1.")
        sys.exit(2)
    install_signal_handlers()
    serve(args)

if __name__ == "__main__":
    main()

