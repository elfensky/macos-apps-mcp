"""Check installed distribution notices and copy pinned fallbacks before signing.

No package imports or network access: the installed dist-info trees are the evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from email.parser import BytesParser
from pathlib import Path


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def nonempty_file(path: Path, root: Path) -> bool:
    return (
        path.is_file()
        and path.resolve().is_relative_to(root.resolve())
        and bool(path.read_bytes().strip())
    )


def shipped_notices(dist_info: Path) -> list[str]:
    """An empty licenses/ directory or metadata licence name is not a notice."""
    return sorted(
        str(path.relative_to(dist_info))
        for path in dist_info.rglob("*")
        if (
            path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE"))
            or "licenses" in [p.lower() for p in path.relative_to(dist_info).parts[:-1]]
        )
        and nonempty_file(path, dist_info)
    )


def load_fallbacks(root: Path) -> tuple[dict, dict]:
    manifest = json.loads((root / "manifest.json").read_text())
    packages = {}
    for group, entry in manifest.items():
        if not entry["version"] or not entry["files"] or not entry["distributions"]:
            raise ValueError(f"Incomplete fallback: {group}")
        for relative, digest in entry["files"].items():
            path = root / relative
            if Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise ValueError(f"Invalid fallback path: {relative}")
            if not nonempty_file(path, root):
                raise ValueError(f"Missing or empty fallback: {relative}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Fallback SHA256 mismatch: {relative}")
        for name in entry["distributions"]:
            if name != canonical_name(name) or name in packages:
                raise ValueError(f"Noncanonical or duplicate fallback name: {name}")
            packages[name] = group
    return manifest, packages


def inspect_site(site: Path, manifest: dict, packages: dict) -> tuple[list, set]:
    distributions = sorted(site.glob("*.dist-info"))
    if not distributions:
        raise ValueError(f"No distributions found: {site}")
    records, seen = [], set()
    for dist_info in distributions:
        metadata = BytesParser().parsebytes((dist_info / "METADATA").read_bytes())
        name, version = metadata.get("Name"), metadata.get("Version")
        if not name or not version:
            raise ValueError(f"Missing Name or Version: {dist_info}")
        name = canonical_name(name)
        seen.add(name)
        group = packages.get(name)
        if group and version != manifest[group]["version"]:
            raise ValueError(f"Stale fallback: {name}=={version}; review {group}")
        notices = shipped_notices(dist_info)
        if not notices and not group:
            raise ValueError(f"No licence material: {name}=={version} in {site}")
        records.append(
            {
                "name": name,
                "version": version,
                "dist_info": dist_info.name,
                "shipped_notices": notices,
                "fallback": group if not notices else None,
            }
        )
    return records, seen


def bundle_licenses(sites: list[Path], fallbacks: Path, resources: Path) -> list:
    manifest, packages = load_fallbacks(fallbacks)
    reports, seen, used = [], set(), set()
    for site in sites:
        records, installed = inspect_site(site, manifest, packages)
        reports.append({"site": site.name, "distributions": records})
        seen.update(installed)
        used.update(r["fallback"] for r in records if r["fallback"])
    if absent := packages.keys() - seen:
        raise ValueError(
            f"Fallback distributions no longer installed: {sorted(absent)}"
        )
    if redundant := manifest.keys() - used:
        raise ValueError(f"Fallbacks no longer needed: {sorted(redundant)}")

    # Validate all trees first. Never let a previous output satisfy a missing notice.
    destination = resources / "THIRD_PARTY_NOTICES"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for group in sorted(used):
        for relative in manifest[group]["files"]:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fallbacks / relative, target)
    shutil.copyfile(fallbacks / "manifest.json", destination / "manifest.json")
    shutil.copyfile(fallbacks / "README.md", destination / "README.md")
    (destination / "index.json").write_text(json.dumps(reports, indent=2) + "\n")
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, action="append", required=True)
    parser.add_argument("--fallbacks", type=Path, required=True)
    parser.add_argument("--resources", type=Path, required=True)
    args = parser.parse_args()
    try:
        reports = bundle_licenses(args.site, args.fallbacks, args.resources)
    except (OSError, ValueError, KeyError, TypeError) as error:
        sys.exit(f"LICENCE CHECK FAILED: {error}")
    for report in reports:
        records = report["distributions"]
        count = sum(bool(r["fallback"]) for r in records)
        print(
            f"licences ok: {report['site']}: "
            f"{len(records)} distributions, {count} fallbacks"
        )


if __name__ == "__main__":
    main()
