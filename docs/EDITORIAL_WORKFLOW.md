# Editorial workflow

## 1. Refresh canonical champions

Export the current champion template catalog from the Reliquary desktop/game
data pipeline and import it with `import-champions`. Do this after patches and
before authoring builds for newly released champions.

## 2. Create candidates

Candidates can come from:

- a historical Raid Codex path;
- the most common valid opt-in observation;
- a human researcher reading current guides and the champion kit;
- an existing Reliquary build that needs a patch review.

All candidates begin as `draft` or `historical`.

## 3. Scope the build

Do not label a build “best” without content. At minimum distinguish where it
changes the Tier 6 choice or path:

- Demon Lord/boss damage;
- general PvE/dungeons;
- wave control/support;
- campaign farming;
- Arena offense/defense;
- Hydra/Chimera or a speed-tuned composition.

If a mastery can break a speed tune or activate an unwanted counterattack/turn
meter effect, state that in `rationale` and create a separate build.

## 4. Enter evidence

Evidence records contain a source policy key, direct URL, source ref/date when
known, hash when available, and a short note about what was verified. Do not
copy long guide text or images into the registry.

## 5. Review and approve

An approved build requires:

- a champion match from the canonical catalog;
- 15 unique mastery nodes;
- exactly two trees with a 10/5 split;
- a valid tier distribution and a single Tier 6 choice;
- current evidence;
- `reviewed_by` and an ISO-8601 `reviewed_at` timestamp;
- champion- and content-specific rationale.

Set `status` to `approved` only after this review. Run:

```bash
python -m registry validate --db build/registry.sqlite
python -m registry audit --db build/registry.sqlite
```

## 6. Release gate

Before the app publishes a registry update, run validation with full coverage:

```bash
python -m registry validate --require-complete --db build/registry.sqlite
python -m registry export --db build/registry.sqlite --output build/masteries.json
```

If a champion is not reviewed, keep the empty build array and display “review
pending.” Never fall back to a generic template disguised as champion-specific
truth.
