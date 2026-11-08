#!/usr/bin/env python3
"""
extract_all_iranian_wallets.py
==============================
Exhaustive crawler script to discover and extract all known wallet addresses
for Iranian cryptocurrency exchanges from Arkham Intelligence using live session credentials.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
from api_generator import ReplayClient, API_BASE, _API_HEADERS

TARGETS = [
    # Official CEX Entities in Arkham
    "nobitex",
    "wallex-ir",
    "wallex",
    "ramzinex",
    "bitpin",
    "abantether",
    "bit24",
    "excoino",
    "arzpaya-com",
    "arzpaya",
    # Additional Iranian exchanges & platforms
    "tabdeal",
    "ompfinex",
    "exir",
    "tetherland",
    "tetherfa",
    "kifpool",
    "sarmayex",
    "pooleno",
    "rabex",
    "ok-exchange",
    "bitbarg",
    "pingi",
    "bitimen",
    "exnovin",
    "ubitex",
    "bitestan",
    "arzplus",
    "arzypto",
    "hamtapa",
    "changeto",
    "farhad exchange",
    "iranicard",
    "pay98",
    "mihanpayment",
    "titann",
    "bitbaan",
    "bitland",
    "arzjoo",
    "ramzali",
    "nikpardakht",
    "safeex",
    "bityad",
    "dideban",
]

def main():
    session_file = BASE_DIR / "storage_state.json"
    client = ReplayClient(
        delay=0.4,
        jitter=0.2,
        session_file=session_file,
        auto_login=False,
    )

    out_dir = BASE_DIR / "api_output" / "iranian_wallets"
    out_dir.mkdir(parents=True, exist_ok=True)

    master_results = {}
    total_wallets_collected = set()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting extraction for {len(TARGETS)} targets...")

    for idx, target in enumerate(TARGETS, 1):
        t_clean = target.strip().lower()
        print(f"\n--- [{idx}/{len(TARGETS)}] Processing target: {t_clean} ---")
        
        target_data = {
            "target": t_clean,
            "entity_id": None,
            "entity_name": None,
            "summary": {},
            "top_address": None,
            "wallets": {},  # key: (address, chain) -> info
        }

        # 1. Search endpoint (caps at 50)
        search_url = f"{API_BASE}/intelligence/search?query={quote(t_clean)}&arkhamAddresses=50&arkhamEntities=5"
        resp = client._send({"method": "GET", "url": search_url, "headers": _API_HEADERS, "body": None, "body_json": None})
        if resp and resp.status_code == 200:
            try:
                s_json = resp.json()
                ents = s_json.get("arkhamEntities", [])
                if ents:
                    # check match
                    for e in ents:
                        if e.get("id") == t_clean or t_clean in (e.get("name") or "").lower():
                            target_data["entity_id"] = e.get("id")
                            target_data["entity_name"] = e.get("name")
                            break
                    if not target_data["entity_id"]:
                        target_data["entity_id"] = ents[0].get("id")
                        target_data["entity_name"] = ents[0].get("name")

                # Parse search arkhamAddresses
                addrs = s_json.get("arkhamAddresses", [])
                for a in addrs:
                    addr_str = a.get("address")
                    chain_str = a.get("chain")
                    ent_obj = a.get("arkhamEntity") or {}
                    lbl_obj = a.get("arkhamLabel") or {}
                    ent_id = ent_obj.get("id")
                    ent_name = ent_obj.get("name")
                    lbl_name = lbl_obj.get("name")
                    
                    # check relevance
                    is_rel = False
                    if target_data["entity_id"] and ent_id == target_data["entity_id"]:
                        is_rel = True
                    elif t_clean in (ent_name or "").lower() or t_clean in (lbl_name or "").lower():
                        is_rel = True
                    
                    if is_rel and addr_str and chain_str:
                        key = (addr_str.lower(), chain_str.lower())
                        target_data["wallets"][key] = {
                            "address": addr_str,
                            "chain": chain_str,
                            "label": lbl_name or "Hot Wallet / Deposit",
                            "entity": ent_name or target_data["entity_name"],
                            "source": "intelligence/search",
                        }
            except Exception as e:
                print(f"  [!] Search parse error: {e}")

        # If entity resolved, query entity-specific endpoints
        ent_id = target_data["entity_id"] or t_clean
        
        # 2. Entity Summary
        sum_url = f"{API_BASE}/intelligence/entity/{quote(ent_id)}/summary"
        resp = client._send({"method": "GET", "url": sum_url, "headers": _API_HEADERS, "body": None, "body_json": None})
        if resp and resp.status_code == 200:
            try:
                target_data["summary"] = resp.json()
                if not target_data["entity_id"]:
                    target_data["entity_id"] = ent_id
            except:
                pass

        # 3. Top Address
        top_url = f"{API_BASE}/balances/entity_top_address/{quote(ent_id)}"
        resp = client._send({"method": "GET", "url": top_url, "headers": _API_HEADERS, "body": None, "body_json": None})
        if resp and resp.status_code == 200:
            try:
                top_addr = resp.text.strip('"').strip()
                if top_addr and len(top_addr) > 10:
                    target_data["top_address"] = top_addr
                    # default chain ethereum/evm if 0x, tron if T...
                    chain_guess = "tron" if top_addr.startswith("T") else ("dogecoin" if top_addr.startswith("D") else "evm")
                    key = (top_addr.lower(), chain_guess)
                    target_data["wallets"][key] = {
                        "address": top_addr,
                        "chain": chain_guess,
                        "label": "Primary Hot Wallet (Top Address)",
                        "entity": target_data["entity_name"] or ent_id,
                        "source": "balances/entity_top_address",
                    }
            except:
                pass

        # 4. Entity Predictions (returns direct list of wallets)
        pred_url = f"{API_BASE}/intelligence/entity_predictions/{quote(ent_id)}"
        resp = client._send({"method": "GET", "url": pred_url, "headers": _API_HEADERS, "body": None, "body_json": None})
        if resp and resp.status_code == 200:
            try:
                preds = resp.json()
                if isinstance(preds, list):
                    for p in preds:
                        p_addr = p.get("address")
                        usd = p.get("usdBalance", 0)
                        if p_addr:
                            chain_guess = "tron" if p_addr.startswith("T") else ("dogecoin" if p_addr.startswith("D") else "evm")
                            key = (p_addr.lower(), chain_guess)
                            target_data["wallets"][key] = {
                                "address": p_addr,
                                "chain": chain_guess,
                                "usd_balance": usd,
                                "label": f"Predicted Exchange Wallet (${usd:,.2f})" if usd else "Predicted Exchange Wallet",
                                "entity": target_data["entity_name"] or ent_id,
                                "source": "intelligence/entity_predictions",
                            }
            except Exception as e:
                print(f"  [!] Predictions parse error: {e}")

        # 5. Transfers (extract exchange addresses from recent 100 transfers)
        tx_url = f"{API_BASE}/transfers?base={quote(ent_id)}&limit=100&flow=all"
        resp = client._send({"method": "GET", "url": tx_url, "headers": _API_HEADERS, "body": None, "body_json": None})
        if resp and resp.status_code == 200:
            try:
                tx_json = resp.json()
                txs = tx_json.get("transfers", [])
                for tx in txs:
                    for endpoint_side in [tx.get("fromAddress"), tx.get("toAddress")]:
                        if not endpoint_side:
                            continue
                        side_ent = endpoint_side.get("arkhamEntity") or {}
                        side_lbl = endpoint_side.get("arkhamLabel") or {}
                        side_addr = endpoint_side.get("address")
                        side_chain = endpoint_side.get("chain")
                        if side_ent.get("id") == ent_id and side_addr and side_chain:
                            key = (side_addr.lower(), side_chain.lower())
                            if key not in target_data["wallets"]:
                                target_data["wallets"][key] = {
                                    "address": side_addr,
                                    "chain": side_chain,
                                    "label": side_lbl.get("name") or "Exchange Active Wallet",
                                    "entity": side_ent.get("name") or target_data["entity_name"],
                                    "source": "transfers",
                                }
            except Exception as e:
                print(f"  [!] Transfers parse error: {e}")

        # Summary for target
        wallet_list = list(target_data["wallets"].values())
        print(f"  -> Found {len(wallet_list)} unique wallets for {t_clean} (Entity: {target_data['entity_id'] or 'None'})")
        
        # Add to total
        for w in wallet_list:
            total_wallets_collected.add(w["address"].lower())

        # Format output
        target_data["wallets"] = wallet_list
        master_results[t_clean] = target_data

        # Save individual json
        (out_dir / f"{t_clean}.json").write_text(json.dumps(target_data, indent=2, ensure_ascii=False))

    # Save aggregated master file
    all_wallets_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_targets_scanned": len(TARGETS),
        "total_unique_wallets": len(total_wallets_collected),
        "targets": master_results,
    }
    master_file = BASE_DIR / "api_output" / "iranian_exchanges_all_wallets.json"
    master_file.write_text(json.dumps(all_wallets_summary, indent=2, ensure_ascii=False))
    print(f"\n=======================================================")
    print(f"EXTRACTION COMPLETE!")
    print(f"Total Unique Wallets Extracted: {len(total_wallets_collected)}")
    print(f"Saved to: {master_file}")
    print(f"=======================================================")

if __name__ == "__main__":
    main()

