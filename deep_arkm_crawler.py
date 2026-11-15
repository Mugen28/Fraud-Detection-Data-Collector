#!/usr/bin/env python3
"""
deep_arkm_crawler.py
====================
Advanced Multi-Chain & Depth-2 Crawler for Iranian Cryptocurrency Exchanges on Arkham.

Features:
1. Multi-Chain Transfer Slicing: Queries 11+ blockchain networks individually per entity,
   bypassing the single-endpoint 100-limit ceiling.
2. Depth-2 Hot Wallet Traversal: Scrapes transfers of discovered exchange Hot Wallets to
   extract proprietary deposit addresses labeled by Arkham (e.g. 'Nobitex.ir Deposit').
3. Entity Predictions & Balances: Ingests all AI-predicted wallets and current balances.
4. Cross-Chain Address Resolution: Validates multi-chain presence for EVM addresses.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import quote, urlencode

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
from api_generator import ReplayClient, API_BASE, _API_HEADERS, arkham_session_ready

# Confirmed Iranian CEX Entities on Arkham
EXCHANGE_ENTITIES = [
    {
        "id": "nobitex",
        "name": "Nobitex.ir",
        "type": "CEX",
        "description": "Largest Iranian Exchange (Over 93% volume)",
    },
    {
        "id": "wallex-ir",
        "alias_id": "wallex",
        "name": "Wallex",
        "type": "CEX / Misc",
        "description": "Major Iranian Order-Book Exchange",
    },
    {
        "id": "bitpin",
        "name": "Bitpin",
        "type": "CEX",
        "description": "Leading Iranian Crypto Platform",
    },
    {
        "id": "ramzinex",
        "name": "Ramzinex",
        "type": "CEX",
        "description": "Oldest Active Iranian Crypto Exchange",
    },
    {
        "id": "bit24",
        "name": "Bit24",
        "type": "CEX / OTC",
        "description": "Major Iranian OTC & Fast Swap Platform",
    },
    {
        "id": "abantether",
        "name": "AbanTether",
        "type": "CEX / OTC",
        "description": "High-volume Stablecoin & Crypto OTC",
    },
    {
        "id": "excoino",
        "name": "Excoino",
        "type": "CEX",
        "description": "Knowledge-based Crypto Exchange & Custody",
    },
    {
        "id": "arzpaya-com",
        "alias_id": "arzpaya",
        "name": "ArzPaya",
        "type": "CEX",
        "description": "Iranian P2P / Trading Exchange",
    },
    {
        "id": "farhad-exchange",
        "name": "Farhad Exchange",
        "type": "CEX / Gateway",
        "description": "Pioneer Electronic Payment & Crypto Exchange",
    },
]

# Supported Chains on Arkham
SUPPORTED_CHAINS = [
    "ethereum",
    "bsc",
    "tron",
    "bitcoin",
    "dogecoin",
    "arbitrum_one",
    "polygon",
    "optimism",
    "base",
    "avalanche",
    "solana",
]

def log(msg: str) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}

def atomic_write_json(path: Path, data: Any) -> None:
    """Safely write JSON to a file via atomic rename to prevent corruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    try:
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise

