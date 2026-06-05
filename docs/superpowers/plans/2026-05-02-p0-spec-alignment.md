# P0 Spec Alignment — Filters, Search, Geo Certainty, Entry JSON API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close PROJECT_SPECIFICATION.md P0 gaps around wired filters, search across location names and entry keywords, optional `geo_certainty` / `certainty_note` on locations, and API exposure of `credibility` / `annotations` on journal entries—without breaking the existing map loop.

**Architecture:** Fix CRUD `WHERE` clauses that already accept query parameters but ignore them. Extend `search_entries` with `EXISTS` subqueries for linked locations and a cast of `keywords` JSON to text for `ILIKE`. Add Alembic migration `004` for two nullable location columns. Thread new fields through Pydantic and the React types used by `LocationDetail` / `MapView`. Keep the HTTP response shape of `GET /api/search` as `list[JournalEntryRead]` so the current frontend hook keeps working.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, pytest + httpx + aiosqlite, React + TypeScript (Vite).

**Out of scope for this plan (follow-up plans):** `LocationName` / alias table, `HistoricalMapLayer` + `GET /api/map-layers`, first-class `Route` / `RouteStop`, bulk admin import, grouped unified search DTO, `summary` / `witness_type` columns, multi-source tabs on location detail.

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `backend/app/crud/journal_entry.py` | Apply `dynasty` / `author` filters in `get_entries`; extend `search_entries` with location name + keywords matching. |
| `backend/app/crud/location.py` | Apply `dynasty` filter via joins through `entry_locations` → `JournalEntry` → `entry_authors` → `Author`. |
| `backend/app/models/location.py` | New ORM columns `geo_certainty`, `certainty_note`. |
| `backend/app/schemas/location.py` | `LocationBase` / `LocationUpdate` include new fields. |
| `backend/app/schemas/journal_entry.py` | `JournalEntryBase`, `JournalEntryUpdate`, and create path include `credibility`, `annotations`. |
| `backend/alembic/versions/004_add_location_geo_certainty.py` | Migration adding columns to `locations`. |
| `backend/app/tests/test_public_entries.py` | Integration tests for filtered entry lists. |
| `backend/app/tests/test_public_locations.py` | Integration test for `dynasty` query on locations. |
| `backend/app/tests/test_search.py` | Tests for search by location name and keywords. |
| `backend/app/tests/test_public_entries.py` or new `test_journal_entry_schema.py` | Optional: assert `GET /api/entries/{id}` returns `credibility` / `annotations`. |
| `frontend/src/types/index.ts` | `Location`, `LocationDetail`, `JournalEntry` types extended. |
| `frontend/src/components/Panel/QuickInfo.tsx` | Display certainty badge and note when present. |
| `frontend/src/components/Map/MapView.tsx` | Extend `MapLocation` with optional `geo_certainty` for later marker styling (display-only in this plan). |

---

### Task 1: Wire `dynasty` and `author` filters in `get_entries`

**Files:**

- Modify: `backend/app/crud/journal_entry.py` (function `get_entries`, approx. lines 22–43)
- Modify: `backend/app/tests/test_public_entries.py`

- [ ] **Step 1: Write failing test — filter by dynasty**

Append to `backend/app/tests/test_public_entries.py`:

