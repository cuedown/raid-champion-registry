from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DEFAULT_SOURCES = PROJECT_ROOT / "data" / "sources.json"
DEFAULT_MASTERIES = PROJECT_ROOT / "data" / "masteries.json"
SCHEMA = PACKAGE_ROOT / "schema.sql"
PARSER_VERSION = "registry-0.1"


class RegistryError(ValueError):
    """Raised when source data cannot safely enter the registry."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def load_document(path: str | Path) -> Any:
    source = Path(path)
    if source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    with source.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def initialize_database(
    path: str | Path,
    *,
    sources_path: str | Path = DEFAULT_SOURCES,
    masteries_path: str | Path = DEFAULT_MASTERIES,
) -> dict[str, int]:
    con = connect(path)
    try:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        con.execute(
            "INSERT OR REPLACE INTO registry_meta(key, value) VALUES ('schema_version', '1')"
        )
        sources = seed_sources(con, load_document(sources_path))
        masteries = seed_masteries(con, load_document(masteries_path))
        con.commit()
        return {"sources": sources, "masteries": masteries}
    finally:
        con.close()


def seed_sources(con: sqlite3.Connection, document: dict[str, Any]) -> int:
    rows = document.get("sources", [])
    for source in rows:
        con.execute(
            """
            INSERT INTO source_policy(
                source_key, name, homepage, terms_url, license_id, source_kind,
                automated_fetch_allowed, authority_level, max_age_days, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                name=excluded.name,
                homepage=excluded.homepage,
                terms_url=excluded.terms_url,
                license_id=excluded.license_id,
                source_kind=excluded.source_kind,
                automated_fetch_allowed=excluded.automated_fetch_allowed,
                authority_level=excluded.authority_level,
                max_age_days=excluded.max_age_days,
                notes=excluded.notes
            """,
            (
                source["source_key"],
                source["name"],
                source["homepage"],
                source.get("terms_url"),
                source.get("license_id"),
                source["source_kind"],
                int(bool(source.get("automated_fetch_allowed"))),
                int(source.get("authority_level", 0)),
                source.get("max_age_days"),
                source.get("notes", ""),
            ),
        )
    return len(rows)


def seed_masteries(con: sqlite3.Connection, document: dict[str, Any]) -> int:
    metadata = document.get("metadata", {})
    source_url = metadata.get("source", "")
    source_ref = metadata.get("source_ref", "")
    rows = document.get("masteries", [])
    if len(rows) != 66:
        raise RegistryError(f"expected the canonical 66 mastery nodes; got {len(rows)}")
    for mastery in rows:
        con.execute(
            """
            INSERT INTO mastery(id, slug, name, tree, tier, position, source_url, source_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                slug=excluded.slug,
                name=excluded.name,
                tree=excluded.tree,
                tier=excluded.tier,
                position=excluded.position,
                source_url=excluded.source_url,
                source_ref=excluded.source_ref
            """,
            (
                int(mastery["id"]),
                mastery["slug"],
                mastery["name"],
                mastery["tree"],
                int(mastery["tier"]),
                int(mastery["position"]),
                source_url,
                source_ref,
            ),
        )
    return len(rows)


def create_snapshot(
    con: sqlite3.Connection,
    *,
    source_key: str,
    source_ref: str,
    source_url: str,
    digest: str,
    observed_updated_at: str | None = None,
    raw_path: str | None = None,
    retrieved_at: str | None = None,
) -> int:
    if con.execute(
        "SELECT 1 FROM source_policy WHERE source_key = ?", (source_key,)
    ).fetchone() is None:
        raise RegistryError(f"unknown source policy: {source_key}")
    retrieved = retrieved_at or utc_now()
    con.execute(
        """
        INSERT INTO source_snapshot(
            source_key, source_ref, source_url, retrieved_at, observed_updated_at,
            content_sha256, parser_version, raw_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_key, source_ref, content_sha256) DO NOTHING
        """,
        (
            source_key,
            source_ref,
            source_url,
            retrieved,
            observed_updated_at,
            digest,
            PARSER_VERSION,
            raw_path,
        ),
    )
    row = con.execute(
        """
        SELECT id FROM source_snapshot
        WHERE source_key = ? AND source_ref = ? AND content_sha256 = ?
        """,
        (source_key, source_ref, digest),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _first(record: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _nested(document: Any, path: Sequence[str]) -> Any:
    value = document
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def iter_champion_records(document: Any) -> Iterator[dict[str, Any]]:
    if isinstance(document, list):
        for row in document:
            if isinstance(row, dict):
                yield row
        return
    if not isinstance(document, dict):
        raise RegistryError("champion input must be a JSON object, JSON array, or CSV")
    paths = (
        ("champions",),
        ("heroes",),
        ("hero_types",),
        ("heroTypes",),
        ("data", "champions"),
        ("data", "heroes"),
        ("static", "champions"),
        ("account", "champions"),
        ("account", "heroes"),
    )
    for path in paths:
        rows = _nested(document, path)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    yield row
            return
    if any(key in document for key in ("name", "champion_name", "hero_name")):
        yield document
        return
    raise RegistryError("could not locate a champion array in the supplied document")


RARITY_ALIASES = {
    "mythic": "Mythical",
    "mythical": "Mythical",
    "legendary": "Legendary",
    "epic": "Epic",
    "rare": "Rare",
    "uncommon": "Uncommon",
    "common": "Common",
}
AFFINITY_ALIASES = {value.lower(): value for value in ("Magic", "Force", "Spirit", "Void")}
TYPE_ALIASES = {
    "attack": "Attack",
    "atk": "Attack",
    "defense": "Defense",
    "defence": "Defense",
    "def": "Defense",
    "hp": "HP",
    "health": "HP",
    "support": "Support",
}


def _enum_value(value: Any, aliases: dict[str, str], field: str) -> str | None:
    if value in (None, ""):
        return None
    normalized = aliases.get(str(value).strip().lower())
    if normalized is None:
        raise RegistryError(f"unknown {field} value: {value!r}")
    return normalized


def normalize_champion(record: dict[str, Any]) -> dict[str, Any]:
    nested_type = record.get("type") if isinstance(record.get("type"), dict) else {}
    name = _first(record, ("name", "champion_name", "championName", "hero_name", "heroName", "title"))
    name = name or _first(nested_type, ("name", "title"))
    if not name or not str(name).strip():
        raise RegistryError("champion record has no name")
    name = str(name).strip()
    game_id = _first(
        record,
        (
            "game_id", "gameId", "giid", "type_id", "typeId", "hero_type_id",
            "heroTypeId", "kind_id", "kindId", "id",
        ),
    )
    if game_id not in (None, ""):
        try:
            game_id = int(game_id)
        except (TypeError, ValueError) as exc:
            raise RegistryError(f"invalid game ID for {name}: {game_id!r}") from exc
    slug = str(_first(record, ("slug", "canonical_key", "canonicalKey")) or slugify(name))
    rarity = _enum_value(_first(record, ("rarity", "grade")), RARITY_ALIASES, "rarity")
    affinity = _enum_value(_first(record, ("affinity", "element")), AFFINITY_ALIASES, "affinity")
    champion_type = _enum_value(
        _first(record, ("champion_type", "championType", "role_type", "roleType"))
        or (record.get("type") if isinstance(record.get("type"), str) else None),
        TYPE_ALIASES,
        "champion type",
    )
    faction = _first(record, ("faction", "faction_name", "factionName", "faction_slug", "factionSlug"))
    if faction:
        faction = str(faction).replace("-", " ").title()
    return {
        "game_id": game_id,
        "slug": slugify(slug),
        "name": name,
        "rarity": rarity,
        "affinity": affinity,
        "faction": faction,
        "champion_type": champion_type,
    }


def upsert_champion(
    con: sqlite3.Connection,
    champion: dict[str, Any],
    *,
    snapshot_id: int,
    seen_at: str | None = None,
) -> int:
    seen = seen_at or utc_now()
    row = None
    if champion.get("game_id") is not None:
        row = con.execute("SELECT * FROM champion WHERE game_id = ?", (champion["game_id"],)).fetchone()
    if row is None:
        row = con.execute("SELECT * FROM champion WHERE slug = ?", (champion["slug"],)).fetchone()
    if row is None:
        cur = con.execute(
            """
            INSERT INTO champion(
                game_id, slug, name, rarity, affinity, faction, champion_type,
                active, first_seen_at, last_seen_at, source_snapshot_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                champion.get("game_id"), champion["slug"], champion["name"],
                champion.get("rarity"), champion.get("affinity"), champion.get("faction"),
                champion.get("champion_type"), seen, seen, snapshot_id,
            ),
        )
        champion_id = int(cur.lastrowid)
    else:
        if (
            row["game_id"] is not None
            and champion.get("game_id") is not None
            and int(row["game_id"]) != int(champion["game_id"])
        ):
            raise RegistryError(
                f"slug collision: {champion['slug']} maps to game IDs {row['game_id']} and {champion['game_id']}"
            )
        champion_id = int(row["id"])
        if row["name"] != champion["name"]:
            con.execute(
                "INSERT OR IGNORE INTO champion_alias(champion_id, alias, alias_kind) VALUES (?, ?, 'former_name')",
                (champion_id, row["name"]),
            )
        con.execute(
            """
            UPDATE champion SET
                game_id=COALESCE(?, game_id), slug=?, name=?,
                rarity=COALESCE(?, rarity), affinity=COALESCE(?, affinity),
                faction=COALESCE(?, faction), champion_type=COALESCE(?, champion_type),
                active=1, last_seen_at=?, source_snapshot_id=?
            WHERE id=?
            """,
            (
                champion.get("game_id"), champion["slug"], champion["name"],
                champion.get("rarity"), champion.get("affinity"), champion.get("faction"),
                champion.get("champion_type"), seen, snapshot_id, champion_id,
            ),
        )
    con.execute(
        "INSERT OR IGNORE INTO champion_alias(champion_id, alias, alias_kind) VALUES (?, ?, 'canonical_name')",
        (champion_id, champion["name"]),
    )
    return champion_id


def import_champions(
    con: sqlite3.Connection,
    path: str | Path,
    *,
    source_key: str = "game-export",
    source_ref: str | None = None,
    source_url: str | None = None,
) -> dict[str, int]:
    file_path = Path(path)
    document = load_document(file_path)
    digest = content_hash(file_path.read_bytes())
    snapshot_id = create_snapshot(
        con,
        source_key=source_key,
        source_ref=source_ref or file_path.name,
        source_url=source_url or file_path.resolve().as_uri(),
        digest=digest,
        raw_path=str(file_path),
    )
    seen_ids: set[int] = set()
    errors = 0
    for index, raw in enumerate(iter_champion_records(document), start=1):
        try:
            champion = normalize_champion(raw)
            seen_ids.add(upsert_champion(con, champion, snapshot_id=snapshot_id))
        except RegistryError as exc:
            errors += 1
            record_issue(
                con,
                snapshot_id,
                "error",
                str(_first(raw, ("name", "id")) or index),
                "invalid_champion",
                str(exc),
            )
    if not seen_ids:
        raise RegistryError("the source did not contain any importable champions")
    con.commit()
    return {"champions": len(seen_ids), "errors": errors, "snapshot_id": snapshot_id}


def record_issue(
    con: sqlite3.Connection,
    snapshot_id: int | None,
    severity: str,
    entity_key: str | None,
    code: str,
    message: str,
) -> None:
    con.execute(
        """
        INSERT INTO import_issue(source_snapshot_id, severity, entity_key, code, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (snapshot_id, severity, entity_key, code, message, utc_now()),
    )


def resolve_champion(con: sqlite3.Connection, selector: Any) -> sqlite3.Row:
    if isinstance(selector, dict):
        game_id = _first(selector, ("game_id", "gameId", "giid", "id"))
        slug = _first(selector, ("slug", "canonical_key", "canonicalKey"))
        name = _first(selector, ("name", "champion_name", "championName"))
    elif isinstance(selector, int) or (isinstance(selector, str) and selector.isdigit()):
        game_id, slug, name = int(selector), None, None
    else:
        game_id, slug, name = None, slugify(str(selector)), str(selector)
    row = None
    if game_id not in (None, ""):
        row = con.execute("SELECT * FROM champion WHERE game_id = ?", (int(game_id),)).fetchone()
    if row is None and slug:
        row = con.execute("SELECT * FROM champion WHERE slug = ?", (slugify(str(slug)),)).fetchone()
    if row is None and name:
        row = con.execute(
            """
            SELECT c.* FROM champion c
            LEFT JOIN champion_alias a ON a.champion_id = c.id
            WHERE c.name = ? COLLATE NOCASE OR a.alias = ? COLLATE NOCASE
            LIMIT 1
            """,
            (str(name), str(name)),
        ).fetchone()
    if row is None:
        raise RegistryError(f"champion is not in the canonical catalog: {selector!r}")
    return row


def _flatten_mastery_input(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        flattened: list[Any] = []
        for tree in ("offense", "attack", "defense", "defence", "support"):
            nodes = value.get(tree)
            if isinstance(nodes, list):
                flattened.extend(nodes)
        return flattened
    raise RegistryError("masteries must be a list or an object grouped by tree")


def resolve_masteries(con: sqlite3.Connection, values: Any) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    seen: set[int] = set()
    for value in _flatten_mastery_input(values):
        if isinstance(value, dict):
            value = _first(value, ("id", "slug", "name"))
        row = None
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            row = con.execute("SELECT * FROM mastery WHERE id = ?", (int(value),)).fetchone()
        elif value is not None:
            row = con.execute(
                "SELECT * FROM mastery WHERE slug = ? OR name = ? COLLATE NOCASE",
                (slugify(str(value)), str(value)),
            ).fetchone()
        if row is None:
            raise RegistryError(f"unknown mastery: {value!r}")
        mastery_id = int(row["id"])
        if mastery_id in seen:
            raise RegistryError(f"duplicate mastery in build: {row['name']}")
        seen.add(mastery_id)
        rows.append(row)
    return rows


def validate_mastery_path(rows: Sequence[sqlite3.Row], *, approved: bool) -> None:
    if len(rows) > 15:
        raise RegistryError(f"a mastery build cannot contain more than 15 picks; got {len(rows)}")
    trees = Counter(str(row["tree"]) for row in rows)
    if len(trees) > 2:
        raise RegistryError(f"a mastery build may use at most two trees; got {sorted(trees)}")
    tier_six = [row for row in rows if int(row["tier"]) == 6]
    if len(tier_six) > 1:
        raise RegistryError("a mastery build may use only one tier-6 mastery")
    per_tree_tier: dict[str, Counter[int]] = defaultdict(Counter)
    for row in rows:
        per_tree_tier[str(row["tree"])][int(row["tier"])] += 1
    for tree, tier_counts in per_tree_tier.items():
        if tier_counts[1] > 1 or tier_counts[6] > 1:
            raise RegistryError(f"{tree} has too many tier-1 or tier-6 picks")
        if any(tier_counts[tier] > 2 for tier in range(2, 6)):
            raise RegistryError(f"{tree} has more than two picks in a middle tier")
        highest = max(tier_counts)
        missing = [tier for tier in range(1, highest + 1) if tier_counts[tier] == 0]
        if missing:
            raise RegistryError(f"{tree} skips prerequisite tier(s): {missing}")
    if not approved:
        return
    if len(rows) != 15:
        raise RegistryError(f"approved full builds must contain exactly 15 masteries; got {len(rows)}")
    if sorted(trees.values()) != [5, 10]:
        raise RegistryError(f"approved builds must use a 10/5 primary-secondary split; got {dict(trees)}")
    for tree, count in trees.items():
        actual = per_tree_tier[tree]
        expected = {1: 1, 2: 2, 3: 2, 4: 2, 5: 2, 6: 1} if count == 10 else {
            1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 0
        }
        if any(actual[tier] != expected[tier] for tier in range(1, 7)):
            raise RegistryError(
                f"approved {tree} path has invalid tier distribution: {dict(actual)}; expected {expected}"
            )


def _iter_recommendations(document: Any) -> Iterator[tuple[Any, dict[str, Any]]]:
    if not isinstance(document, dict):
        raise RegistryError("recommendation input must be a JSON object")
    if isinstance(document.get("recommendations"), list):
        for recommendation in document["recommendations"]:
            if not isinstance(recommendation, dict):
                continue
            selector = recommendation.get("champion") or document.get("champion")
            if selector is None:
                raise RegistryError("recommendation has no champion selector")
            yield selector, recommendation
        return
    if isinstance(document.get("builds"), list):
        selector = document.get("champion")
        if selector is None:
            raise RegistryError("recommendation document has no champion selector")
        for build in document["builds"]:
            if isinstance(build, dict):
                yield selector, build
        return
    if "masteries" in document and "champion" in document:
        yield document["champion"], document
        return
    raise RegistryError("could not locate recommendation builds in the document")


def upsert_recommendation(
    con: sqlite3.Connection,
    *,
    champion_id: int,
    build: dict[str, Any],
    mastery_rows: Sequence[sqlite3.Row],
    snapshot_id: int,
    default_source_key: str,
) -> int:
    status = str(build.get("status", "draft")).lower()
    if status not in {"draft", "historical", "approved", "rejected"}:
        raise RegistryError(f"unknown recommendation status: {status}")
    evidence = build.get("evidence") or []
    if status == "approved" and not evidence:
        raise RegistryError("approved recommendations require at least one evidence record")
    validate_mastery_path(mastery_rows, approved=status == "approved")
    champion = con.execute("SELECT slug FROM champion WHERE id = ?", (champion_id,)).fetchone()
    assert champion is not None
    title = str(build.get("title") or build.get("name") or "General mastery build").strip()
    key = str(build.get("key") or build.get("recommendation_key") or f"{champion['slug']}:{slugify(title)}")
    scopes = build.get("scopes") or build.get("locations") or ["general"]
    if isinstance(scopes, str):
        scopes = [scopes]
    scopes = sorted({slugify(str(scope)) for scope in scopes if str(scope).strip()})
    if not scopes:
        raise RegistryError(f"recommendation {key} has no scopes")
    reviewed_by = build.get("reviewed_by") or build.get("reviewedBy")
    reviewed_at = build.get("reviewed_at") or build.get("reviewedAt")
    if status == "approved" and (not reviewed_by or not reviewed_at):
        raise RegistryError("approved recommendations require reviewed_by and reviewed_at")
    now = utc_now()
    digest_payload = {
        "key": key,
        "masteries": [int(row["id"]) for row in mastery_rows],
        "scopes": scopes,
        "status": status,
        "rationale": build.get("rationale", ""),
    }
    digest = content_hash(digest_payload)
    con.execute(
        """
        INSERT INTO recommendation(
            recommendation_key, champion_id, title, build_type, status, confidence,
            priority, rationale, authored_by, reviewed_by, reviewed_at,
            source_snapshot_id, content_sha256, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(recommendation_key) DO UPDATE SET
            champion_id=excluded.champion_id,
            title=excluded.title,
            build_type=excluded.build_type,
            status=excluded.status,
            confidence=excluded.confidence,
            priority=excluded.priority,
            rationale=excluded.rationale,
            authored_by=excluded.authored_by,
            reviewed_by=excluded.reviewed_by,
            reviewed_at=excluded.reviewed_at,
            source_snapshot_id=excluded.source_snapshot_id,
            content_sha256=excluded.content_sha256,
            updated_at=excluded.updated_at
        """,
        (
            key,
            champion_id,
            title,
            str(build.get("build_type", build.get("buildType", "general"))),
            status,
            int(build.get("confidence", 50 if status == "draft" else 25)),
            int(build.get("priority", 100)),
            str(build.get("rationale", "")),
            str(build.get("authored_by") or build.get("author") or default_source_key),
            reviewed_by,
            reviewed_at,
            snapshot_id,
            digest,
            now,
            now,
        ),
    )
    recommendation = con.execute(
        "SELECT id FROM recommendation WHERE recommendation_key = ?", (key,)
    ).fetchone()
    assert recommendation is not None
    recommendation_id = int(recommendation["id"])
    con.execute("DELETE FROM recommendation_scope WHERE recommendation_id = ?", (recommendation_id,))
    con.execute("DELETE FROM recommendation_mastery WHERE recommendation_id = ?", (recommendation_id,))
    con.execute("DELETE FROM recommendation_evidence WHERE recommendation_id = ?", (recommendation_id,))
    con.executemany(
        "INSERT INTO recommendation_scope(recommendation_id, scope) VALUES (?, ?)",
        [(recommendation_id, scope) for scope in scopes],
    )
    con.executemany(
        "INSERT INTO recommendation_mastery(recommendation_id, mastery_id, pick_order) VALUES (?, ?, ?)",
        [(recommendation_id, int(row["id"]), index) for index, row in enumerate(mastery_rows, 1)],
    )
    for item in evidence:
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict) or not item.get("url"):
            raise RegistryError(f"invalid evidence record in recommendation {key}")
        evidence_source = str(item.get("source_key") or item.get("source") or default_source_key)
        if con.execute(
            "SELECT 1 FROM source_policy WHERE source_key = ?", (evidence_source,)
        ).fetchone() is None:
            raise RegistryError(f"unknown evidence source policy: {evidence_source}")
        con.execute(
            """
            INSERT INTO recommendation_evidence(
                recommendation_id, source_key, source_url, source_ref,
                observed_updated_at, content_sha256, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recommendation_id,
                evidence_source,
                str(item["url"]),
                item.get("source_ref") or item.get("ref"),
                item.get("observed_updated_at") or item.get("updated_at"),
                item.get("content_sha256") or item.get("sha256"),
                str(item.get("note", "")),
                now,
            ),
        )
    return recommendation_id


def import_recommendations(
    con: sqlite3.Connection,
    path: str | Path,
    *,
    source_key: str = "manual-editorial",
    source_ref: str | None = None,
    source_url: str | None = None,
) -> dict[str, int]:
    file_path = Path(path)
    document = load_document(file_path)
    digest = content_hash(file_path.read_bytes())
    snapshot_id = create_snapshot(
        con,
        source_key=source_key,
        source_ref=source_ref or file_path.name,
        source_url=source_url or file_path.resolve().as_uri(),
        digest=digest,
        raw_path=str(file_path),
    )
    imported = 0
    with con:
        for selector, build in _iter_recommendations(document):
            champion = resolve_champion(con, selector)
            mastery_rows = resolve_masteries(con, build.get("masteries"))
            upsert_recommendation(
                con,
                champion_id=int(champion["id"]),
                build=build,
                mastery_rows=mastery_rows,
                snapshot_id=snapshot_id,
                default_source_key=source_key,
            )
            imported += 1
    return {"recommendations": imported, "snapshot_id": snapshot_id}


def _mastery_values_from_observation(record: dict[str, Any]) -> list[Any]:
    value = _first(record, ("mastery_ids", "masteryIds", "masteries"))
    if isinstance(value, dict):
        value = _first(value, ("unlocked", "ids", "masteries")) or value
    if not isinstance(value, list):
        return []
    return value


def import_observations(
    con: sqlite3.Connection,
    path: str | Path,
    *,
    source_ref: str | None = None,
) -> dict[str, int]:
    file_path = Path(path)
    document = load_document(file_path)
    digest = content_hash(file_path.read_bytes())
    snapshot_id = create_snapshot(
        con,
        source_key="community-observation",
        source_ref=source_ref or file_path.name,
        source_url="local://opt-in-account-export",
        digest=digest,
        raw_path=str(file_path),
    )
    imported = skipped = 0
    now = utc_now()
    with con:
        for raw in iter_champion_records(document):
            values = _mastery_values_from_observation(raw)
            if not values:
                skipped += 1
                continue
            try:
                champion = resolve_champion(
                    con,
                    {
                        "game_id": _first(raw, ("game_id", "gameId", "giid", "type_id", "typeId", "heroTypeId")),
                        "slug": _first(raw, ("slug",)),
                        "name": _first(raw, ("name", "champion_name", "championName", "hero_name", "heroName")),
                    },
                )
                mastery_rows = resolve_masteries(con, values)
                validate_mastery_path(mastery_rows, approved=False)
            except RegistryError as exc:
                skipped += 1
                record_issue(
                    con,
                    snapshot_id,
                    "warning",
                    str(_first(raw, ("name", "game_id", "id"))),
                    "invalid_observation",
                    str(exc),
                )
                continue
            mastery_ids = sorted(int(row["id"]) for row in mastery_rows)
            fingerprint = content_hash(mastery_ids)
            existing = con.execute(
                "SELECT id FROM observed_build WHERE champion_id = ? AND fingerprint = ?",
                (int(champion["id"]), fingerprint),
            ).fetchone()
            if existing is None:
                cur = con.execute(
                    """
                    INSERT INTO observed_build(
                        champion_id, fingerprint, sample_count, first_seen_at,
                        last_seen_at, source_snapshot_id
                    ) VALUES (?, ?, 1, ?, ?, ?)
                    """,
                    (int(champion["id"]), fingerprint, now, now, snapshot_id),
                )
                observed_id = int(cur.lastrowid)
                con.executemany(
                    "INSERT INTO observed_build_mastery(observed_build_id, mastery_id) VALUES (?, ?)",
                    [(observed_id, mastery_id) for mastery_id in mastery_ids],
                )
            else:
                con.execute(
                    """
                    UPDATE observed_build
                    SET sample_count=sample_count + 1, last_seen_at=?, source_snapshot_id=?
                    WHERE id=?
                    """,
                    (now, snapshot_id, int(existing["id"])),
                )
            imported += 1
    return {"observations": imported, "skipped": skipped, "snapshot_id": snapshot_id}


def promote_observations(con: sqlite3.Connection, *, min_samples: int = 5) -> dict[str, int]:
    if min_samples < 1:
        raise RegistryError("min_samples must be at least 1")
    candidates = con.execute(
        """
        WITH ranked AS (
            SELECT ob.*, ROW_NUMBER() OVER (
                PARTITION BY ob.champion_id
                ORDER BY ob.sample_count DESC, ob.last_seen_at DESC, ob.id ASC
            ) AS rank_no
            FROM observed_build ob
            WHERE ob.sample_count >= ?
        )
        SELECT * FROM ranked WHERE rank_no = 1
        """,
        (min_samples,),
    ).fetchall()
    promoted = skipped = 0
    with con:
        for candidate in candidates:
            mastery_rows = con.execute(
                """
                SELECT m.* FROM observed_build_mastery obm
                JOIN mastery m ON m.id = obm.mastery_id
                WHERE obm.observed_build_id = ?
                ORDER BY m.tree, m.tier, m.position
                """,
                (int(candidate["id"]),),
            ).fetchall()
            try:
                validate_mastery_path(mastery_rows, approved=True)
            except RegistryError:
                skipped += 1
                continue
            champion = con.execute(
                "SELECT slug, name FROM champion WHERE id = ?", (int(candidate["champion_id"]),)
            ).fetchone()
            assert champion is not None
            build = {
                "key": f"{champion['slug']}:observed-most-common",
                "title": "Most common observed full build",
                "build_type": "observed",
                "status": "draft",
                "confidence": min(75, 25 + int(candidate["sample_count"])),
                "priority": 500,
                "scopes": ["general"],
                "authored_by": "observation-aggregator",
                "rationale": (
                    f"Anonymized aggregate candidate from {candidate['sample_count']} identical opt-in account exports. "
                    "Popularity is not proof of quality; editorial review is required."
                ),
                "evidence": [
                    {
                        "source_key": "community-observation",
                        "url": f"local://observed-build/{candidate['fingerprint']}",
                        "note": f"sample_count={candidate['sample_count']}",
                    }
                ],
            }
            upsert_recommendation(
                con,
                champion_id=int(candidate["champion_id"]),
                build=build,
                mastery_rows=mastery_rows,
                snapshot_id=int(candidate["source_snapshot_id"]),
                default_source_key="community-observation",
            )
            promoted += 1
    return {"promoted": promoted, "skipped": skipped}


def import_raid_codex_directory(
    con: sqlite3.Connection,
    directory: str | Path,
    *,
    source_ref: str = "b2c3c6a4ac0375cc5bec3c582caf3212a775d83b",
) -> dict[str, int]:
    root = Path(directory)
    files = sorted(path for path in root.glob("*.json") if path.name != "manifest.json")
    if not files:
        raise RegistryError(f"no Raid Codex champion JSON files found in {root}")
    file_hashes = {path.name: content_hash(path.read_bytes()) for path in files}
    snapshot_id = create_snapshot(
        con,
        source_key="raid-codex-2021",
        source_ref=source_ref,
        source_url=f"https://github.com/raid-codex/data/tree/{source_ref}/docs/champions/current",
        digest=content_hash(file_hashes),
        observed_updated_at="2021-05-31T09:36:28Z",
        raw_path=str(root),
    )
    champions = recommendations = skipped = 0
    with con:
        for path in files:
            raw = load_document(path)
            if not isinstance(raw, dict) or not raw.get("name"):
                skipped += 1
                continue
            try:
                champion = normalize_champion(raw)
                champion_id = upsert_champion(con, champion, snapshot_id=snapshot_id)
                champions += 1
            except RegistryError as exc:
                skipped += 1
                record_issue(con, snapshot_id, "warning", path.stem, "raid_codex_champion", str(exc))
                continue
            for index, mastery_build in enumerate(raw.get("masteries") or [], start=1):
                if not isinstance(mastery_build, dict):
                    continue
                try:
                    mastery_rows = resolve_masteries(
                        con,
                        {
                            "offense": mastery_build.get("offense") or [],
                            "defense": mastery_build.get("defense") or [],
                            "support": mastery_build.get("support") or [],
                        },
                    )
                    locations = mastery_build.get("locations") or ["general"]
                    title = "Historical: " + ", ".join(str(value).replace("-", " ").title() for value in locations)
                    build = {
                        "key": f"raid-codex:{champion['slug']}:{index}",
                        "title": title,
                        "build_type": "historical",
                        "status": "historical",
                        "confidence": 25,
                        "priority": 900,
                        "scopes": locations,
                        "authored_by": mastery_build.get("author") or "raid-codex",
                        "rationale": "Historical bootstrap from the final 2021 Raid Codex dataset; must be re-reviewed for the current game.",
                        "evidence": [
                            {
                                "source_key": "raid-codex-2021",
                                "url": f"https://github.com/raid-codex/data/blob/{source_ref}/docs/champions/current/{path.name}",
                                "source_ref": source_ref,
                                "content_sha256": file_hashes[path.name],
                                "note": f"Upstream attribution: {mastery_build.get('from', 'unknown')}",
                            }
                        ],
                    }
                    upsert_recommendation(
                        con,
                        champion_id=champion_id,
                        build=build,
                        mastery_rows=mastery_rows,
                        snapshot_id=snapshot_id,
                        default_source_key="raid-codex-2021",
                    )
                    recommendations += 1
                except RegistryError as exc:
                    skipped += 1
                    record_issue(
                        con,
                        snapshot_id,
                        "warning",
                        f"{path.stem}:{index}",
                        "raid_codex_build",
                        str(exc),
                    )
    return {
        "champions": champions,
        "recommendations": recommendations,
        "skipped": skipped,
        "snapshot_id": snapshot_id,
    }


def audit(con: sqlite3.Connection) -> dict[str, Any]:
    def scalar(sql: str, params: Sequence[Any] = ()) -> int:
        row = con.execute(sql, params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    champions = scalar("SELECT COUNT(*) FROM champion WHERE active = 1")
    approved_champions = scalar(
        "SELECT COUNT(DISTINCT champion_id) FROM recommendation WHERE status = 'approved'"
    )
    statuses = {
        row["status"]: int(row["count"])
        for row in con.execute(
            "SELECT status, COUNT(*) AS count FROM recommendation GROUP BY status"
        ).fetchall()
    }
    return {
        "schema_version": con.execute(
            "SELECT value FROM registry_meta WHERE key = 'schema_version'"
        ).fetchone()[0],
        "champions": champions,
        "mastery_nodes": scalar("SELECT COUNT(*) FROM mastery"),
        "recommendations": statuses,
        "champions_with_approved_builds": approved_champions,
        "champions_without_approved_builds": max(0, champions - approved_champions),
        "approved_coverage_percent": round((approved_champions / champions * 100), 2) if champions else 0.0,
        "observation_samples": scalar("SELECT COALESCE(SUM(sample_count), 0) FROM observed_build"),
        "import_warnings": scalar("SELECT COUNT(*) FROM import_issue WHERE severity = 'warning'"),
        "import_errors": scalar("SELECT COUNT(*) FROM import_issue WHERE severity = 'error'"),
    }


def validate_database(con: sqlite3.Connection, *, require_complete: bool = False) -> dict[str, Any]:
    report = audit(con)
    failures: list[str] = []
    if report["mastery_nodes"] != 66:
        failures.append(f"expected 66 mastery nodes, found {report['mastery_nodes']}")
    foreign_keys = con.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        failures.append(f"foreign key violations: {len(foreign_keys)}")
    approved = con.execute(
        "SELECT id, recommendation_key FROM recommendation WHERE status = 'approved'"
    ).fetchall()
    for recommendation in approved:
        rows = con.execute(
            """
            SELECT m.* FROM recommendation_mastery rm
            JOIN mastery m ON m.id = rm.mastery_id
            WHERE rm.recommendation_id = ? ORDER BY rm.pick_order
            """,
            (int(recommendation["id"]),),
        ).fetchall()
        try:
            validate_mastery_path(rows, approved=True)
        except RegistryError as exc:
            failures.append(f"{recommendation['recommendation_key']}: {exc}")
    if require_complete and report["champions_without_approved_builds"]:
        failures.append(
            f"{report['champions_without_approved_builds']} active champions have no approved mastery build"
        )
    report["valid"] = not failures
    report["failures"] = failures
    return report


def export_registry(
    con: sqlite3.Connection,
    *,
    statuses: Iterable[str] = ("approved",),
    include_uncovered: bool = True,
) -> dict[str, Any]:
    allowed = tuple(dict.fromkeys(str(status).lower() for status in statuses))
    if not allowed:
        raise RegistryError("at least one recommendation status is required")
    placeholders = ",".join("?" for _ in allowed)
    champions = con.execute(
        "SELECT * FROM champion WHERE active = 1 ORDER BY name COLLATE NOCASE"
    ).fetchall()
    output: list[dict[str, Any]] = []
    for champion in champions:
        recommendations = con.execute(
            f"""
            SELECT * FROM recommendation
            WHERE champion_id = ? AND status IN ({placeholders})
            ORDER BY priority, confidence DESC, title COLLATE NOCASE
            """,
            (int(champion["id"]), *allowed),
        ).fetchall()
        builds: list[dict[str, Any]] = []
        for recommendation in recommendations:
            scopes = [
                row["scope"]
                for row in con.execute(
                    "SELECT scope FROM recommendation_scope WHERE recommendation_id = ? ORDER BY scope",
                    (int(recommendation["id"]),),
                ).fetchall()
            ]
            mastery_rows = con.execute(
                """
                SELECT m.id, m.slug, m.name, m.tree, m.tier, m.position, rm.pick_order
                FROM recommendation_mastery rm
                JOIN mastery m ON m.id = rm.mastery_id
                WHERE rm.recommendation_id = ? ORDER BY rm.pick_order
                """,
                (int(recommendation["id"]),),
            ).fetchall()
            grouped: dict[str, list[dict[str, Any]]] = {"Offense": [], "Defense": [], "Support": []}
            for mastery in mastery_rows:
                grouped[str(mastery["tree"])].append(
                    {
                        "id": int(mastery["id"]),
                        "slug": mastery["slug"],
                        "name": mastery["name"],
                        "tier": int(mastery["tier"]),
                        "position": int(mastery["position"]),
                        "pick_order": int(mastery["pick_order"]),
                    }
                )
            evidence = [
                {
                    "source_key": row["source_key"],
                    "url": row["source_url"],
                    "source_ref": row["source_ref"],
                    "observed_updated_at": row["observed_updated_at"],
                    "content_sha256": row["content_sha256"],
                    "note": row["note"],
                }
                for row in con.execute(
                    """
                    SELECT * FROM recommendation_evidence
                    WHERE recommendation_id = ? ORDER BY id
                    """,
                    (int(recommendation["id"]),),
                ).fetchall()
            ]
            builds.append(
                {
                    "key": recommendation["recommendation_key"],
                    "title": recommendation["title"],
                    "build_type": recommendation["build_type"],
                    "status": recommendation["status"],
                    "confidence": int(recommendation["confidence"]),
                    "priority": int(recommendation["priority"]),
                    "scopes": scopes,
                    "rationale": recommendation["rationale"],
                    "reviewed_by": recommendation["reviewed_by"],
                    "reviewed_at": recommendation["reviewed_at"],
                    "masteries": {key: value for key, value in grouped.items() if value},
                    "evidence": evidence,
                }
            )
        if builds or include_uncovered:
            output.append(
                {
                    "game_id": champion["game_id"],
                    "slug": champion["slug"],
                    "name": champion["name"],
                    "rarity": champion["rarity"],
                    "affinity": champion["affinity"],
                    "faction": champion["faction"],
                    "champion_type": champion["champion_type"],
                    "mastery_builds": builds,
                }
            )
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "included_statuses": list(allowed),
        "coverage": audit(con),
        "champions": output,
    }