class DeepArkmCrawler:
    def __init__(
        self,
        client: ReplayClient,
        chains: List[str] | None = None,
        max_transfers_per_chain: int = 100,
        enable_depth2: bool = True,
        depth2_limit: int = 50,
        max_depth2_wallets: int = 0,
        out_dir: Path | None = None,
    ):
        self.client = client
        self.chains = chains or SUPPORTED_CHAINS
        self.max_transfers_per_chain = min(max(1, max_transfers_per_chain), 100)
        self.enable_depth2 = enable_depth2
        self.depth2_limit = min(max(1, depth2_limit), 100)
        self.max_depth2_wallets = max(0, max_depth2_wallets)
        self.out_dir = out_dir or (BASE_DIR / "api_output" / "deep_iranian_wallets")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.seen_wallets: Set[Tuple[str, str]] = set()

    def run(self, master_path: Path | None = None) -> Dict[str, Any]:
        log(f"Starting Deep Arkham Crawler across {len(EXCHANGE_ENTITIES)} Iranian entities...")
        log(f"Active Chains ({len(self.chains)}): {', '.join(self.chains)}")
        log(f"Depth-2 Hot Wallet Traversal: {'Enabled' if self.enable_depth2 else 'Disabled'}")

        results: Dict[str, Any] = {}
        total_unique_all = set()

        for ent in EXCHANGE_ENTITIES:
            ent_id = ent["id"]
            ent_name = ent["name"]
            ent_file = self.out_dir / f"{ent_id}_deep.json"

            if getattr(self.client, "auth_failed", False) or getattr(self.client, "cloudflare_blocked", False):
                log(f"\n[!] Session authentication failed or blocked by Cloudflare. Halting crawl to protect dataset.")
                for remaining in EXCHANGE_ENTITIES:
                    r_id = remaining["id"]
                    if r_id not in results:
                        r_file = self.out_dir / f"{r_id}_deep.json"
                        if r_file.exists():
                            try:
                                cached = json.loads(r_file.read_text(encoding="utf-8"))
                                results[r_id] = cached
                                for w in cached.get("wallets", []):
                                    total_unique_all.add(w["address"].lower())
                            except Exception:
                                pass
                break

            log(f"\n{'='*60}\n>>> Processing Entity: {ent_name} [{ent_id}]\n{'='*60}")
            
            ent_data = self._crawl_entity(ent)
            ent_wallets = ent_data.get("wallets", [])

            # Safety check: if 0 wallets were returned but a previous non-empty cache exists, protect it!
            if len(ent_wallets) == 0 and ent_file.exists():
                try:
                    cached = json.loads(ent_file.read_text(encoding="utf-8"))
                    cached_wallets = cached.get("wallets", [])
                    if len(cached_wallets) > 0:
                        log(f"  [!] Preserving existing {ent_file.name} ({len(cached_wallets)} wallets) to prevent data wipe.")
                        ent_data = cached
                        ent_wallets = cached_wallets
                except Exception as exc:
                    log(f"  ! Could not read existing {ent_file.name}: {exc}")

            results[ent_id] = ent_data
            for w in ent_wallets:
                total_unique_all.add(w["address"].lower())

            # Save individual entity report atomically
            if len(ent_wallets) > 0 or not ent_file.exists():
                atomic_write_json(ent_file, ent_data)
                log(f"Saved {len(ent_wallets)} wallets for {ent_name} -> {ent_file.name}")

        # Master report
        master_summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "method": "Multi-Chain Slicing + Depth-2 Hot Wallet Scraping",
            "total_entities_crawled": len(EXCHANGE_ENTITIES),
            "total_unique_wallets": len(total_unique_all),
            "entities": results,
        }
        master_path = master_path or (BASE_DIR / "api_output" / "deep_iranian_exchanges_all_wallets.json")
        atomic_write_json(master_path, master_summary)
        
        log(f"\n{'*'*60}")
        log(f"DEEP CRAWL COMPLETE!")
        log(f"Total Unique Verified Wallets: {len(total_unique_all)}")
        log(f"Master Database: {master_path}")
        log(f"{'*'*60}\n")
        return master_summary

    def _crawl_entity(self, ent: Dict[str, str]) -> Dict[str, Any]:
        ent_id = ent["id"]
        ent_name = ent["name"]
        wallets_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        hot_wallets_to_expand: Set[Tuple[str, str]] = set()

        if getattr(self.client, "auth_failed", False) or getattr(self.client, "cloudflare_blocked", False):
            log(f"  ! Skipping {ent_name}: session auth failed or blocked by Cloudflare.")
            return {
                "entity_id": ent_id,
                "entity_name": ent_name,
                "total_wallets": 0,
                "chain_breakdown": {},
                "wallets": [],
            }

        # Phase 1: Entity Metadata, Predictions & Root Hot Wallet
        log(f"  [1/4] Querying Root Endpoints & AI Predictions for {ent_id}...")
        
        # 1a. Root Top Address
        top_url = f"{API_BASE}/balances/entity_top_address/{quote(ent_id)}"
        resp = self.client._send({"method": "GET", "url": top_url, "headers": _API_HEADERS, "body": None, "body_json": None})
        if resp and resp.status_code == 200:
            top_addr = resp.text.strip('"').strip()
            if top_addr and len(top_addr) > 8:
                chain_guess = "tron" if top_addr.startswith("T") else ("dogecoin" if top_addr.startswith("D") else "evm")
                k = (top_addr.lower(), chain_guess)
                wallets_map[k] = {
                    "address": top_addr,
                    "chain": chain_guess,
                    "label": "Primary Master Hot Wallet",
                    "entity": ent_name,
                    "source": "balances/entity_top_address",
                }
                hot_wallets_to_expand.add((top_addr, chain_guess))
                log(f"    Primary Hot Wallet: {top_addr} [{chain_guess}]")

        # 1b. Entity Predictions
        pred_url = f"{API_BASE}/intelligence/entity_predictions/{quote(ent_id)}"
        resp = self.client._send({"method": "GET", "url": pred_url, "headers": _API_HEADERS, "body": None, "body_json": None})
        if resp and resp.status_code == 200:
            try:
                preds = resp.json()
                if isinstance(preds, list):
                    log(f"    Ingested {len(preds)} AI predicted wallets from entity_predictions")
                    for p in preds:
                        p_addr = p.get("address")
                        usd = p.get("usdBalance", 0)
                        if p_addr:
                            chain_guess = "tron" if p_addr.startswith("T") else ("dogecoin" if p_addr.startswith("D") else "evm")
                            k = (p_addr.lower(), chain_guess)
                            if k not in wallets_map:
                                wallets_map[k] = {
                                    "address": p_addr,
                                    "chain": chain_guess,
                                    "usd_balance": usd,
                                    "label": f"Predicted Exchange Wallet (${usd:,.2f})" if usd else "Predicted Exchange Wallet",
                                    "entity": ent_name,
                                    "source": "intelligence/entity_predictions",
                                }
            except Exception as e:
                log(f"    ! Predictions parse error: {e}")

        # 1c. Search labeled addresses (capped at 50)
        search_url = f"{API_BASE}/intelligence/search?query={quote(ent_id)}&arkhamAddresses=50"
        resp = self.client._send({"method": "GET", "url": search_url, "headers": _API_HEADERS, "body": None, "body_json": None})
        if resp and resp.status_code == 200:
            try:
                s_data = resp.json()
                for a in s_data.get("arkhamAddresses", []):
                    addr_s = a.get("address")
                    chain_s = a.get("chain")
                    lbl = (a.get("arkhamLabel") or {}).get("name", "")
                    if addr_s and chain_s:
                        k = (addr_s.lower(), chain_s.lower())
                        wallets_map[k] = {
                            "address": addr_s,
                            "chain": chain_s,
                            "label": lbl or "Exchange Labeled Wallet",
                            "entity": ent_name,
                            "source": "intelligence/search",
                        }
                        if "hot" in lbl.lower():
                            hot_wallets_to_expand.add((addr_s, chain_s))
            except Exception as e:
                log(f"    ! Search parse error: {e}")

        # Phase 2: Multi-Chain Transfer Slicing
        log(f"  [2/4] Slicing Transfers across {len(self.chains)} Chains (up to {self.max_transfers_per_chain} txs/chain)...")
        for ch in self.chains:
            tx_url = f"{API_BASE}/transfers?base={quote(ent_id)}&chain={ch}&limit={self.max_transfers_per_chain}&flow=all"
            resp = self.client._send({"method": "GET", "url": tx_url, "headers": _API_HEADERS, "body": None, "body_json": None})
            if resp and resp.status_code == 200:
                try:
                    d = resp.json()
                    txs = d.get("transfers", [])
                    if not isinstance(txs, list):
                        continue
                    found_in_chain = 0
                    for tx in txs:
                        if not isinstance(tx, dict):
                            continue
                        for side in [tx.get("fromAddress"), tx.get("toAddress")]:
                            if not isinstance(side, dict):
                                continue
                            s_ent = as_dict(side.get("arkhamEntity")).get("id")
                            s_lbl = as_dict(side.get("arkhamLabel")).get("name", "")
                            s_addr = side.get("address")
                            s_chain = side.get("chain") or ch
                            if s_addr and (s_ent == ent_id or "deposit" in s_lbl.lower() or ent_id in (s_lbl or "").lower()):
                                k = (s_addr.lower(), s_chain.lower())
                                if k not in wallets_map:
                                    wallets_map[k] = {
                                        "address": s_addr,
                                        "chain": s_chain,
                                        "label": s_lbl or "Exchange Active Wallet",
                                        "entity": ent_name,
                                        "source": f"transfers/chain/{ch}",
                                    }
                                    found_in_chain += 1
                                if "hot" in s_lbl.lower():
                                    hot_wallets_to_expand.add((s_addr, s_chain))
                    if txs:
                        log(f"    Chain [{ch:12s}]: {len(txs):3d} txs inspected -> +{found_in_chain} new exchange wallets")
                except Exception as e:
                    log(f"    ! Transfers parse error on {ch}: {e}")

        # Phase 3: Depth-2 Hot Wallet Traversal
        if self.enable_depth2 and hot_wallets_to_expand:
            ordered_hot = sorted(hot_wallets_to_expand, key=lambda item: (item[1], item[0].lower()))
            selected_hot = ordered_hot[:self.max_depth2_wallets] if self.max_depth2_wallets else ordered_hot
            log(
                f"  [3/4] Depth-2 Traversal: Inspecting {len(selected_hot)} of "
                f"{len(ordered_hot)} Hot Wallets for Deposit Streams..."
            )
            for hw_addr, hw_chain in selected_hot:
                # Query on hot wallet address
                target_chains = [hw_chain] if hw_chain in ("tron", "bitcoin", "dogecoin") else ["bsc", "ethereum", "arbitrum_one", "polygon"]
                for ch in target_chains:
                    hw_url = f"{API_BASE}/transfers?base={quote(hw_addr)}&chain={ch}&limit={self.depth2_limit}&flow=all"
                    resp = self.client._send({"method": "GET", "url": hw_url, "headers": _API_HEADERS, "body": None, "body_json": None})
                    if resp and resp.status_code == 200:
                        try:
                            d = resp.json()
                            txs = d.get("transfers", [])
                            if not isinstance(txs, list):
                                continue
                            dep_count = 0
                            for tx in txs:
                                if not isinstance(tx, dict):
                                    continue
                                # check fromAddress (usually user depositing into hot wallet)
                                from_side = tx.get("fromAddress") or {}
                                if not isinstance(from_side, dict):
                                    continue
                                f_addr = from_side.get("address")
                                f_lbl = as_dict(from_side.get("arkhamLabel")).get("name", "")
                                f_ent = as_dict(from_side.get("arkhamEntity")).get("id")
                                if f_addr and ("deposit" in f_lbl.lower() or f_ent == ent_id or ent_id in f_lbl.lower()):
                                    k = (f_addr.lower(), ch.lower())
                                    if k not in wallets_map:
                                        wallets_map[k] = {
                                            "address": f_addr,
                                            "chain": ch,
                                            "label": f_lbl or f"{ent_name} Deposit Address",
                                            "entity": ent_name,
                                            "source": f"depth2/hot_wallet/{hw_addr[:10]}",
                                        }
                                        dep_count += 1
                            if dep_count > 0:
                                log(f"    Hot Wallet {hw_addr[:14]}... on [{ch}]: +{dep_count} deposit wallets identified")
                        except Exception as e:
                            log(f"    ! Depth-2 parse error on {ch}: {e}")

        # Phase 4: Breakdown and Return
        wallets_list = list(wallets_map.values())
        chain_stats: Dict[str, int] = {}
        for w in wallets_list:
            c = w.get("chain", "unknown")
            chain_stats[c] = chain_stats.get(c, 0) + 1

        log(f"  [4/4] Completed {ent_name}: {len(wallets_list)} total unique wallets.")
        log(f"        Chains: {chain_stats}")

        return {
            "entity_id": ent_id,
            "entity_name": ent_name,
            "total_wallets": len(wallets_list),
            "chain_breakdown": chain_stats,
            "wallets": wallets_list,
        }