```python
from app.models.author import Author
from app.models.associations import entry_authors


@pytest.mark.asyncio
async def test_list_entries_filter_dynasty(client, db_session):
    tang = Author(name="玄奘", dynasty="唐")
    yuan = Author(name="马可·波罗", dynasty="元")
    book = Book(title="Corpus")
    db_session.add_all([tang, yuan, book])
    await db_session.flush()
    e_tang = JournalEntry(book_id=book.id, title="西域记", original_text="雪山")
    e_yuan = JournalEntry(book_id=book.id, title="游记", original_text="港口")
    db_session.add_all([e_tang, e_yuan])
    await db_session.flush()
    await db_session.execute(
        entry_authors.insert().values(entry_id=e_tang.id, author_id=tang.id)
    )
    await db_session.execute(
        entry_authors.insert().values(entry_id=e_yuan.id, author_id=yuan.id)
    )
    await db_session.flush()

    resp = await client.get("/api/entries", params={"dynasty": "唐"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "西域记"


@pytest.mark.asyncio
async def test_list_entries_filter_author_name(client, db_session):
    a1 = Author(name="玄奘", dynasty="唐")
    a2 = Author(name="法显", dynasty="晋")
    book = Book(title="Corpus")
    db_session.add_all([a1, a2, book])
    await db_session.flush()
    e1 = JournalEntry(book_id=book.id, title="A文", original_text="x")
    e2 = JournalEntry(book_id=book.id, title="B文", original_text="y")
    db_session.add_all([e1, e2])
    await db_session.flush()
    await db_session.execute(entry_authors.insert().values(entry_id=e1.id, author_id=a1.id))
    await db_session.execute(entry_authors.insert().values(entry_id=e2.id, author_id=a2.id))
    await db_session.flush()

    resp = await client.get("/api/entries", params={"author": "法显"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "B文"
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd /Users/zero/project/hismap/hismap/backend && pytest app/tests/test_public_entries.py::test_list_entries_filter_dynasty app/tests/test_public_entries.py::test_list_entries_filter_author_name -v
```

Expected: FAIL (both tests return 2 rows instead of 1, or similar assertion failure).

- [ ] **Step 3: Implement filters in CRUD**

Add import: `from app.models.author import Author` (file already imports `or_`, `select`, `entry_authors`, `JournalEntry`).

Replace the body of `get_entries` with:

```python
async def get_entries(
    db: AsyncSession,
    dynasty: str | None = None,
    author: str | None = None,
    keyword: str | None = None,
    era: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[JournalEntry]:
    stmt = _base_query()
    if dynasty or author:
        stmt = stmt.join(entry_authors).join(Author, Author.id == entry_authors.c.author_id)
        if dynasty:
            stmt = stmt.where(Author.dynasty == dynasty)
        if author:
            stmt = stmt.where(Author.name == author)
        stmt = stmt.distinct()
    if era:
        stmt = stmt.where(JournalEntry.era_context == era)
    if keyword:
        stmt = stmt.where(
            or_(
                JournalEntry.original_text.ilike(f"%{keyword}%"),
                JournalEntry.modern_translation.ilike(f"%{keyword}%"),
                JournalEntry.title.ilike(f"%{keyword}%"),
            )
        )
    result = await db.execute(stmt.offset(skip).limit(limit))
    return list(result.scalars().unique().all())
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd /Users/zero/project/hismap/hismap/backend && pytest app/tests/test_public_entries.py::test_list_entries_filter_dynasty app/tests/test_public_entries.py::test_list_entries_filter_author_name -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/zero/project/hismap/hismap && git add backend/app/crud/journal_entry.py backend/app/tests/test_public_entries.py && git commit -m "fix(api): apply dynasty and author filters to journal entry list"
```

---

### Task 2: Wire `dynasty` filter in `get_locations`

**Files:**

- Modify: `backend/app/crud/location.py`
- Modify: `backend/app/tests/test_public_locations.py`

- [ ] **Step 1: Write failing test**

Append to `backend/app/tests/test_public_locations.py`:

```python
from app.models.author import Author
from app.models.book import Book
from app.models.journal_entry import JournalEntry
from app.models.associations import entry_authors, entry_locations


@pytest.mark.asyncio
async def test_list_locations_filter_dynasty(client, db_session):
    tang = Author(name="玄奘", dynasty="唐")
    yuan = Author(name="马可·波罗", dynasty="元")
    book = Book(title="Corpus")
    loc_tang = Location(name="长安", latitude=34.26, longitude=108.94, location_type="古城")
    loc_yuan = Location(name="泉州", latitude=24.87, longitude=118.67, location_type="港口")
    db_session.add_all([tang, yuan, book, loc_tang, loc_yuan])
    await db_session.flush()
    e_tang = JournalEntry(book_id=book.id, title="唐文", original_text="都城")
    e_yuan = JournalEntry(book_id=book.id, title="元文", original_text="海事")
    db_session.add_all([e_tang, e_yuan])
    await db_session.flush()
    await db_session.execute(entry_authors.insert().values(entry_id=e_tang.id, author_id=tang.id))
    await db_session.execute(entry_authors.insert().values(entry_id=e_yuan.id, author_id=yuan.id))
    await db_session.execute(entry_locations.insert().values(entry_id=e_tang.id, location_id=loc_tang.id, location_order=0))
    await db_session.execute(entry_locations.insert().values(entry_id=e_yuan.id, location_id=loc_yuan.id, location_order=0))
    await db_session.flush()

    resp = await client.get("/api/locations", params={"dynasty": "唐"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "长安"
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd /Users/zero/project/hismap/hismap/backend && pytest app/tests/test_public_locations.py::test_list_locations_filter_dynasty -v
```

