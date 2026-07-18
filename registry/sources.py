from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .db import RegistryError, content_hash, utc_now

RAID_CODEX_REPOSITORY = "raid-codex/data"
RAID_CODEX_DEFAULT_REF = "b2c3c6a4ac0375cc5bec3c582caf3212a775d83b"
RAID_CODEX_DIRECTORY = "docs/champions/current"


def _request(url: str, *, token: str | None = None) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "cuedown-raid-champion-registry/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        raise RegistryError(f"GitHub returned HTTP {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RegistryError(f"could not reach GitHub for {url}: {exc.reason}") from exc


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def sync_raid_codex(
    destination: str | Path,
    *,
    ref: str = RAID_CODEX_DEFAULT_REF,
    github_token: str | None = None,
) -> dict[str, Any]:
    """Download the final MIT-licensed Raid Codex snapshot from a pinned commit.

    This is intentionally a GitHub repository adapter, not a website scraper.
    Imported recommendations are always marked historical and are never eligible
    for publication until a Reliquary editor creates and approves a current build.
    """

    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    token = github_token or os.environ.get("GITHUB_TOKEN")
    query = urllib.parse.urlencode({"ref": ref})
    api_url = (
        f"https://api.github.com/repos/{RAID_CODEX_REPOSITORY}/contents/"
        f"{RAID_CODEX_DIRECTORY}?{query}"
    )
    listing = json.loads(_request(api_url, token=token))
    if not isinstance(listing, list):
        raise RegistryError("unexpected GitHub directory response for Raid Codex")
    entries = sorted(
        (
            item
            for item in listing
            if isinstance(item, dict)
            and item.get("type") == "file"
            and str(item.get("name", "")).endswith(".json")
        ),
        key=lambda item: str(item["name"]),
    )
    if not entries:
        raise RegistryError("the pinned Raid Codex directory contained no champion JSON files")

    manifest_files: list[dict[str, Any]] = []
    for item in entries:
        name = str(item["name"])
        raw_url = (
            f"https://raw.githubusercontent.com/{RAID_CODEX_REPOSITORY}/"
            f"{urllib.parse.quote(ref, safe='')}/{RAID_CODEX_DIRECTORY}/"
            f"{urllib.parse.quote(name)}"
        )
        raw = _request(raw_url, token=token)
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RegistryError(f"Raid Codex file is not valid JSON: {name}") from exc
        _atomic_write(target / name, raw)
        manifest_files.append(
            {
                "name": name,
                "sha256": content_hash(raw),
                "github_blob_sha": item.get("sha"),
                "bytes": len(raw),
            }
        )

    license_url = (
        f"https://raw.githubusercontent.com/{RAID_CODEX_REPOSITORY}/"
        f"{urllib.parse.quote(ref, safe='')}/LICENSE"
    )
    license_bytes = _request(license_url, token=token)
    _atomic_write(target / "UPSTREAM_LICENSE", license_bytes)
    manifest = {
        "schema_version": 1,
        "repository": RAID_CODEX_REPOSITORY,
        "source_ref": ref,
        "source_directory": RAID_CODEX_DIRECTORY,
        "retrieved_at": utc_now(),
        "license": "MIT",
        "historical_only": True,
        "files": manifest_files,
    }
    _atomic_write(
        target / "manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return {
        "destination": str(target),
        "source_ref": ref,
        "files": len(manifest_files),
        "bytes": sum(int(item["bytes"]) for item in manifest_files),
    }