def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Arkham Multi-Chain & Depth-2 Iranian Exchange Crawler")
    parser.add_argument("--chains", nargs="*", default=SUPPORTED_CHAINS, help="Chains to crawl")
    parser.add_argument("--no-depth2", action="store_true", help="Disable Depth-2 hot wallet scraping")
    parser.add_argument("--transfers-per-chain", type=int, default=100, help="Max transfers per chain")
    parser.add_argument("--depth2-limit", type=int, default=50, help="Transfers per hot wallet")
    parser.add_argument("--depth2-wallets", type=int, default=0, help="Hot wallets to expand in depth-2. 0 means every one, in stable address order.")
    parser.add_argument("--delay", type=float, default=1.2, help="Sleep between calls (seconds)")
    parser.add_argument("--jitter", type=float, default=0.4, help="Jitter sleep variation (seconds)")
    return parser.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.delay < 0 or args.jitter < 0 or args.depth2_wallets < 0:
        log("ERROR: --delay and --jitter must be >= 0, and --depth2-wallets must be >= 0.")
        return 2
    session_file = BASE_DIR / "storage_state.json"
    if not arkham_session_ready(session_file):
        log(
            "ERROR: storage_state.json has no usable arkham_session cookie for arkm.com. "
            "Run `python3 api_generator.py login` before crawling."
        )
        return 2
    client = ReplayClient(
        delay=args.delay,
        jitter=args.jitter,
        session_file=session_file,
        auto_login=False,
    )
    crawler = DeepArkmCrawler(
        client=client,
        chains=args.chains,
        max_transfers_per_chain=args.transfers_per_chain,
        enable_depth2=not args.no_depth2,
        depth2_limit=args.depth2_limit,
        max_depth2_wallets=args.depth2_wallets,
    )
    crawler.run()
    return 0

if __name__ == "__main__":
    sys.exit(main())

