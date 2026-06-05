from __future__ import annotations

import json
from pathlib import Path

from pipeline.core.llm_client import LLMClient
from pipeline.models import ExtractedStory, SegmentResultV2

PROMPTS_DIR = Path(__file__).parent.parent / "config" / "prompts"

DEFAULT_EXTRACTION_TOOLS = []


def get_extraction_tools(config: dict | None = None) -> list[dict]:
    """Load extraction tools from config, falling back to defaults."""
    if config and config.get("extratools"):
        return config["extratools"]
    return DEFAULT_EXTRACTION_TOOLS


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text()


def build_context(
    story: ExtractedStory,
    segment_result: SegmentResultV2,
    segment_index: int,
    known_entities: list[dict] | None = None,
    book_summary: str | None = None,
) -> str:
    """Build context string for the combined extraction prompt."""
    parts = []

    # 1. Book summary
    if book_summary:
        parts.append(f"BOOK SUMMARY:\n{book_summary}")

    # 2. Book metadata
    if story.book_metadata:
        bm = story.book_metadata
        parts.append(f"BOOK METADATA:\nTitle: {bm.get('title', 'Unknown')}\nAuthor: {bm.get('author', 'Unknown')}\nDynasty/Era: {bm.get('dynasty', 'Unknown')}")

    # 3. Current chapter title
    if story.chapter_title:
        parts.append(f"CURRENT CHAPTER: {story.chapter_title}")

    # 4. Chapter position
    total = len(segment_result.segments)
    parts.append(f"CHAPTER POSITION: {segment_index + 1} / {total}")

    # 5. Adjacent chapter titles
    if segment_index > 0:
        prev_title = segment_result.segments[segment_index - 1].title
        parts.append(f"PREVIOUS CHAPTER: {prev_title}")
    if segment_index < total - 1:
        next_title = segment_result.segments[segment_index + 1].title
        parts.append(f"NEXT CHAPTER: {next_title}")

    # 6. Known entities
    if known_entities:
        entity_str = ", ".join(f"{e['name']} ({e.get('lat', '?')}, {e.get('lng', '?')})" for e in known_entities[:20])
        parts.append(f"KNOWN ENTITIES (for consistency):\n{entity_str}")

    # 7. Source language rules
    lang_rules = {
        "zh-classical": "Source is classical Chinese. Extract modern Chinese and English translations.",
        "zh-modern": "Source is modern Chinese. Extract English translation only.",
        "arabic": "Source is Arabic. Extract English translation only.",
        "en": "Source is English. No translation needed.",
    }
    lang = story.language
    parts.append(f"SOURCE LANGUAGE: {lang}\n{lang_rules.get(lang, 'Extract appropriate translations.')}")

    return "\n\n".join(parts)


def _normalize_story_data(data: dict) -> None:
    """Fix common LLM output issues in story data before Pydantic validation."""
    # Normalize annotations: wrap plain strings in {"note": str}
    ann = data.get("annotations")
    if isinstance(ann, list):
        normalized: list[dict] = []
        for a in ann:
            if isinstance(a, str):
                normalized.append({"note": a})
            elif isinstance(a, dict):
                normalized.append(a)
            else:
                normalized.append({"note": str(a)})
        data["annotations"] = normalized


