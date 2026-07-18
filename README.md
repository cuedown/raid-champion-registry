# RAID Champion Mastery Registry

A provenance-first SQLite registry for champion identities, mastery nodes, and
content-specific mastery recommendations. The default app export contains only
human-reviewed, structurally valid `approved` builds.

> **Repository reset:** the original JSON files are fabricated/placeholder
> data (for example, `The Dread Wolf`, `Rare Champion 1`, invalid affinities,
> and invalid mastery tiers). They are quarantined as legacy material and are
> never read by this implementation. Do not ship them in an application.

## What this solves

- One normalized SQL database contains every champion; each champion can have
  several builds for different content such as Arena, Demon Lord, Hydra, or
  campaign farming.
- Every imported fact has a source snapshot, retrieval time, parser version,
  and SHA-256 content hash.
- `approved` builds must have exactly 15 picks, a valid 10/5 two-tree split,
  no more than one Tier 6 mastery, evidence, a reviewer, and a review date.
- Historical and observed/popular builds are retained for research but are not
  silently presented as truth.
- The application receives deterministic JSON or can query the SQLite database
  directly.

## Source strategy

There is no official Plarium feed of recommended champion mastery builds.
Plarium documents the mastery system, while champion-specific choices are
editorial judgments that differ by role and content.

The registry therefore keeps these layers separate:

1. **Current client/game export:** canonical champion identity and any current
   mastery IDs. This should come from the standalone exporter used by Reliquary.
2. **Raid Toolkit:** MIT-licensed mapping for the 66 mastery IDs and names.
3. **Raid Codex:** optional MIT-licensed 2021 bootstrap. It is imported only as
   `historical`, never as current or approved.
4. **Opt-in observations:** anonymized mastery fingerprints from account
   exports can identify common full builds. Popularity creates a `draft`, not
   an approval.
5. **Reliquary editorial review:** current, content-specific builds with links
   to evidence become the source the app publishes.

HellHades is **reference-only**. Its current terms expressly prohibit
spidering, crawling, and scraping, so this project does not include a
HellHades downloader. Add an automated adapter only after written permission
or an official licensed API is documented.

See [Source policy](docs/SOURCE_POLICY.md) and
[Editorial workflow](docs/EDITORIAL_WORKFLOW.md).

## Quick start

Requires Python 3.11+ and no third-party runtime dependencies.

```bash
python -m registry init --db build/registry.sqlite
python -m registry import-champions --db build/registry.sqlite path/to/current-champions.json
python -m registry import-recommendations --db build/registry.sqlite data/curated/kael.json
python -m registry validate --db build/registry.sqlite
python -m registry export --db build/registry.sqlite --output build/masteries.json
```

The export command includes only `approved` recommendations by default. For an
editorial preview, add `--status draft`; for audit work, add
`--status historical` as another repeated option.

Install the console command if preferred:

```bash
python -m pip install -e .
raid-registry audit --db build/registry.sqlite
```

## Import a current champion catalog

The importer accepts JSON, CSV, and common account-export wrappers such as
`champions`, `heroes`, `data.champions`, `static.champions`, and
`account.champions`. A minimal canonical record is:

```json
{
  "game_id": 1510,
  "name": "Kael",
  "rarity": "Rare",
  "affinity": "Magic",
  "faction": "Dark Elves",
  "champion_type": "Attack"
}
```

Use a champion template/type ID, not an owned-instance ID. The importer rejects
unknown rarities, affinities, champion types, conflicting IDs, and nameless
rows. Invalid records are recorded in `import_issue`.

## Optional historical bootstrap

Raid Codex stopped updating in May 2021, but its final dataset is useful for
locating older candidates and is MIT licensed.

```bash
python -m registry sync-raid-codex cache/raid-codex
python -m registry import-raid-codex --db build/registry.sqlite cache/raid-codex
```

The downloader uses a pinned GitHub commit and verifies every JSON file before
writing a manifest of hashes. It does not scrape raid-codex.com or another
guide website.

## Build coverage from opt-in exports

The observation importer deliberately stores no player name, account ID,
device ID, email, or credentials. It retains only champion ID, mastery IDs, a
fingerprint, count, and timestamps.

```bash
python -m registry observe --consent --db build/registry.sqlite path/to/account-export.json
python -m registry promote-observations --min-samples 10 --db build/registry.sqlite
```

Promotion creates a `draft` for the most common valid full path per champion.
An editor must still determine its correct game-mode scope and approve it.

## Reproducible rebuild

```bash
python -m registry build \
  --db build/registry.sqlite \
  --champions path/to/current-champions.json \
  --recommendations-dir data/curated \
  --output build/masteries.json
```

Use `--require-complete` only when every active champion is expected to have at
least one approved build. This makes incomplete application releases fail CI.

## Tests

```bash
python -m unittest discover -s tests -v
```

The GitHub workflow runs the tests and validates the canonical 66-node mastery
catalog on every push and pull request.

## Application contract

Use `build/masteries.json` as the stable read model. Each champion contains
zero or more `mastery_builds`; each build includes scopes, confidence, review
metadata, masteries grouped by tree, and evidence. Champions with no approved
build remain present with an empty array, allowing the UI to show “review
pending” instead of inventing a recommendation.

The normalized SQL tables remain the write/audit model. The most relevant
views are:

- `v_published_mastery_builds`: flat, approved app rows;
- `v_champion_coverage`: approved/draft/historical counts per champion.

## License

Project code is MIT. See [Third-party notices](THIRD_PARTY_NOTICES.md) for the
mastery ID mapping and optional historical adapter.