Expected: FAIL (returns 2 locations).

- [ ] **Step 3: Implement dynasty filter**

In `backend/app/crud/location.py`, import `JournalEntry`, `Author`, `entry_locations`, `entry_authors`. Extend `get_locations`:

```python
async def get_locations(
    db: AsyncSession,
    location_type: str | None = None,
    dynasty: str | None = None,
    skip: int = 0,
    limit: int = 1000,
) -> list[Location]:
    stmt = select(Location)
    if location_type:
        stmt = stmt.where(Location.location_type == location_type)
    if dynasty:
        stmt = (
            stmt.join(entry_locations, entry_locations.c.location_id == Location.id)
            .join(JournalEntry, JournalEntry.id == entry_locations.c.entry_id)
            .join(entry_authors, entry_authors.c.entry_id == JournalEntry.id)
            .join(Author, Author.id == entry_authors.c.author_id)
            .where(Author.dynasty == dynasty)
            .distinct()
        )
    result = await db.execute(stmt.offset(skip).limit(limit))
    return list(result.scalars().unique().all())
```

- [ ] **Step 4: Run full location tests**

```bash
cd /Users/zero/project/hismap/hismap/backend && pytest app/tests/test_public_locations.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/zero/project/hismap/hismap && git add backend/app/crud/location.py backend/app/tests/test_public_locations.py && git commit -m "fix(api): filter locations list by author dynasty"
```

---

### Task 3: Extend search to locations and keywords

**Files:**

- Modify: `backend/app/crud/journal_entry.py` (`search_entries`)
- Modify: `backend/app/tests/test_search.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/app/tests/test_search.py`:

```python
from app.models.location import Location
from app.models.associations import entry_locations


@pytest.mark.asyncio
async def test_search_by_linked_location_name(client, db_session):
    book = Book(title="Test Book")
    db_session.add(book)
    await db_session.flush()
    loc = Location(name="刺桐", latitude=24.87, longitude=118.67, modern_name="泉州", ancient_name=None)
    db_session.add(loc)
    await db_session.flush()
    entry = JournalEntry(
        book_id=book.id,
        title="航程",
        original_text="无关正文",
        keywords=["ship"],
    )
    db_session.add(entry)
    await db_session.flush()
    await db_session.execute(
        entry_locations.insert().values(entry_id=entry.id, location_id=loc.id, location_order=0)
    )
    await db_session.flush()

    resp = await client.get("/api/search", params={"q": "刺桐"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == entry.id


@pytest.mark.asyncio
async def test_search_by_keywords_json(client, db_session):
    book = Book(title="Test Book")
    db_session.add(book)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            book_id=book.id,
            title="贸易",
            original_text="正文不含关键词",
            keywords=["香料", "海上丝绸之路"],
        )
    )
    await db_session.flush()

    resp = await client.get("/api/search", params={"q": "香料"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "贸易"
```

- [ ] **Step 2: Run new tests — expect failure**

```bash
cd /Users/zero/project/hismap/hismap/backend && pytest app/tests/test_search.py::test_search_by_linked_location_name app/tests/test_search.py::test_search_by_keywords_json -v
```

Expected: FAIL (empty or wrong count).

- [ ] **Step 3: Implement `search_entries`**

At top of `journal_entry.py`, extend imports: `from sqlalchemy import cast, exists, String` (keep existing `or_`, `select`). Add `from app.models.location import Location`. The file already imports `entry_locations` from `app.models.associations`.

Replace `search_entries` with:

