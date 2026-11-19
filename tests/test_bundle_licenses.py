"""Build-time notice coverage, using real temporary distribution trees."""

import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from scripts.bundle_licenses import bundle_licenses, load_fallbacks

ROOT = Path(__file__).resolve().parents[1]
NOTICE = b"Copyright (c) Fixture Authors\nPermission is hereby granted.\n"


def distribution(site, name="example", version="1.0", notices=None):
    directory = site / f"{name}-{version}.dist-info"
    directory.mkdir(parents=True)
    (directory / "METADATA").write_text(
        f"Name: {name}\nVersion: {version}\nLicense: MIT\n"
    )
    for relative, data in (notices or {}).items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return directory


def fallbacks(root, packages=("example",), version="1.0", files=None):
    root.mkdir()
    (root / "README.md").write_text("Fixture source evidence\n")
    entries = {}
    if packages:
        files = files or {"example/LICENSE": NOTICE, "example/NOTICE": NOTICE}
        for relative, data in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        entries["example"] = {
            "distributions": list(packages),
            "version": version,
            "files": {
                path: hashlib.sha256(data).hexdigest() for path, data in files.items()
            },
        }
    (root / "manifest.json").write_text(json.dumps(entries))
    return root


@pytest.mark.parametrize(
    "path", ["LICENSE", "COPYING.txt", "NOTICE", "licenses/MIT.txt"]
)
def test_shipped_material_needs_no_fallback(tmp_path, path):
    site = tmp_path / "site"
    dist = distribution(site, notices={path: NOTICE})
    reports = bundle_licenses(
        [site], fallbacks(tmp_path / "fallbacks", packages=()), tmp_path / "Resources"
    )
    assert reports[0]["distributions"][0]["shipped_notices"] == [path]
    assert reports[0]["distributions"][0]["fallback"] is None
    assert (dist / path).read_bytes() == NOTICE


@pytest.mark.parametrize("material", [None, b"", b" \n\t"])
def test_metadata_and_empty_notice_material_fail(tmp_path, material):
    site = tmp_path / "site"
    dist = distribution(site)
    (dist / "licenses").mkdir()
    if material is not None:
        (dist / "licenses/LICENSE").write_bytes(material)
    resources = tmp_path / "Resources"
    with pytest.raises(ValueError, match="No licence material: example==1.0"):
        bundle_licenses([site], fallbacks(tmp_path / "fallbacks", ()), resources)
    assert not resources.exists()


def test_copies_exact_license_and_notice_for_both_trees(tmp_path):
    sites = [tmp_path / "site-aarch64", tmp_path / "site-x86_64"]
    for site in sites:
        distribution(site, "Example_Package")
        distribution(site, "covered", notices={"licenses/LICENSE": NOTICE})
    source = fallbacks(tmp_path / "fallbacks", ("example-package",))
    resources = tmp_path / "Resources"
    reports = bundle_licenses(sites, source, resources)
    output = resources / "THIRD_PARTY_NOTICES"
    for path in ["example/LICENSE", "example/NOTICE", "manifest.json"]:
        assert (output / path).read_bytes() == (source / path).read_bytes()
    assert not (output / "README.md").exists()  # internal archive links stay in repo
    assert json.loads((output / "index.json").read_text()) == reports
    assert all(len(r["distributions"]) == 2 for r in reports)
    assert all(r["distributions"][0]["fallback"] == "example" for r in reports)
    # Repeated builds must replace stale output, without changing installed metadata.
    (output / "stale.txt").write_text("old")
    bundle_licenses(sites, source, resources)
    assert not (output / "stale.txt").exists()
    assert (sites[0] / "covered-1.0.dist-info/licenses/LICENSE").read_bytes() == NOTICE
    assert not (sites[0] / "Example_Package-1.0.dist-info/LICENSE").exists()


def test_missing_notice_in_second_architecture_stops_the_build(tmp_path):
    arm, intel = tmp_path / "arm", tmp_path / "intel"
    distribution(arm, notices={"LICENSE": NOTICE})
    distribution(intel)
    with pytest.raises(ValueError, match="No licence material.*intel"):
        bundle_licenses(
            [arm, intel], fallbacks(tmp_path / "fallbacks", ()), tmp_path / "Resources"
        )
    assert not (tmp_path / "Resources").exists()


def test_each_dist_info_is_checked_when_pbs_and_runtime_versions_coexist(tmp_path):
    site = tmp_path / "site"
    distribution(site, "pip", "25.1", {"licenses/LICENSE.txt": NOTICE})
    second = distribution(site, "pip", "26.2.2", {"licenses/LICENSE.txt": NOTICE})
    source = fallbacks(tmp_path / "fallbacks", ())
    resources = tmp_path / "Resources"
    reports = bundle_licenses([site], source, resources)
    assert len(reports[0]["distributions"]) == 2
    (second / "licenses/LICENSE.txt").unlink()
    with pytest.raises(ValueError, match="No licence material: pip==26.2.2"):
        bundle_licenses([site], source, resources)


