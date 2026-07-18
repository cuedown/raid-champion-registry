from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .db import (
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
from .sources import RAID_CODEX_DEFAULT_REF, sync_raid_codex


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def add_db_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=Path("build/registry.sqlite"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="raid-registry",
        description="Build and audit the provenance-first RAID mastery registry.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create the SQLite schema and seed the 66 mastery nodes")
    add_db_argument(init)

    champions = sub.add_parser("import-champions", help="Import a current champion catalog/export")
    add_db_argument(champions)
    champions.add_argument("path", type=Path)
    champions.add_argument("--source-key", default="game-export")
    champions.add_argument("--source-ref")
    champions.add_argument("--source-url")

    recommendations = sub.add_parser(
        "import-recommendations", help="Import reviewed or draft editorial recommendation JSON"
    )
    add_db_argument(recommendations)
    recommendations.add_argument("path", type=Path)
    recommendations.add_argument("--source-key", default="manual-editorial")
    recommendations.add_argument("--source-ref")
    recommendations.add_argument("--source-url")

    sync = sub.add_parser(
        "sync-raid-codex",
        help="Download the pinned, MIT-licensed 2021 Raid Codex snapshot (historical only)",
    )
    sync.add_argument("destination", type=Path)
    sync.add_argument("--ref", default=RAID_CODEX_DEFAULT_REF)

    codex = sub.add_parser(
        "import-raid-codex", help="Import a downloaded Raid Codex directory as historical evidence"
    )
    add_db_argument(codex)
    codex.add_argument("directory", type=Path)
    codex.add_argument("--ref", default=RAID_CODEX_DEFAULT_REF)

    observe = sub.add_parser(
        "observe", help="Aggregate mastery fingerprints from an opt-in account export"
    )
    add_db_argument(observe)
    observe.add_argument("path", type=Path)
    observe.add_argument("--source-ref")
    observe.add_argument(
        "--consent",
        action="store_true",
        help="Confirm the export is authorized for local anonymous aggregation",
    )

    promote = sub.add_parser(
        "promote-observations", help="Create draft candidates from the most common full observed builds"
    )
    add_db_argument(promote)
    promote.add_argument("--min-samples", type=int, default=5)

    audit_parser = sub.add_parser("audit", help="Report coverage, issues, and recommendation status")
    add_db_argument(audit_parser)

    validate = sub.add_parser("validate", help="Run structural and mastery-path checks")
    add_db_argument(validate)
    validate.add_argument("--require-complete", action="store_true")

    export = sub.add_parser("export", help="Export an app-consumable JSON registry")
    add_db_argument(export)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument(
        "--status", action="append", choices=("approved", "draft", "historical", "rejected")
    )
    export.add_argument("--covered-only", action="store_true")

    build = sub.add_parser("build", help="Rebuild a database from current inputs")
    add_db_argument(build)
    build.add_argument("--champions", type=Path)
    build.add_argument("--recommendations-dir", type=Path, default=Path("data/curated"))
    build.add_argument("--raid-codex-dir", type=Path)
    build.add_argument("--output", type=Path)
    build.add_argument("--require-complete", action="store_true")
    return parser


def ensure_initialized(db: Path) -> None:
    if not db.exists():
        initialize_database(db)


def run(args: argparse.Namespace) -> int:
    if args.command == "init":
        emit({"database": str(args.db), **initialize_database(args.db)})
        return 0
    if args.command == "sync-raid-codex":
        emit(sync_raid_codex(args.destination, ref=args.ref))
        return 0

    ensure_initialized(args.db)
    con = connect(args.db)
    try:
        if args.command == "import-champions":
            emit(
                import_champions(
                    con,
                    args.path,
                    source_key=args.source_key,
                    source_ref=args.source_ref,
                    source_url=args.source_url,
                )
            )
        elif args.command == "import-recommendations":
            emit(
                import_recommendations(
                    con,
                    args.path,
                    source_key=args.source_key,
                    source_ref=args.source_ref,
                    source_url=args.source_url,
                )
            )
        elif args.command == "import-raid-codex":
            emit(import_raid_codex_directory(con, args.directory, source_ref=args.ref))
        elif args.command == "observe":
            if not args.consent:
                raise RegistryError(
                    "observation import requires --consent; the registry will retain only champion/build fingerprints"
                )
            emit(import_observations(con, args.path, source_ref=args.source_ref))
        elif args.command == "promote-observations":
            emit(promote_observations(con, min_samples=args.min_samples))
        elif args.command == "audit":
            emit(audit(con))
        elif args.command == "validate":
            result = validate_database(con, require_complete=args.require_complete)
            emit(result)
            return 0 if result["valid"] else 1
        elif args.command == "export":
            statuses = args.status or ["approved"]
            payload = export_registry(
                con, statuses=statuses, include_uncovered=not args.covered_only
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            emit({"output": str(args.output), "champions": len(payload["champions"]), "statuses": statuses})
        elif args.command == "build":
            con.close()
            if args.db.exists():
                args.db.unlink()
            initialize_database(args.db)
            con = connect(args.db)
            results: dict[str, Any] = {"database": str(args.db)}
            if args.champions:
                results["champions"] = import_champions(con, args.champions)
            if args.raid_codex_dir:
                results["raid_codex"] = import_raid_codex_directory(con, args.raid_codex_dir)
            if args.recommendations_dir.exists():
                imported = 0
                for path in sorted(args.recommendations_dir.glob("*.json")):
                    imported += import_recommendations(con, path)["recommendations"]
                results["curated_recommendations"] = imported
            results["validation"] = validate_database(con, require_complete=args.require_complete)
            if args.output:
                payload = export_registry(con)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                results["output"] = str(args.output)
            emit(results)
            return 0 if results["validation"]["valid"] else 1
        else:
            raise RegistryError(f"unhandled command: {args.command}")
        return 0
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
