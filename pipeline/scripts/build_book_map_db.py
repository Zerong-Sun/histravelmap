"""Build book-map data from travelogue files using the configured Mimo model.

This script wraps the existing 4-stage pipeline for batch book processing:
ingest -> segment -> extract places/passages -> optional database write.
It also writes a map_index.json grouped by location so the frontend can quickly
show all travelogue records for a clicked city/location.

Usage:
    python pipeline/scripts/build_book_map_db.py books/*.txt --mimo-token "$MIMO_TOKEN"
    python pipeline/scripts/build_book_map_db.py /path/to/books --recursive --write-db

Environment:
    LLM_BASE_URL / LLM_API_KEY are used by pipeline/config/config.yaml.
    For convenience, MIMO_BASE_URL and MIMO_TOKEN or MIMO_API_KEY are also accepted.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from pipeline.core.llm_client import load_config
from pipeline.models import ExtractedStory
from pipeline.runner import run_pipeline
from pipeline.stages.s1_ingest import make_book_slug
from pipeline.stages.s3_extract import _normalize_story_data

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".rtf", ".epub"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract book/location/passages data for the historical map."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Book files or directories containing .pdf/.txt/.md/.rtf/.epub files.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively discover books inside input directories.",
    )
    parser.add_argument(
        "--output-root",
        default=str(ROOT / "pipeline" / "output"),
        help="Directory for per-book story JSON and map_index.json.",
    )
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="Write extracted books, entries, and locations to the configured database.",
    )
    parser.add_argument(
        "--mimo-token",
        default=None,
        help="Mimo API token. If omitted, uses LLM_API_KEY, MIMO_TOKEN, or MIMO_API_KEY.",
    )
    parser.add_argument(
        "--mimo-base-url",
        default=None,
        help="Mimo OpenAI-compatible base URL. If omitted, uses LLM_BASE_URL or MIMO_BASE_URL.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override config.yaml llm.model, e.g. mimo-v2.5.",
    )
    parser.add_argument(
        "--max-books",
        type=int,
        default=None,
        help="Process at most N discovered books. Useful for a first smoke test.",
    )
    return parser.parse_args()


def apply_mimo_env_aliases(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """Accept Mimo-flavored env names while preserving the existing config.yaml."""
    token = args.mimo_token or os.getenv("LLM_API_KEY") or os.getenv("MIMO_TOKEN") or os.getenv("MIMO_API_KEY")
    base_url = args.mimo_base_url or os.getenv("LLM_BASE_URL") or os.getenv("MIMO_BASE_URL")

    if token:
        os.environ["LLM_API_KEY"] = token
        os.environ.setdefault("OCR_API_KEY", token)
    if base_url:
        os.environ["LLM_BASE_URL"] = base_url
        os.environ.setdefault("OCR_BASE_URL", base_url)
    return token, base_url


def load_runtime_config(args: argparse.Namespace) -> dict[str, Any]:
    token, base_url = apply_mimo_env_aliases(args)
    config = load_config()

    if token:
        config.setdefault("llm", {})["api_key"] = token
        config.setdefault("ocr", {})["api_key"] = token
    if base_url:
        config.setdefault("llm", {})["base_url"] = base_url
        config.setdefault("ocr", {})["base_url"] = base_url
    if args.model:
        config.setdefault("llm", {})["model"] = args.model
        config.setdefault("ocr", {})["model"] = args.model

    missing = [
        key
        for key in ("base_url", "api_key", "model")
        if not config.get("llm", {}).get(key) or str(config["llm"][key]).startswith("${")
    ]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            f"Missing LLM config fields: {names}. Set LLM_BASE_URL and LLM_API_KEY "
            "or pass --mimo-base-url and --mimo-token."
        )

    return config


def discover_books(inputs: list[str], recursive: bool) -> list[Path]:
    books: list[Path] = []
    for raw in inputs:
        path = Path(raw).expanduser().resolve()
        if path.is_file():
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                books.append(path)
            continue

        if not path.is_dir():
            raise FileNotFoundError(f"Input does not exist: {path}")

        iterator = path.rglob("*") if recursive else path.glob("*")
        books.extend(
            child
            for child in iterator
            if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS
        )

    deduped = sorted({book: None for book in books}.keys())
    if not deduped:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise RuntimeError(f"No supported book files found. Supported extensions: {allowed}")
    return deduped


def _read_story(path: Path) -> ExtractedStory | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _normalize_story_data(data)
        return ExtractedStory(**data)
    except Exception as exc:
        print(f"  ! Skipping malformed story JSON {path}: {exc}")
        return None


def _location_key(location: dict[str, Any]) -> str:
    name = (location.get("modern_name") or location.get("name") or "").strip()
    return name.lower()


def build_map_index(output_root: Path, book_files: list[Path]) -> dict[str, Any]:
    """Build a location-centric index from extracted per-story JSON files."""
    index: dict[str, Any] = {
        "books_processed": [str(path) for path in book_files],
        "locations": [],
    }
    locations_by_key: dict[str, dict[str, Any]] = {}

    for book_file in book_files:
        book_slug = make_book_slug(str(book_file))
        story_dir = output_root / book_slug
        if not story_dir.exists():
            continue

        for story_path in sorted(story_dir.glob("*.json")):
            if story_path.name.startswith("_"):
                continue

            story = _read_story(story_path)
            if story is None or not story.is_content or not story.extracted:
                continue
            if not story.entities:
                continue

            book_meta = story.book_metadata or {}
            story_meta = story.story_metadata or {}
            for order, loc in enumerate(story.entities.get("locations", [])):
                if not loc.get("name"):
                    continue

                key = _location_key(loc)
                if not key:
                    continue

                record = locations_by_key.setdefault(
                    key,
                    {
                        "name": loc.get("name"),
                        "modern_name": loc.get("modern_name"),
                        "ancient_names": [],
                        "latitude": loc.get("lat"),
                        "longitude": loc.get("lng"),
                        "location_type": loc.get("location_type"),
                        "one_line_summary": loc.get("one_line_summary"),
                        "mentions": [],
                    },
                )

                ancient_name = loc.get("ancient_name")
                if ancient_name and ancient_name not in record["ancient_names"]:
                    record["ancient_names"].append(ancient_name)
                if not record.get("latitude") and loc.get("lat"):
                    record["latitude"] = loc.get("lat")
                    record["longitude"] = loc.get("lng")

                record["mentions"].append(
                    {
                        "book_slug": story.book_slug,
                        "book_title": book_meta.get("title") or story.book_slug,
                        "author": book_meta.get("author"),
                        "dynasty": book_meta.get("dynasty"),
                        "source_file": str(book_file),
                        "story_id": story.id,
                        "story_title": story_meta.get("title") or story.title,
                        "chapter_reference": story_meta.get("chapter_reference"),
                        "visit_date_approximate": story_meta.get("visit_date_approximate"),
                        "location_order": order,
                        "excerpt_original": story.excerpt_original,
                        "excerpt_translation": story.excerpt_translation,
                        "summary_chinese": story.summary_chinese,
                        "summary_english": story.summary_english,
                        "story_json": str(story_path),
                    }
                )

    index["locations"] = sorted(
        locations_by_key.values(),
        key=lambda item: (-len(item["mentions"]), item["name"] or ""),
    )
    return index


async def main() -> None:
    args = parse_args()
    config = load_runtime_config(args)
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    books = discover_books(args.inputs, args.recursive)
    if args.max_books is not None:
        books = books[: args.max_books]

    print(f"Found {len(books)} book(s). Output root: {output_root}")
    print(f"DB write: {'enabled' if args.write_db else 'disabled (JSON/index only)'}")

    for idx, book in enumerate(books, start=1):
        book_slug = make_book_slug(str(book))
        output_dir = output_root / book_slug
        print(f"\n[{idx}/{len(books)}] Processing {book.name}")
        try:
            await run_pipeline(
                str(book),
                config=config,
                output_dir=str(output_dir),
                skip_output=not args.write_db,
            )
        except Exception as exc:
            print(f"  ! Failed {book}: {exc}")

    map_index = build_map_index(output_root, books)
    index_path = output_root / "map_index.json"
    index_path.write_text(
        json.dumps(map_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    mention_count = sum(len(loc["mentions"]) for loc in map_index["locations"])
    print(f"\nWrote {index_path}")
    print(f"Indexed {len(map_index['locations'])} location(s), {mention_count} mention(s).")


if __name__ == "__main__":
    asyncio.run(main())