@pytest.mark.parametrize("shipped", [False, True])
def test_version_change_requires_source_review(tmp_path, shipped):
    site = tmp_path / "site"
    distribution(site, version="2.0", notices={"LICENSE": NOTICE} if shipped else {})
    with pytest.raises(ValueError, match="Stale fallback: example==2.0"):
        bundle_licenses(
            [site], fallbacks(tmp_path / "fallbacks"), tmp_path / "Resources"
        )


@pytest.mark.parametrize("change", ["missing", "empty", "changed", "directory"])
def test_invalid_fallback_file_fails_before_output(tmp_path, change):
    site = tmp_path / "site"
    distribution(site)
    source = fallbacks(tmp_path / "fallbacks")
    path = source / "example/LICENSE"
    if change in ("missing", "directory"):
        path.unlink()
        if change == "directory":
            path.mkdir()
    else:
        path.write_bytes(b" \n" if change == "empty" else b"different text")
    with pytest.raises(ValueError, match="fallback|Fallback"):
        bundle_licenses([site], source, tmp_path / "Resources")
    assert not (tmp_path / "Resources").exists()


def test_stale_package_mapping_is_rejected(tmp_path):
    site = tmp_path / "site"
    distribution(site, "replacement", notices={"LICENSE": NOTICE})
    with pytest.raises(ValueError, match="no longer installed.*example"):
        bundle_licenses(
            [site], fallbacks(tmp_path / "fallbacks"), tmp_path / "Resources"
        )


def test_redundant_fallback_is_rejected(tmp_path):
    site = tmp_path / "site"
    distribution(site, notices={"LICENSE": NOTICE})
    with pytest.raises(ValueError, match="Fallbacks no longer needed"):
        bundle_licenses(
            [site], fallbacks(tmp_path / "fallbacks"), tmp_path / "Resources"
        )


def test_empty_site_fails_instead_of_reporting_coverage(tmp_path):
    with pytest.raises(ValueError, match="No distributions found"):
        bundle_licenses(
            [tmp_path / "absent"],
            fallbacks(tmp_path / "fallbacks", ()),
            tmp_path / "Resources",
        )


@pytest.mark.parametrize("directory", [False, True])
def test_legacy_distribution_metadata_cannot_escape_inventory(tmp_path, directory):
    site = tmp_path / "site"
    distribution(site, notices={"LICENSE": NOTICE})
    legacy = site / "legacy-1.0.egg-info"
    if directory:
        legacy.mkdir()
    else:
        legacy.write_text("Name: legacy\nVersion: 1.0\n")
    with pytest.raises(ValueError, match="Unsupported legacy distribution metadata"):
        bundle_licenses(
            [site], fallbacks(tmp_path / "fallbacks", ()), tmp_path / "Resources"
        )
    assert not (tmp_path / "Resources").exists()


def test_external_symlink_is_not_shipped_material(tmp_path):
    site = tmp_path / "site"
    dist = distribution(site)
    (tmp_path / "outside").write_bytes(NOTICE)
    (dist / "LICENSE").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="No licence material"):
        bundle_licenses([site], fallbacks(tmp_path / "fallbacks", ()), tmp_path / "out")


def test_cli_reports_failure_with_nonzero_exit(tmp_path):
    site = tmp_path / "site"
    distribution(site)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/bundle_licenses.py"),
            "--site",
            str(site),
            "--fallbacks",
            str(fallbacks(tmp_path / "fallbacks", ())),
            "--resources",
            str(tmp_path / "Resources"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "LICENCE CHECK FAILED: No licence material: example==1.0" in result.stderr


def test_build_gates_actual_trees_before_signing():
    source = (ROOT / "scripts/build_app.sh").read_text()
    check = source.index('"$REPO/scripts/bundle_licenses.py"')
    assert source.index('"$WORK"/wheel/*.whl') < check
    assert check < source.index('if [[ -n "$SIGN" ]]')
    command = source[check : source.index("\n# Build stamp", check)]
    assert (
        '--site "$WORK/site-aarch64" --site "$WORK/site-x86_64" --site "$SITE"'
        in command
    )
    assert '--resources "$APP/Contents/Resources"' in command


def test_repository_fallbacks_have_exact_bytes_and_current_locked_versions():
    manifest, packages = load_fallbacks(ROOT / "packaging/licenses")
    locked = {
        package["name"]: package["version"]
        for package in tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    }
    for name, group in packages.items():
        assert locked[name] == manifest[group]["version"]