```python
async def search_entries(db: AsyncSession, query: str, limit: int = 50) -> list[JournalEntry]:
    q = f"%{query}%"
    linked_location = exists(
        select(1)
        .select_from(
            entry_locations.join(Location, Location.id == entry_locations.c.location_id)
        )
        .where(entry_locations.c.entry_id == JournalEntry.id)
        .where(
            or_(
                Location.name.ilike(q),
                Location.modern_name.ilike(q),
                Location.ancient_name.ilike(q),
            )
        )
    )
    keywords_match = JournalEntry.keywords.isnot(None) & cast(JournalEntry.keywords, String).ilike(q)

    stmt = (
        _base_query()
        .where(
            or_(
                JournalEntry.original_text.ilike(q),
                JournalEntry.modern_translation.ilike(q),
                JournalEntry.english_translation.ilike(q),
                JournalEntry.title.ilike(q),
                JournalEntry.era_context.ilike(q),
                JournalEntry.political_context.ilike(q),
                linked_location,
                keywords_match,
            )
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())
```

- [ ] **Step 4: Run all search tests**

```bash
cd /Users/zero/project/hismap/hismap/backend && pytest app/tests/test_search.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/zero/project/hismap/hismap && git add backend/app/crud/journal_entry.py backend/app/tests/test_search.py && git commit -m "feat(api): search entries by linked location names and keywords"
```

---

### Task 4: Location `geo_certainty` and `certainty_note`

**Files:**

- Create: `backend/alembic/versions/004_add_location_geo_certainty.py`
- Modify: `backend/app/models/location.py`
- Modify: `backend/app/schemas/location.py`
- Modify: `backend/app/tests/test_public_locations.py` (detail response) or `test_admin_locations.py` if present

- [ ] **Step 1: Add Alembic revision**

Create `backend/alembic/versions/004_add_location_geo_certainty.py`:

```python
"""Add geo_certainty and certainty_note to locations.

Revision ID: 004
Revises: 003
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("geo_certainty", sa.String(length=32), nullable=True))
    op.add_column("locations", sa.Column("certainty_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("locations", "certainty_note")
    op.drop_column("locations", "geo_certainty")
```

Run:

```bash
cd /Users/zero/project/hismap/hismap/backend && alembic upgrade head
```

Expected: completes without error on dev database (optional in CI if migrations applied in test via metadata only—tests use `create_all` from models, so you **must** add ORM columns for tests to see columns).

- [ ] **Step 2: Update SQLAlchemy model**

In `backend/app/models/location.py`, after `today_remains`:

```python
    geo_certainty: Mapped[str | None] = mapped_column(String(32))
    certainty_note: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 3: Update Pydantic schemas**

In `backend/app/schemas/location.py`, add to `LocationBase` and `LocationUpdate`:

```python
    geo_certainty: str | None = None
    certainty_note: str | None = None
