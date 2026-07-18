PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS registry_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_policy (
    source_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    homepage TEXT NOT NULL,
    terms_url TEXT,
    license_id TEXT,
    source_kind TEXT NOT NULL CHECK (source_kind IN (
        'game_export', 'licensed_dataset', 'manual_editorial',
        'community_observation', 'reference_only'
    )),
    automated_fetch_allowed INTEGER NOT NULL DEFAULT 0 CHECK (automated_fetch_allowed IN (0, 1)),
    authority_level INTEGER NOT NULL DEFAULT 0 CHECK (authority_level BETWEEN 0 AND 100),
    max_age_days INTEGER CHECK (max_age_days IS NULL OR max_age_days >= 0),
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS source_snapshot (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL REFERENCES source_policy(source_key),
    source_ref TEXT NOT NULL,
    source_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    observed_updated_at TEXT,
    content_sha256 TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    raw_path TEXT,
    UNIQUE (source_key, source_ref, content_sha256)
);

CREATE TABLE IF NOT EXISTS champion (
    id INTEGER PRIMARY KEY,
    game_id INTEGER UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    rarity TEXT CHECK (rarity IS NULL OR rarity IN (
        'Mythical', 'Legendary', 'Epic', 'Rare', 'Uncommon', 'Common'
    )),
    affinity TEXT CHECK (affinity IS NULL OR affinity IN ('Magic', 'Force', 'Spirit', 'Void')),
    faction TEXT,
    champion_type TEXT CHECK (champion_type IS NULL OR champion_type IN ('Attack', 'Defense', 'HP', 'Support')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    source_snapshot_id INTEGER NOT NULL REFERENCES source_snapshot(id)
);

CREATE TABLE IF NOT EXISTS champion_alias (
    champion_id INTEGER NOT NULL REFERENCES champion(id) ON DELETE CASCADE,
    alias TEXT NOT NULL COLLATE NOCASE,
    alias_kind TEXT NOT NULL DEFAULT 'name',
    PRIMARY KEY (champion_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_champion_name ON champion(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_champion_game_id ON champion(game_id);

CREATE TABLE IF NOT EXISTS mastery (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    tree TEXT NOT NULL CHECK (tree IN ('Offense', 'Defense', 'Support')),
    tier INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 6),
    position INTEGER NOT NULL CHECK (position BETWEEN 1 AND 4),
    source_url TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    UNIQUE (tree, tier, position)
);

CREATE TABLE IF NOT EXISTS recommendation (
    id INTEGER PRIMARY KEY,
    recommendation_key TEXT NOT NULL UNIQUE,
    champion_id INTEGER NOT NULL REFERENCES champion(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    build_type TEXT NOT NULL DEFAULT 'general',
    status TEXT NOT NULL CHECK (status IN ('draft', 'historical', 'approved', 'rejected')),
    confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    priority INTEGER NOT NULL DEFAULT 100,
    rationale TEXT NOT NULL DEFAULT '',
    authored_by TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT,
    source_snapshot_id INTEGER NOT NULL REFERENCES source_snapshot(id),
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS recommendation_scope (
    recommendation_id INTEGER NOT NULL REFERENCES recommendation(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    PRIMARY KEY (recommendation_id, scope)
);

CREATE TABLE IF NOT EXISTS recommendation_mastery (
    recommendation_id INTEGER NOT NULL REFERENCES recommendation(id) ON DELETE CASCADE,
    mastery_id INTEGER NOT NULL REFERENCES mastery(id),
    pick_order INTEGER NOT NULL CHECK (pick_order BETWEEN 1 AND 15),
    PRIMARY KEY (recommendation_id, mastery_id),
    UNIQUE (recommendation_id, pick_order)
);

CREATE TABLE IF NOT EXISTS recommendation_evidence (
    id INTEGER PRIMARY KEY,
    recommendation_id INTEGER NOT NULL REFERENCES recommendation(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL REFERENCES source_policy(source_key),
    source_url TEXT NOT NULL,
    source_ref TEXT,
    observed_updated_at TEXT,
    content_sha256 TEXT,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_issue (
    id INTEGER PRIMARY KEY,
    source_snapshot_id INTEGER REFERENCES source_snapshot(id) ON DELETE CASCADE,
    severity TEXT NOT NULL CHECK (severity IN ('warning', 'error')),
    entity_key TEXT,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observed_build (
    id INTEGER PRIMARY KEY,
    champion_id INTEGER NOT NULL REFERENCES champion(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 1 CHECK (sample_count > 0),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    source_snapshot_id INTEGER NOT NULL REFERENCES source_snapshot(id),
    UNIQUE (champion_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS observed_build_mastery (
    observed_build_id INTEGER NOT NULL REFERENCES observed_build(id) ON DELETE CASCADE,
    mastery_id INTEGER NOT NULL REFERENCES mastery(id),
    PRIMARY KEY (observed_build_id, mastery_id)
);

CREATE TRIGGER IF NOT EXISTS trg_recommendation_mastery_two_trees
AFTER INSERT ON recommendation_mastery
BEGIN
    SELECT CASE WHEN (
        SELECT COUNT(DISTINCT m.tree)
        FROM recommendation_mastery rm
        JOIN mastery m ON m.id = rm.mastery_id
        WHERE rm.recommendation_id = NEW.recommendation_id
    ) > 2 THEN RAISE(ABORT, 'a mastery build may use at most two trees') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_recommendation_mastery_one_tier_six
AFTER INSERT ON recommendation_mastery
BEGIN
    SELECT CASE WHEN (
        SELECT COUNT(*)
        FROM recommendation_mastery rm
        JOIN mastery m ON m.id = rm.mastery_id
        WHERE rm.recommendation_id = NEW.recommendation_id AND m.tier = 6
    ) > 1 THEN RAISE(ABORT, 'a mastery build may use at most one tier-6 mastery') END;
END;

CREATE VIEW IF NOT EXISTS v_published_mastery_builds AS
SELECT
    c.game_id,
    c.slug AS champion_slug,
    c.name AS champion_name,
    r.recommendation_key,
    r.title,
    r.build_type,
    r.confidence,
    r.priority,
    r.reviewed_by,
    r.reviewed_at,
    rs.scope,
    rm.pick_order,
    m.id AS mastery_id,
    m.slug AS mastery_slug,
    m.name AS mastery_name,
    m.tree,
    m.tier,
    m.position
FROM recommendation r
JOIN champion c ON c.id = r.champion_id
JOIN recommendation_scope rs ON rs.recommendation_id = r.id
JOIN recommendation_mastery rm ON rm.recommendation_id = r.id
JOIN mastery m ON m.id = rm.mastery_id
WHERE r.status = 'approved' AND c.active = 1;

CREATE VIEW IF NOT EXISTS v_champion_coverage AS
SELECT
    c.id AS champion_id,
    c.game_id,
    c.slug,
    c.name,
    COUNT(DISTINCT CASE WHEN r.status = 'approved' THEN r.id END) AS approved_builds,
    COUNT(DISTINCT CASE WHEN r.status = 'draft' THEN r.id END) AS draft_builds,
    COUNT(DISTINCT CASE WHEN r.status = 'historical' THEN r.id END) AS historical_builds,
    COALESCE(MAX(ob.sample_count), 0) AS largest_observed_sample
FROM champion c
LEFT JOIN recommendation r ON r.champion_id = c.id
LEFT JOIN observed_build ob ON ob.champion_id = c.id
WHERE c.active = 1
GROUP BY c.id;
