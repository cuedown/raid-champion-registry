from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from registry.db import (
    RegistryError,
    audit,
    connect,
    export_registry,
    import_champions,
    import_observations,
    import_raid_codex_directory,
    import_recommendations,
    initialize_database,
    promote_observations,
    validate_database,
)


KAEL_MASTERIES = [
    500113,
    500121,
    500122,
    500131,
    500132,
    500141,
    500143,
    500151,
    500152,
    500161,
    500313,
    500324,
    500333,
    500343,
    500354,
]


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db = self.root / "registry.sqlite"
        initialize_database(self.db)
        self.con = connect(self.db)

    def tearDown(self) -> None:
        self.con.close()
        self.temporary.cleanup()

    def write_json(self, name: str, value: object) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def import_kael(self) -> None:
        path = self.write_json(
            "champions.json",
            {
                "champions": [
                    {
                        "game_id": 1510,
                        "name": "Kael",
                        "rarity": "Rare",
                        "affinity": "Magic",
                        "faction": "Dark Elves",
                        "champion_type": "Attack",
                    }
                ]
            },
        )
        result = import_champions(self.con, path, source_ref="test-fixture")
        self.assertEqual(result["champions"], 1)

    def test_init_seeds_exact_mastery_catalog(self) -> None:
        result = audit(self.con)
        self.assertEqual(result["mastery_nodes"], 66)
        self.assertEqual(result["champions"], 0)

    def test_approved_build_round_trips_to_app_export(self) -> None:
        self.import_kael()
        path = self.write_json(
            "kael.json",
            {
                "champion": {"game_id": 1510},
                "builds": [
                    {
                        "key": "kael:pve-general",
                        "title": "PvE general",
                        "status": "approved",
                        "confidence": 90,
                        "scopes": ["campaign", "dragon", "demon-lord"],
                        "masteries": KAEL_MASTERIES,
                        "authored_by": "test-editor",
                        "reviewed_by": "test-reviewer",
                        "reviewed_at": "2026-07-18T00:00:00Z",
                        "evidence": [
                            {
                                "source_key": "manual-editorial",
                                "url": "https://example.invalid/editorial/kael",
                                "note": "Test fixture only",
                            }
                        ],
                    }
                ],
            },
        )
        result = import_recommendations(self.con, path, source_ref="test-review")
        self.assertEqual(result["recommendations"], 1)
        validation = validate_database(self.con, require_complete=True)
        self.assertTrue(validation["valid"], validation["failures"])
        exported = export_registry(self.con)
        self.assertEqual(len(exported["champions"]), 1)
        build = exported["champions"][0]["mastery_builds"][0]
        self.assertEqual(build["key"], "kael:pve-general")
        self.assertEqual(
            sum(len(nodes) for nodes in build["masteries"].values()),
            15,
        )

    def test_approved_build_rejects_partial_or_unreviewed_path(self) -> None:
        self.import_kael()
        path = self.write_json(
            "bad.json",
            {
                "champion": "Kael",
                "builds": [
                    {
                        "title": "Invalid",
                        "status": "approved",
                        "masteries": KAEL_MASTERIES[:-1],
                        "reviewed_by": "reviewer",
                        "reviewed_at": "2026-07-18T00:00:00Z",
                        "evidence": ["https://example.invalid"],
                    }
                ],
            },
        )
        with self.assertRaisesRegex(RegistryError, "exactly 15"):
            import_recommendations(self.con, path)
        count = self.con.execute("SELECT COUNT(*) FROM recommendation").fetchone()[0]
        self.assertEqual(count, 0)

    def test_observations_are_aggregated_without_identity_fields(self) -> None:
        self.import_kael()
        observation = {
            "account_id": "must-not-be-stored",
            "player_name": "must-not-be-stored",
            "champions": [
                {
                    "game_id": 1510,
                    "name": "Kael",
                    "mastery_ids": KAEL_MASTERIES,
                }
            ],
        }
        first = self.write_json("observation-1.json", observation)
        second = self.write_json("observation-2.json", observation)
        import_observations(self.con, first)
        import_observations(self.con, second)
        row = self.con.execute("SELECT * FROM observed_build").fetchone()
        self.assertEqual(row["sample_count"], 2)
        schema_columns = {
            item[1] for item in self.con.execute("PRAGMA table_info(observed_build)").fetchall()
        }
        self.assertFalse({"account_id", "player_name", "device_id"} & schema_columns)
        promoted = promote_observations(self.con, min_samples=2)
        self.assertEqual(promoted["promoted"], 1)
        status = self.con.execute("SELECT status FROM recommendation").fetchone()[0]
        self.assertEqual(status, "draft")

    def test_raid_codex_import_is_historical_never_approved(self) -> None:
        codex = self.root / "codex"
        codex.mkdir()
        (codex / "kael.json").write_text(
            json.dumps(
                {
                    "name": "Kael",
                    "giid": "1510",
                    "slug": "kael",
                    "rarity": "Rare",
                    "element": "Magic",
                    "type": "Attack",
                    "faction_slug": "dark-elves",
                    "masteries": [
                        {
                            "author": "archive",
                            "from": "historical-source",
                            "locations": ["clan-boss", "dungeon"],
                            "offense": [
                                "deadly-precision",
                                "heart-of-glory",
                                "keen-strike",
                                "single-out",
                                "life-drinker",
                                "bring-it-down",
                                "cycle-of-violence",
                                "methodical",
                                "kill-streak",
                                "warmaster",
                            ],
                            "defense": [],
                            "support": [
                                "pinpoint-accuracy",
                                "charged-focus",
                                "swarm-smiter",
                                "lore-of-steel",
                                "master-hexer",
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = import_raid_codex_directory(self.con, codex, source_ref="test-codex-ref")
        self.assertEqual(result["champions"], 1)
        self.assertEqual(result["recommendations"], 1)
        row = self.con.execute("SELECT status, confidence FROM recommendation").fetchone()
        self.assertEqual(row["status"], "historical")
        self.assertLess(row["confidence"], 50)
        self.assertEqual(export_registry(self.con)["champions"][0]["mastery_builds"], [])


if __name__ == "__main__":
    unittest.main()