async def extract(
    segment_result: SegmentResultV2,
    llm: LLMClient,
    book_summary: str | None = None,
    known_entities: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    """Stage 3: Extract all data from each story via combined LLM call.

    Uses the combined filter+extract prompt. Handles:
    - Non-content detection (is_content field)
    - Multi-story segmentation (entries[] array)
    - Full field extraction (excerpt, summary, entities, credibility)
    """
    prompt_template = load_prompt("extraction_combined")
    stats = {"processed": 0, "skipped": 0, "failed": 0}

    # Collect known entities from already-processed stories
    if known_entities is None:
        known_entities = []
        for seg_info in segment_result.segments:
            story_path = Path(seg_info.file_path)
            if not story_path.exists():
                continue
            data = json.loads(story_path.read_text(encoding="utf-8"))
            s = ExtractedStory(**data)
            if s.entities:
                for loc in s.entities.get("locations", []):
                    if loc.get("name") and loc.get("lat") and loc.get("lng"):
                        known_entities.append(loc)

    for seg_idx, seg_info in enumerate(segment_result.segments):
        story_path = Path(seg_info.file_path)
        if not story_path.exists():
            stats["failed"] += 1
            continue

        story_data = json.loads(story_path.read_text(encoding="utf-8"))
        _normalize_story_data(story_data)
        story = ExtractedStory(**story_data)

        if story.extracted:
            stats["skipped"] += 1
            continue

        if not story.is_content:
            story.extracted = True
            story.error = "non_content"
            story_path.write_text(story.model_dump_json(indent=2), encoding="utf-8")
            stats["skipped"] += 1
            print(f"    [{seg_info.id}] skipped (non-content)")
            continue

        ok = await _extract_single(
            story, story_path, seg_info, seg_idx,
            segment_result, llm, prompt_template,
            known_entities, book_summary, config,
        )
        if ok:
            stats["processed"] += 1
        else:
            stats["failed"] += 1

    # Retry pass: re-attempt failed entries
    if stats["failed"] > 0:
        print(f"\n  Retrying {stats['failed']} failed entries...")
        retry_failed = 0
        for seg_idx, seg_info in enumerate(segment_result.segments):
            story_path = Path(seg_info.file_path)
            if not story_path.exists():
                continue

            story_data = json.loads(story_path.read_text(encoding="utf-8"))
            _normalize_story_data(story_data)
            story = ExtractedStory(**story_data)

            if story.extracted or not story.is_content:
                continue

            print(f"    [{seg_info.id}] retrying...", end=" ", flush=True)
            ok = await _extract_single(
                story, story_path, seg_info, seg_idx,
                segment_result, llm, prompt_template,
                known_entities, book_summary, config,
            )
            if ok:
                stats["processed"] += 1
                stats["failed"] -= 1
            else:
                retry_failed += 1

        if retry_failed:
            print(f"  {retry_failed} entries still failed after retry")

    return stats


async def _extract_single(
    story: ExtractedStory,
    story_path: Path,
    seg_info,
    seg_idx: int,
    segment_result: SegmentResultV2,
    llm: LLMClient,
    prompt_template: str,
    known_entities: list[dict],
    book_summary: str | None,
    config: dict | None,
) -> bool:
    """Extract data for a single story. Returns True on success, False on failure."""
    context = build_context(story, segment_result, seg_idx, known_entities, book_summary)
    prompt = prompt_template.format(context=context, text=story.original_text)

    try:
        try:
            raw = await llm.chat_with_tools(
                prompt=prompt,
                system="You are a historical text analysis expert.",
                tools=get_extraction_tools(config),
                response_format={"type": "json_object"},
                max_tokens=(config or {}).get("llm", {}).get("max_tokens", 8192),
            )
        except Exception:
            raw = await llm.extract_json(
                prompt=prompt,
                system="You are a historical text analysis expert. Be concise. Return ONLY valid JSON.",
                max_tokens=8192,
            )

        if not raw or not raw.strip():
            raise ValueError("LLM returned empty response")

        # Clean markdown fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            raw = "\n".join(lines)

        try:
            extracted = json.loads(raw)
        except json.JSONDecodeError:
            # Try to recover malformed/truncated JSON
            fixed = raw.rstrip()
            if fixed.endswith(','):
                fixed = fixed[:-1]
            import re
            fixed = re.sub(r',(\s*[\]}])', r'\1', fixed)
            if fixed.count('"') % 2 != 0:
                fixed += '"'
            open_brackets = fixed.count('[') - fixed.count(']')
            open_braces = fixed.count('{') - fixed.count('}')
            fixed += ']' * max(0, open_brackets)
            fixed += '}' * max(0, open_braces)
            extracted = json.loads(fixed)

        entries = extracted.get("entries", [])
        if not entries:
            raise ValueError("LLM returned no entries")

        # Use the first content entry (typically only 1 per chunk)
        entry = None
        for e in entries:
            if e.get("is_content", True):
                entry = e
                break

        if entry is None:
            # All entries are non-content
            story.is_content = False
            story.extracted = True
            story.error = "non_content"
            story_path.write_text(story.model_dump_json(indent=2), encoding="utf-8")
            print("non-content")
            return True  # not a failure, just non-content

        # Map entry fields to story
        story_meta = entry.get("story_metadata", {})
        excerpt = entry.get("excerpt", {})
        summary = entry.get("summary", {})
        entities = entry.get("entities", {})
        credibility = entry.get("credibility", {})

        story.story_metadata = story_meta
        story.entities = entities
        story.credibility = credibility
        story.annotations = entry.get("annotations", [])

        story.excerpt_original = excerpt.get("original")
        story.excerpt_translation = excerpt.get("translation")
        story.summary_chinese = summary.get("chinese")
        story.summary_english = summary.get("english")
        story.persons = entities.get("persons")
        story.dates = entities.get("dates")

        # Keep legacy translations field populated for backward compat
        story.translations = {
            "modern_chinese": summary.get("chinese"),
            "english": summary.get("english"),
        }

        story.is_truncated = entry.get("is_truncated", False)
        story.extracted = True
        story.error = None

        # Update known entities
        for loc in entities.get("locations", []):
            if loc.get("name") and loc.get("lat") and loc.get("lng"):
                known_entities.append(loc)

        print("OK")
        story_path.write_text(story.model_dump_json(indent=2), encoding="utf-8")
        return True

    except Exception as e:
        story.extracted = False
        story.error = str(e)[:500]
        print(f"FAIL: {story.error[:80]}")
        story_path.write_text(story.model_dump_json(indent=2), encoding="utf-8")
        return False
