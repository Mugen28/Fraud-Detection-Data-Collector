#!/usr/bin/env python3
"""
onchain_wallet_sweeper.py
=========================
Hybrid On-Chain Sweeper & Continuous Deposit Wallet Harvester.

Takes the root exchange hot wallets discovered from Arkham and directly monitors / sweeps
public blockchain explorers (TronGrid, Blockstream Bitcoin, and EVM JSON-RPC) to extract
real-time and historical user deposit addresses sweeping funds into the exchanges.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

BASE_DIR = Path(__file__).resolve().parent

# Curated List of Validated Root Hot Wallets Discovered from Arkham
ROOT_HOT_WALLETS = [
    # TRON Hot Wallets (Majority of Iranian retail volume: USDT-TRC20)
    {
        "exchange": "nobitex",
        "name": "Nobitex.ir",
        "chain": "tron",
        "address": "TPMF2n3hJLcCwoHq6bwLeVXBbNZgj73AEd",
        "role": "Primary TRC-20 Hot Wallet",
    },
    {
        "exchange": "bitpin",
        "name": "Bitpin",
        "chain": "tron",
        "address": "TPAGNcyoCkdrFA6YFHUR1GrcySMHUr88jq",
        "role": "Primary TRC-20 Hot Wallet",
    },
    {
        "exchange": "bit24",
        "name": "Bit24",
        "chain": "tron",
        "address": "TGfVBoUwvVR7dMsNFWYThUjyPKwMV28UpK",
        "role": "Primary TRC-20 / Staking Pool Wallet",
    },
    {
        "exchange": "nobitex",
        "name": "Nobitex.ir",
        "chain": "tron",
        "address": "TAm937jKKHTgJ8qsBuW8CwSRL9shLRQ7yn",
        "role": "Secondary TRC-20 Hot Wallet",
    },
    {
        "exchange": "nobitex",
        "name": "Nobitex.ir",
        "chain": "tron",
        "address": "TUHpMF2TkFaJrowUYMzpuY8rzL4kNXXkuE",
        "role": "TRC-20 Hot Wallet #3",
    },

    # Bitcoin Hot Wallets
    {
        "exchange": "nobitex",
        "name": "Nobitex.ir",
        "chain": "bitcoin",
        "address": "bc1qgr3d2uwesguppck3mmdzk63p2n42788a87pczr",
        "role": "Primary SegWit Bitcoin Hot Wallet",
    },

    # EVM Hot Wallets (BSC, Ethereum, Polygon, Arbitrum)
    {
        "exchange": "nobitex",
        "name": "Nobitex.ir",
        "chain": "evm",
        "address": "0xad000f8f23b9ec2957e44cb5d6ea03925441d42c",
        "role": "Central EVM / BSC Hot Wallet",
    },
    {
        "exchange": "wallex",
        "name": "Wallex",
        "chain": "evm",
        "address": "0xd09e06cc2f2fb51aab6ff6663bb7a5682bf372ac",
        "role": "Primary EVM Hot Wallet",
    },
    {
        "exchange": "ramzinex",
        "name": "Ramzinex",
        "chain": "evm",
        "address": "0x8e8afe1fe20f444c6bf57c4fcd100207d6762227",
        "role": "Primary EVM Hot Wallet",
    },
    {
        "exchange": "bitpin",
        "name": "Bitpin",
        "chain": "evm",
        "address": "0x0595db3a47bf1a0d34d1fc23cc4e69f0d01672f9",
        "role": "Primary EVM Hot Wallet",
    },
    {
        "exchange": "abantether",
        "name": "AbanTether",
        "chain": "evm",
        "address": "0x549d4fc107185de6997f7bcba5d28f0dfb7eaf2c",
        "role": "Primary EVM Hot Wallet",
    },
    {
        "exchange": "excoino",
        "name": "Excoino",
        "chain": "evm",
        "address": "0x98439001c0c9d6002f3a0b3fc245efb52c36f175",
        "role": "Primary EVM Hot Wallet",
    },
    {
        "exchange": "arzpaya",
        "name": "ArzPaya",
        "chain": "evm",
        "address": "0x82a403c14483931b2ff6e4440c8373ccfee698b8",
        "role": "Primary EVM Hot Wallet",
    },
    {
        "exchange": "farhad-exchange",
        "name": "Farhad Exchange",
        "chain": "evm",
        "address": "0xef5e27fc28e086fae55854ceb194d0d4cae632f4",
        "role": "Primary EVM Hot Wallet",
    },
]

# ERC-20 Transfer(address,address,uint256). topic2 is the recipient.
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
EVM_RPCS = {
    "ethereum": "https://ethereum.publicnode.com",
    "bsc": "https://bsc-dataseed.binance.org",
    "polygon": "https://polygon-bor-rpc.publicnode.com",
    "arbitrum_one": "https://arbitrum-one-rpc.publicnode.com",
    "optimism": "https://optimism-rpc.publicnode.com",
    "base": "https://base-rpc.publicnode.com",
    "avalanche": "https://avalanche-c-chain-rpc.publicnode.com",
}

def log(msg: str) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def http_get_json(url: str, timeout: float = 12.0) -> Any | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log(f"  ! request failed ({type(exc).__name__})")
        return None

def http_post_json(url: str, payload: dict, timeout: float = 12.0) -> Any | None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log(f"  ! request failed ({type(exc).__name__})")
        return None

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

def address_problem(chain: str, address: str) -> str | None:
    """Return a reason when a root address cannot be swept, otherwise None."""
    chain = (chain or "").lower()
    address = (address or "").strip()
    if chain == "tron":
        if address.startswith("T") and len(address) == 34:
            return None
        return "invalid tron address"
    if chain == "bitcoin":
        if address.startswith("bc1") and 42 <= len(address) <= 62:
            return None
        if address[:1] in "13" and len(address) >= 33 and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]+", address):
            return None
        return "invalid bitcoin address"
    if chain == "evm" or chain in EVM_RPCS:
        if re.fullmatch(r"0x[a-fA-F0-9]{40}", address):
            return None
        return "invalid evm address"
    return None

def topic_to_address(topic: str) -> str | None:
    raw = topic[2:] if topic.startswith("0x") else topic
    if len(raw) < 40 or not re.fullmatch(r"[0-9a-fA-F]+", raw):
        return None
    return "0x" + raw[-40:].lower()

class OnChainSweeper:
    def __init__(
        self,
        max_pages: int = 5,
        limit_per_page: int = 50,
        out_dir: Path | None = None,
        evm_block_span: int = 2000,
    ):
        self.max_pages = max_pages
        self.limit_per_page = limit_per_page
        self.evm_block_span = max(1, evm_block_span)
        self.out_dir = out_dir or (BASE_DIR / "api_output" / "onchain_swept_wallets")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.discovered_wallets: Dict[str, Dict[str, Any]] = {}

    def sweep_tron(self, target: Dict[str, str]) -> int:
        addr = target["address"]
        exchange = target["name"]
        log(f"Sweeping TRON incoming deposits for {exchange} ({addr[:12]}...)...")
        
        fingerprint = None
        new_wallets = 0
        total_txs = 0

        for page in range(1, self.max_pages + 1):
            url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions/trc20?limit={self.limit_per_page}&only_to=true"
            if fingerprint:
                url += f"&fingerprint={fingerprint}"
            
            data = http_get_json(url)
            if not isinstance(data, dict) or "data" not in data:
                break

            txs = data.get("data")
            if not isinstance(txs, list):
                break
            total_txs += len(txs)

            for tx in txs:
                if not isinstance(tx, dict):
                    continue
                from_addr = tx.get("from")
                token_sym = (tx.get("token_info") or {}).get("symbol", "TRC20")
                if from_addr and from_addr != addr:
                    key = f"tron:{from_addr}"
                    if key not in self.discovered_wallets:
                        self.discovered_wallets[key] = {
                            "address": from_addr,
                            "chain": "tron",
                            "label": f"{exchange} User Deposit / Sweeper Wallet",
                            "exchange": exchange,
                            "token_transferred": token_sym,
                            "target_hot_wallet": addr,
                            "source": "onchain/trongrid",
                            "first_seen": datetime.now(timezone.utc).isoformat(),
                        }
                        new_wallets += 1

            meta = data.get("meta") or {}
            if not isinstance(meta, dict):
                break
            fingerprint = meta.get("fingerprint")
            if not fingerprint:
                break
            time.sleep(0.3)

        log(f"  -> Inspected {total_txs} TRON incoming txs -> Discovered {new_wallets} new unique deposit wallets.")
        return new_wallets

    def sweep_bitcoin(self, target: Dict[str, str]) -> int:
        addr = target["address"]
        exchange = target["name"]
        log(f"Sweeping Bitcoin transactions for {exchange} ({addr[:14]}...)...")
        
        url = f"https://blockstream.info/api/address/{addr}/txs"
        data = http_get_json(url)
        if not data or not isinstance(data, list):
            log(f"  -> No data or rate limited on Bitcoin explorer.")
            return 0

        txs = [tx for tx in data if isinstance(tx, dict)]
        new_wallets = 0
        for tx in txs:
            # Vin addresses are depositors
            for vin in tx.get("vin") or []:
                if not isinstance(vin, dict):
                    continue
                prevout = vin.get("prevout") or {}
                if not isinstance(prevout, dict):
                    continue
                vin_addr = prevout.get("scriptpubkey_address")
                if vin_addr and vin_addr != addr:
                    key = f"bitcoin:{vin_addr}"
                    if key not in self.discovered_wallets:
                        self.discovered_wallets[key] = {
                            "address": vin_addr,
                            "chain": "bitcoin",
                            "label": f"{exchange} User BTC Depositor / Associated Wallet",
                            "exchange": exchange,
                            "target_hot_wallet": addr,
                            "source": "onchain/blockstream",
                            "first_seen": datetime.now(timezone.utc).isoformat(),
                        }
                        new_wallets += 1

        log(f"  -> Inspected {len(txs)} Bitcoin txs -> Discovered {new_wallets} new unique deposit wallets.")
        return new_wallets

    def _rpc(self, url: str, method: str, params: list) -> Any | None:
        payload = http_post_json(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if not isinstance(payload, dict):
            return None
        if payload.get("error"):
            log(f"  ! RPC {method} error")
            return None
        return payload.get("result")

    def sweep_evm(self, target: Dict[str, str]) -> int:
        addr = target["address"]
        exchange = target["name"]
        chains = list(EVM_RPCS) if target["chain"] == "evm" else [target["chain"]]
        padded = "0x" + addr[2:].lower().zfill(64)
        new_wallets = 0
        log(f"Sweeping EVM ERC-20 deposits for {exchange} ({addr[:10]}...) on {', '.join(chains)}...")

        for chain in chains:
            rpc_url = EVM_RPCS.get(chain)
            if not rpc_url:
                log(f"  -> No RPC configured for {chain}.")
                continue
            latest_hex = self._rpc(rpc_url, "eth_blockNumber", [])
            if not isinstance(latest_hex, str):
                log(f"  -> {chain}: block height unavailable.")
                continue
            try:
                latest = int(latest_hex, 16)
            except ValueError:
                log(f"  -> {chain}: unreadable block height.")
                continue

            # Fall back to smaller span if public RPC limits maximum block range
            span_candidates = [self.evm_block_span]
            if self.evm_block_span > 1000:
                span_candidates.append(1000)
            if self.evm_block_span > 500:
                span_candidates.append(500)

            logs = None
            for span in span_candidates:
                start = max(0, latest - span)
                logs = self._rpc(rpc_url, "eth_getLogs", [{
                    "fromBlock": hex(start),
                    "toBlock": hex(latest),
                    "topics": [TRANSFER_TOPIC, None, padded],
                }])
                if isinstance(logs, list):
                    break

            if not isinstance(logs, list):
                log(f"  -> {chain}: no logs returned.")
                continue
            found_here = 0
            for entry in logs:
                if not isinstance(entry, dict):
                    continue
                topics = entry.get("topics") or []
                if not isinstance(topics, list) or len(topics) < 3:
                    continue
                sender = topic_to_address(str(topics[1]))
                recipient = topic_to_address(str(topics[2]))
                if not sender or recipient != addr.lower() or sender == addr.lower():
                    continue
                key = f"{chain}:{sender}"
                if key in self.discovered_wallets:
                    continue
                self.discovered_wallets[key] = {
                    "address": sender,
                    "chain": chain,
                    "label": f"{exchange} User ERC-20 Deposit",
                    "exchange": exchange,
                    "token_transferred": "ERC-20",
                    "target_hot_wallet": addr,
                    "source": f"onchain/evm-rpc/{chain}",
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                }
                found_here += 1
                new_wallets += 1
            log(f"  -> {chain}: inspected {len(logs)} logs -> +{found_here} deposit wallets.")
        return new_wallets

    def run(self, summary_path: Path | None = None, targets: List[Dict[str, str]] | None = None) -> Dict[str, Any]:
        out_file = summary_path or (BASE_DIR / "api_output" / "onchain_swept_wallets.json")
        if out_file.exists():
            try:
                existing_data = json.loads(out_file.read_text(encoding="utf-8"))
                for ew in existing_data.get("wallets", []):
                    if isinstance(ew, dict) and ew.get("address") and ew.get("chain"):
                        key = f"{ew['chain'].lower()}:{ew['address'].lower()}"
                        if key not in self.discovered_wallets:
                            self.discovered_wallets[key] = ew
                log(f"Loaded {len(self.discovered_wallets)} historical swept wallets from {out_file.name}")
            except Exception as exc:
                log(f"Warning: could not load existing {out_file.name}: {exc}")

        selected = targets if targets is not None else ROOT_HOT_WALLETS
        log(f"Starting On-Chain Sweeper on {len(selected)} validated Iranian Hot Wallets...")
        skipped: List[Dict[str, str]] = []

        for target in selected:
            ch = target["chain"]
            problem = address_problem(ch, target.get("address") or "")
            label = target.get("name") or target.get("exchange")
            if problem:
                log(f"Skipping {label} on {ch}: {problem}.")
                skipped.append({
                    "exchange": target.get("exchange") or "",
                    "chain": ch,
                    "reason": problem,
                })
                continue
            if ch == "tron":
                self.sweep_tron(target)
            elif ch == "bitcoin":
                self.sweep_bitcoin(target)
            elif ch == "evm" or ch in EVM_RPCS:
                self.sweep_evm(target)
            else:
                log(f"Skipping {label} on {ch}: no sweeper for this chain.")
                skipped.append({
                    "exchange": target.get("exchange") or "",
                    "chain": ch,
                    "reason": "no on-chain sweeper for this chain",
                })
            time.sleep(0.3)

        wallets_list = list(self.discovered_wallets.values())
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "method": "Hybrid On-Chain Gateway Sweeper (TronGrid + Blockstream + EVM JSON-RPC)",
            "total_swept_wallets": len(wallets_list),
            "skipped_targets": skipped,
            "wallets": wallets_list,
        }

        out_file = summary_path or (BASE_DIR / "api_output" / "onchain_swept_wallets.json")
        atomic_write_json(out_file, summary)
        
        log(f"\n{'*'*60}")
        log(f"ON-CHAIN SWEEP COMPLETE!")
        log(f"Discovered {len(wallets_list)} Active On-Chain User Deposit Wallets!")
        log(f"Saved to: {out_file}")
        log(f"{'*'*60}\n")
        return summary

def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hybrid On-Chain Wallet Sweeper")
    parser.add_argument("--pages", type=positive_int, default=5, help="Number of pages to sweep per hot wallet")
    parser.add_argument("--limit", type=positive_int, default=50, help="Transfers per page")
    args = parser.parse_args(argv)

    sweeper = OnChainSweeper(max_pages=args.pages, limit_per_page=args.limit)
    sweeper.run()
    return 0

if __name__ == "__main__":
    sys.exit(main())

