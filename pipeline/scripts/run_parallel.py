"""Parallel runner for build_book_map_db.py — processes multiple books concurrently."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from pipeline.core.llm_client import load_config
from pipeline.runner import run_pipeline
from pipeline.stages.s1_ingest import make_book_slug
from pipeline.scripts.build_book_map_db import (
    build_map_index,
    discover_books,
    load_runtime_config,
)

CONCURRENCY = 3  # max parallel book pipelines


async def process_book(
    idx: int,
    total: int,
    book: Path,
    config: dict,
    output_root: Path,
    sem: asyncio.Semaphore,
) -> bool:
    book_slug = make_book_slug(str(book))
    output_dir = output_root / book_slug
    async with sem:
        print(f"\n[{idx}/{total}] START {book.name}")
        t0 = time.time()
        try:
            await run_pipeline(
                str(book),
                config=config,
                output_dir=str(output_dir),
                skip_output=True,
            )
            elapsed = time.time() - t0
            print(f"[{idx}/{total}] DONE  {book.name}  ({elapsed:.1f}s)")
            return True
        except Exception as exc:
            elapsed = time.time() - t0
            print(f"[{idx}/{total}] FAIL  {book.name}  ({elapsed:.1f}s): {exc}")
            return False


async def main() -> None:
    # Hardcode args for this run
    class Args:
        inputs = [str(ROOT / "travel_books")]
        recursive = False
        output_root = str(ROOT / "pipeline" / "output")
        write_db = False
        mimo_token = "tp-c0m4kgymh0j7hampgxe9c5py0pou5ipjmm63pzqn2qkspmpk"
        mimo_base_url = "https://token-plan-cn.xiaomimimo.com/v1"
        model = "mimo-v2.5"
        max_books = None

    args = Args()
    config = load_runtime_config(args)
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    books = discover_books(args.inputs, args.recursive)
    if args.max_books:
        books = books[: args.max_books]

    total = len(books)
    print(f"Found {total} book(s). Concurrency: {CONCURRENCY}")
    print(f"Output root: {output_root}")
    print(f"Model: {config['llm']['model']} @ {config['llm']['base_url']}")

    sem = asyncio.Semaphore(CONCURRENCY)
    t_start = time.time()

    tasks = [
        process_book(i + 1, total, book, config, output_root, sem)
        for i, book in enumerate(books)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    elapsed_total = time.time() - t_start
    ok = sum(1 for r in results if r is True)
    fail = total - ok
    print(f"\n{'='*60}")
    print(f"All done: {ok} succeeded, {fail} failed, total {elapsed_total:.1f}s")

    # Build map index
    map_index = build_map_index(output_root, books)
    index_path = output_root / "map_index.json"
    index_path.write_text(
        json.dumps(map_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    mention_count = sum(len(loc["mentions"]) for loc in map_index["locations"])
    print(f"Wrote {index_path}")
    print(f"Indexed {len(map_index['locations'])} location(s), {mention_count} mention(s).")


if __name__ == "__main__":
    asyncio.run(main())
