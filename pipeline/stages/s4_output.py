from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.associations import entry_authors, entry_locations
from app.models.author import Author
from app.models.book import Book
from app.models.journal_entry import JournalEntry
from app.models.location import Location
from pipeline.models import ExtractedStory, OutputResult, SegmentResultV2
from pipeline.stages.s3_extract import _normalize_story_data


async def output_to_db(
    segment_result: SegmentResultV2,
    session: AsyncSession,
) -> OutputResult:
    """Stage 4: Write extracted stories to database.

    Reads each story's JSON file, creates Book, Author, Location, JournalEntry records.
    Uses a single transaction -- rolls back all on failure.
    """
    stats = OutputResult()

    stories: list[ExtractedStory] = []
    for seg_info in segment_result.segments:
        story_path = Path(seg_info.file_path)
        if not story_path.exists():
            continue
        data = json.loads(story_path.read_text(encoding="utf-8"))
        _normalize_story_data(data)
        stories.append(ExtractedStory(**data))

    if not stories:
        return stats

    # 1. Create Book from first story's book_metadata
    first = stories[0]
    book = None
    if first.book_metadata:
        bm = first.book_metadata
        book = Book(
            title=bm.get("title", segment_result.book_slug),
            author=bm.get("author"),
            dynasty=bm.get("dynasty"),
            era_start=bm.get("era_start"),
            era_end=bm.get("era_end"),
            source_text=f"pipeline/output/{segment_result.book_slug}",
        )
        session.add(book)
        await session.flush()
        stats.books = 1

    # 2. Create Author
    author = None
    if first.book_metadata and first.book_metadata.get("author"):
        am = first.book_metadata
        author = Author(
            name=am["author"],
            dynasty=am.get("dynasty"),
            birth_year=None,
            death_year=None,
            biography=am.get("author_biography"),
        )
        session.add(author)
        await session.flush()
        stats.authors = 1

    # 3. Deduplicate locations
    loc_map: dict[str, Location] = {}
    for story in stories:
        if not story.entities:
            continue
        for loc_data in story.entities.get("locations", []):
            name = loc_data.get("name", "")
            if name and name not in loc_map:
                loc = Location(
                    name=name,
                    modern_name=loc_data.get("modern_name"),
                    ancient_name=loc_data.get("ancient_name"),
                    latitude=loc_data.get("lat") or 0.0,
                    longitude=loc_data.get("lng") or 0.0,
                    location_type=loc_data.get("location_type"),
                    one_line_summary=loc_data.get("one_line_summary"),
                )
                session.add(loc)
                await session.flush()
                loc_map[name] = loc
                stats.locations += 1

    # 4. Create JournalEntry for each content story
    for story in stories:
        if not story.is_content:
            continue

        rel_path = f"pipeline/output/{segment_result.book_slug}/{story.id}.json"

        story_meta = story.story_metadata or {}
        entities = story.entities or {}
        credibility = story.credibility or {}

        je = JournalEntry(
            book_id=book.id if book else None,
            title=story_meta.get("title", story.title),
            original_text=rel_path,
            excerpt_original=story.excerpt_original,
            excerpt_translation=story.excerpt_translation,
            summary_chinese=story.summary_chinese,
            summary_english=story.summary_english,
            chapter_reference=story_meta.get("chapter_reference"),
            keywords=entities.get("keywords"),
            persons=story.persons,
            dates=story.dates,
            era_context=credibility.get("era_context"),
            political_context=credibility.get("political_context"),
            religious_context=credibility.get("religious_context"),
            social_environment=credibility.get("social_environment"),
            visit_date_approximate=story_meta.get("visit_date_approximate"),
            credibility=credibility if credibility else None,
            annotations=story.annotations if story.annotations else None,
        )
        session.add(je)
        await session.flush()

        for i, loc_data in enumerate(entities.get("locations", [])):
            name = loc_data.get("name", "")
            if name in loc_map:
                # Find importance from annotations
                importance = 0
                for ann in story.annotations or []:
                    if ann.get("marker_title", "").lower().startswith(name.lower()):
                        importance = ann.get("importance", 0)
                        break

                await session.execute(
                    entry_locations.insert().values(
                        entry_id=je.id,
                        location_id=loc_map[name].id,
                        location_order=i,
                        importance=importance,
                    )
                )

        if author:
            await session.execute(
                entry_authors.insert().values(entry_id=je.id, author_id=author.id)
            )

        stats.entries += 1

    await session.commit()
    return stats