```

(`LocationUpdate` should allow patching these fields.)

- [ ] **Step 4: Write API test for GET location detail**

Append to `backend/app/tests/test_public_locations.py`:

```python
@pytest.mark.asyncio
async def test_get_location_includes_geo_certainty(client, db_session):
    loc = Location(
        name="Zanzibar",
        latitude=-6.1659,
        longitude=39.2026,
        geo_certainty="approximate",
        certainty_note="Medieval Zanj may denote a wider coast.",
    )
    db_session.add(loc)
    await db_session.flush()

    resp = await client.get(f"/api/locations/{loc.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["geo_certainty"] == "approximate"
    assert "Zanj" in body["certainty_note"]
```

- [ ] **Step 5: Run location tests**

```bash
cd /Users/zero/project/hismap/hismap/backend && pytest app/tests/test_public_locations.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/zero/project/hismap/hismap && git add backend/alembic/versions/004_add_location_geo_certainty.py backend/app/models/location.py backend/app/schemas/location.py backend/app/tests/test_public_locations.py && git commit -m "feat(db): add geo_certainty and certainty_note to locations"
```

---

### Task 5: Expose `credibility` and `annotations` on journal entry schemas

**Files:**

- Modify: `backend/app/schemas/journal_entry.py`
- Modify: `backend/app/tests/test_public_entries.py`

- [ ] **Step 1: Extend Pydantic models**

In `JournalEntryBase`, add:

```python
    credibility: dict | None = None
    annotations: list | None = None
```

In `JournalEntryUpdate`, add the same two fields as optional (`dict | None = None`, `list | None = None`).

- [ ] **Step 2: Write test**

Append to `backend/app/tests/test_public_entries.py`:

```python
@pytest.mark.asyncio
async def test_get_entry_includes_credibility_annotations(client, db_session):
    book = Book(title="Test Book")
    db_session.add(book)
    await db_session.flush()
    entry = JournalEntry(
        book_id=book.id,
        title="Excerpt",
        original_text="text",
        credibility={"credibility_score": 0.9, "notes": "eyewitness"},
        annotations=[{"type": "place", "text": "港"}],
    )
    db_session.add(entry)
    await db_session.flush()

    resp = await client.get(f"/api/entries/{entry.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["credibility"]["credibility_score"] == 0.9
    assert len(data["annotations"]) == 1
```

- [ ] **Step 3: Run test**

```bash
cd /Users/zero/project/hismap/hismap/backend && pytest app/tests/test_public_entries.py::test_get_entry_includes_credibility_annotations -v
```

Expected: PASS once schemas include fields (Pydantic `from_attributes` reads ORM).

- [ ] **Step 4: Run full backend test suite**

```bash
cd /Users/zero/project/hismap/hismap/backend && pytest app/tests -q
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/zero/project/hismap/hismap && git add backend/app/schemas/journal_entry.py backend/app/tests/test_public_entries.py && git commit -m "feat(api): expose journal entry credibility and annotations"
```

---

### Task 6: Frontend types and certainty display

**Files:**

- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/components/Panel/QuickInfo.tsx`
- Modify: `frontend/src/components/Map/MapView.tsx` (interface only)

- [ ] **Step 1: Update TypeScript types**

In `frontend/src/types/index.ts`, extend `Location`:

```ts
  geo_certainty?: string | null;
  certainty_note?: string | null;
```

Extend `JournalEntry` and `JournalEntryDetail`:

```ts
  credibility?: Record<string, unknown> | null;
  annotations?: unknown[] | null;
```

- [ ] **Step 2: Show certainty in QuickInfo**

After the coordinates block in `QuickInfo.tsx`, add:

```tsx
        {location.geo_certainty && (
          <div className="col-span-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">
            <span className="font-medium">地理可信度:</span> {location.geo_certainty}
            {location.certainty_note && (
              <p className="mt-1 text-gray-700">{location.certainty_note}</p>
            )}
          </div>
        )}
```

- [ ] **Step 3: Extend MapLocation**

In `MapView.tsx`, extend `MapLocation`:

```ts
  geo_certainty?: string | null;
```

Ensure `useLocations` / parent passes through if API returns these fields (no transform needed if spreading API data).

- [ ] **Step 4: Run frontend build**

```bash
cd /Users/zero/project/hismap/hismap/frontend && npm run build
```

Expected: exit code 0

- [ ] **Step 5: Commit**

```bash
cd /Users/zero/project/hismap/hismap && git add frontend/src/types/index.ts frontend/src/components/Panel/QuickInfo.tsx frontend/src/components/Map/MapView.tsx && git commit -m "feat(ui): surface location geo certainty and entry JSON fields in types"
```

---

## Self-review

| Spec / requirement (PROJECT_SPECIFICATION.md) | Task covering it |
|-----------------------------------------------|------------------|
| P0: filters by traveler (`Author`), textual context — dynasty/author wired | Task 1, Task 2 |
| P0: search modern/ancient names — via linked `Location` names | Task 3 |
| P0: search entry keywords | Task 3 |
| P0: uncertain geography explicit (`geo_certainty`, note) | Task 4, Task 6 |
| P0: structured notes in API (`credibility`, `annotations`) | Task 5 |
| Aliases (`LocationName`), unified grouped search, historical layers, routes API | Out of scope (documented above) |

**Placeholder scan:** No `TBD` / `TODO` / vague-only steps; migration and code blocks are concrete.

**Type consistency:** `geo_certainty` is `str | None` in Python and optional `string | null` in TS; `credibility` is `dict` / `Record<string, unknown>`; `annotations` is `list` / `unknown[]`.

---

## Plan complete and saved to `docs/superpowers/plans/2026-05-02-p0-spec-alignment.md`

**Two execution options:**

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. **REQUIRED SUB-SKILL:** superpowers:subagent-driven-development.

2. **Inline Execution** — Execute tasks in this session with checkpoints. **REQUIRED SUB-SKILL:** superpowers:executing-plans.

**Which approach?**
