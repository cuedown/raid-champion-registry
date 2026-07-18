# Source policy

## The important distinction

The champion catalog and mastery catalog are factual game data. A mastery
*recommendation* is an editorial conclusion that depends on champion kit,
content, team, gear, speed tune, and account stage. The database never treats
one external guide as an unquestionable universal build.

## Authority ladder

| Layer | Preferred source | Automated | Publication status |
|---|---|---:|---|
| Champion identity | Current operator-owned client/static export | Import only | Canonical facts |
| Mastery IDs/names | Current client export, cross-checked with MIT Raid Toolkit mapping | Yes when supplied | Canonical facts |
| Historical candidate | Pinned MIT Raid Codex repository snapshot | Yes | `historical` |
| Common user path | Explicitly opt-in, anonymous account exports | Local import | `draft` candidate |
| Current recommendation | Reliquary editor using current evidence | No | `draft` then `approved` |
| HellHades/AyumiLove | Link and manually evaluated evidence | No | Evidence only |

## HellHades

As checked on 2026-07-18, the HellHades terms list spidering, crawling, and
scraping among prohibited uses. The registry therefore includes no HTML
scraper, browser automation, sitemap crawler, or hidden API client for
HellHades.

Permitted implementation paths are:

1. receive written data-reuse and automated-access permission;
2. obtain a documented licensed API/feed;
3. link to a guide as evidence while Reliquary authors its own compact mastery
   selection after review.

This is a product-risk boundary, not a claim of legal advice.

## Raid Codex

`raid-codex/data` is MIT licensed, but its final commit is from 2021. The
adapter pins commit `b2c3c6a4ac0375cc5bec3c582caf3212a775d83b`, saves the
upstream license and per-file hashes, and assigns a low confidence. It cannot
produce an `approved` record.

## Freshness and changes

Each source has a `max_age_days` policy. A future release gate should require:

- the current champion export has been refreshed after the latest RAID patch;
- newly seen champion IDs have at least a review-pending UI state;
- removed/renamed IDs are reconciled rather than silently duplicated;
- approved recommendations older than their policy are re-reviewed;
- any mastery ID/tree change blocks the build until reconciled.

## Privacy

Observation imports are local and require explicit `--consent`. The schema has
no columns for account ID, player name, device ID, email, IP address, or login
credentials. If observations are later uploaded to a service, implement a
separate explicit opt-in flow, retention policy, abuse protection, and privacy
review before enabling it.
