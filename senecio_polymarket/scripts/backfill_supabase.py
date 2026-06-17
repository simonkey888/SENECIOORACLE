#!/usr/bin/env python3
"""
SENECIO Oracle — Backfill Supabase from predictions.jsonl (ACT XIX)

One-shot script: reads all predictions from the seed JSONL file and inserts
them into Supabase. Safe to re-run (uses timestamp as dedup key — Supabase
will have duplicates if you run twice; for clean state, truncate first).

Usage:
    python3 scripts/backfill_supabase.py
    python3 scripts/backfill_supabase.py --dry-run
    python3 scripts/backfill_supabase.py --path /custom/path.jsonl
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Make backend importable
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from backend import supabase_client


async def backfill(jsonl_path: Path, dry_run: bool = False) -> None:
    if not jsonl_path.exists():
        print(f"ERROR: file not found: {jsonl_path}")
        return

    print(f"Reading: {jsonl_path}")
    rows = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                print(f"  skip bad line: {e}")

    print(f"Total predictions in file: {len(rows)}")

    if dry_run:
        print("\n--- DRY RUN ---")
        for r in rows[:5]:
            print(f"  {r.get('timestamp')} {r.get('symbol')} {r.get('prediction')} conf={r.get('confidence')} ex={r.get('exchange_used')}")
        print(f"  ... ({len(rows)} total, would insert all)")
        return

    print(f"\nInserting {len(rows)} predictions into Supabase...")
    success = 0
    failed = 0
    for i, p in enumerate(rows, 1):
        result = await supabase_client.insert_prediction(p)
        if result:
            success += 1
            print(f"  [{i}/{len(rows)}] OK id={result.get('id')} ts={p.get('timestamp')} symbol={p.get('symbol')}")
        else:
            failed += 1
            print(f"  [{i}/{len(rows)}] FAIL ts={p.get('timestamp')}")
        # Be nice to Supabase free tier rate limits
        await asyncio.sleep(0.1)

    print(f"\nDone: {success} inserted, {failed} failed")
    await supabase_client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=str, default=str(ROOT / "oracle" / "senecio_output" / "predictions.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(backfill(Path(args.path), dry_run=args.dry_run))


if __name__ == "__main__":
    main()
