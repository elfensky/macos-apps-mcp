"""The shared write-to-disk module (``macos_apps_mcp.files``): Mail today, Photos next.

A name from outside is attacker-controlled: an attachment NAME arrives in inbound mail
from anyone (#81 save, #85 export), a photo's original filename from whoever shared it.
Turning either into a FILESYSTEM PATH is the risk. These tests come first and they are
the point of the module — the lazy version of this code is the wrong version.

The rules being pinned:

* the basename is DERIVED, never concatenated — no traversal, no absolute path, no
  separator of any convention survives;
* the destination is inside an allowlisted root, checked AFTER symlink resolution;
* an existing file is never silently overwritten (Mail's own ``save`` verb DOES
  overwrite silently — device-verified — so the refusal has to happen in Python, before
  the Apple Event).
"""

from __future__ import annotations

import logging
import os
import stat
import subprocess
from pathlib import Path

import pytest

from macos_apps_mcp import files
from macos_apps_mcp.errors import NativeError, WriteRefused


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "root"
    r.mkdir()
    monkeypatch.setenv("MACOS_APPS_FILE_ROOT", str(r))
    return r


# --- hostile names -------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "../../.ssh/authorized_keys",
        "../../../etc/passwd",
        "/etc/passwd",
        "//etc/passwd",
        "..\\..\\Windows\\System32\\evil.dll",
        "C:\\Windows\\evil.dll",
        "Macintosh HD:Users:andrei:.zshrc",
        "subdir/nested/payload.sh",
    ],
)
def test_no_separator_convention_survives_into_the_basename(hostile):
    """Traversal, absolute paths and every separator convention macOS has ever used
    (POSIX ``/``, Windows ``\\``, HFS ``:``) collapse to the LAST component. The name is
    never concatenated onto the destination — it is derived."""
    safe = files.safe_basename(hostile)
    assert "/" not in safe
    assert "\\" not in safe
    assert ":" not in safe
    assert not safe.startswith(".")
    assert ".." not in safe


@pytest.mark.parametrize(
    "hostile, expected",
    [
        ("", "file"),
        ("   ", "file"),
        (".", "file"),
        ("..", "file"),
        ("../", "file"),
        ("evil/", "file"),
        (".ssh", "_.ssh"),
        (".bashrc", "_.bashrc"),
        ("normal.pdf", "normal.pdf"),
        ("report 2026.final.pdf", "report 2026.final.pdf"),
    ],
)
def test_degenerate_names_fall_back_not_resolve(hostile, expected):
    assert files.safe_basename(hostile) == expected


def test_nul_and_control_bytes_are_stripped():
    # A NUL truncates a C string: "safe.pdf\x00.sh" is one name to Python and another to
    # anything that hands the path to a C API.
    assert files.safe_basename("safe.pdf\x00.sh") == "safe.pdf.sh"
    assert files.safe_basename("a\r\nb\tc.pdf") == "abc.pdf"


def test_bidi_override_is_stripped_not_preserved():
    # U+202E RIGHT-TO-LEFT OVERRIDE renders "exe.txt" as "txt.exe" — a display spoof
    # that survives every path check because it is not a path character at all.
    name = "invoice\u202egpj.exe"
    safe = files.safe_basename(name)
    assert "\u202e" not in safe
    assert safe == "invoicegpj.exe"


def test_absurdly_long_names_are_truncated_keeping_the_extension():
    safe = files.safe_basename("A" * 4096 + ".pdf")
    assert len(safe.encode()) <= 200
    assert safe.endswith(".pdf")


def test_unicode_name_survives_intact():
    # Sanitizing must not mangle a legitimate non-ASCII filename.
    assert files.safe_basename("rapport-été.pdf") == "rapport-été.pdf"


# --- the destination root ------------------------------------------------------------


def test_dest_defaults_to_the_root_itself(root):
    assert files.resolve_dest("") == root.resolve()


def test_relative_dest_lands_under_the_root(root):
    want = (root / "invoices/2026").resolve()
    assert files.resolve_dest("invoices/2026") == want


def test_absolute_dest_outside_the_root_is_refused(root, tmp_path):
    with pytest.raises(ValueError, match="outside"):
        files.resolve_dest(str(tmp_path / "elsewhere"))


def test_relative_traversal_out_of_the_root_is_refused(root):
    with pytest.raises(ValueError, match="outside"):
        files.resolve_dest("../../etc")


def test_a_symlink_pointing_out_of_the_root_is_refused(root, tmp_path):
    """The containment check runs AFTER resolution. Checking the un-resolved path
    accepts a symlink inside the root that points anywhere on disk."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        files.resolve_dest("escape")


def test_resolve_dest_does_not_create_a_directory_it_refuses(root, tmp_path):
    target = tmp_path / "never-created"
    with pytest.raises(ValueError):
        files.resolve_dest(str(target))
    assert not target.exists()


def test_resolve_dest_creates_the_directory_it_accepts(root):
    out = files.resolve_dest("deep/nested/path")
    assert out.is_dir()


# --- the whole path, end to end ------------------------------------------------------


def test_target_path_of_a_traversal_name_stays_in_the_root(root):
    path = files.target_path("invoices", "../../../../etc/passwd")
    assert path == (root / "invoices" / "passwd").resolve()
    assert path.is_relative_to(root.resolve())


def test_target_path_refuses_an_existing_file(root):
    (root / "x.pdf").write_bytes(b"mine")
    with pytest.raises(WriteRefused, match="already exists"):
        files.target_path("", "x.pdf")
    assert (root / "x.pdf").read_bytes() == b"mine"  # untouched


def test_exists_refusal_is_a_typed_write_refusal():
    e = files.exists_refusal(Path("/x/y"))
    assert isinstance(e, WriteRefused) and e.kind == "write_refused"
    assert not isinstance(e, OSError)
    assert str(e).startswith("/x/y already exists")


def test_target_path_refuses_an_existing_file_even_via_a_hostile_name(root):
    (root / "passwd").write_bytes(b"mine")
    with pytest.raises(WriteRefused):
        files.target_path("", "../../etc/passwd")


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("file_as_dest", "File exists"),
        ("file_as_parent", "Not a directory"),
        ("read_only_parent", "Permission denied"),
    ],
)
def test_resolve_dest_refuses_a_directory_it_cannot_create(root, setup, reason):
    """A dest_dir that cannot be made is a typed refusal with the OS reason, never a
    raw OSError — and nothing is created."""
    if setup == "file_as_dest":
        (root / "taken").write_bytes(b"x")
        dest, shown = "taken", root / "taken"
    elif setup == "file_as_parent":
        (root / "f").write_bytes(b"x")
        dest, shown = "f/sub", root / "f" / "sub"
    else:
        if os.geteuid() == 0:
            pytest.skip("root ignores directory permissions")
        (root / "ro").mkdir(mode=0o500)
        dest, shown = "ro/sub", root / "ro" / "sub"
    try:
        with pytest.raises(WriteRefused) as e:
            files.resolve_dest(dest)
    finally:
        if (root / "ro").exists():
            (root / "ro").chmod(0o700)
    text = str(e.value)
    assert str(shown.resolve()) in text and reason in text
    assert "nothing was written" in text and "Do not retry" in text
    assert isinstance(e.value.__cause__, OSError)
    if dest != "taken":
        assert not shown.exists()


# --- the size cap --------------------------------------------------------------------


def test_size_cap_refuses_before_anything_is_written():
    with pytest.raises(ValueError, match="larger than") as exc:
        files.check_size(11, "huge.zip", max_bytes=10)
    assert "cap" in str(exc.value)


def test_size_cap_allows_the_boundary():
    files.check_size(10, "big.zip", max_bytes=10)


def test_unknown_size_is_allowed_through(root):
    # `file size` is missing on some attachments; the post-write stat is the backstop.
    files.check_size(None, "unknown.bin", max_bytes=10)


def test_the_cap_is_the_callers_and_keyword_only():
    """D-11: no module-level cap exists, and a caller cannot forget to pass its own."""
    assert not hasattr(files, "MAX_BYTES")
    with pytest.raises(TypeError):
        files.check_size(11, "a", 10)
    with pytest.raises(TypeError):
        files.check_size(11, "a")


def test_check_size_hint_is_appended():
    with pytest.raises(ValueError, match="Save it from Mail directly"):
        files.check_size(11, "a", max_bytes=10, hint="Save it from Mail directly.")


def test_written_file_must_not_be_empty(root):
    """Device-verified 2026-08-05: saving an attachment on a NOT-downloaded message
    makes Mail fetch it. But an offline account cannot, and a 0-byte file that looks
    like a successful save is worse than a loud failure — so the file is removed and
    the call raises."""
    empty = root / "empty.pdf"
    empty.touch()
    with pytest.raises(ValueError, match="0 bytes"):
        files.confirm_written(empty)
    assert not empty.exists()


def test_confirm_written_names_the_callers_hint(root):
    empty = root / "empty.jpg"
    empty.touch()
    with pytest.raises(ValueError, match="0 bytes.*offline") as exc:
        files.confirm_written(empty, hint="the photo is offline in iCloud.")
    assert "has been removed" in str(exc.value)
    assert not empty.exists()


def test_refusals_are_neutral(root, tmp_path):
    """D-11: the shared module speaks about files, never about one caller's source."""
    messages = []
    with pytest.raises(ValueError) as outside:
        files.resolve_dest(str(tmp_path / "elsewhere"))
    messages.append(str(outside.value))
    (root / "x.bin").write_bytes(b"1")
    with pytest.raises(WriteRefused) as exists:
        files.target_path("", "x.bin")
    messages.append(str(exists.value))
    (root / "taken").write_bytes(b"1")
    with pytest.raises(WriteRefused) as cannot:
        files.resolve_dest("taken")
    messages.append(str(cannot.value))
    with pytest.raises(ValueError) as over:
        files.check_size(11, "x.bin", max_bytes=10)
    messages.append(str(over.value))
    empty = root / "empty.bin"
    empty.touch()
    with pytest.raises(ValueError) as zero:
        files.confirm_written(empty)
    messages.append(str(zero.value))
    for text in messages:
        for word in ("mail", "Mail", "attachment"):
            assert word not in text, (word, text)


def test_confirm_written_returns_the_byte_count(root):
    f = root / "ok.pdf"
    f.write_bytes(b"%PDF-1.4 hello")
    assert files.confirm_written(f) == 14
    assert f.exists()


# --- staging: a killed export's leftover (#387) -------------------------------------


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def _leftover(parent: Path, pid: int, suffix: str = "abcd1234", mode: int = 0o700):
    d = parent / f".macos-apps-mcp-export-{pid}-{suffix}"
    d.mkdir()
    (d / "photo.heic").write_bytes(b"photo")
    d.chmod(mode)
    return d


def test_staging_names_carry_the_pid(root):
    with files.staging(root / "x") as d:
        assert d.parent == root
        assert d.name.startswith(f".macos-apps-mcp-export-{os.getpid()}-")
        assert stat.S_IMODE(d.stat().st_mode) == 0o700
    assert not d.exists()


def test_staging_removes_a_dead_process_s_leftover(root):
    gone = _leftover(root, _dead_pid())
    with files.staging(root / "y"):
        pass
    assert not gone.exists()


def _swept_beside(root: Path, kept: Path) -> None:
    """Run one ``staging`` call after planting a control leftover whose process is dead.
    The control must be gone (the sweep ran) and ``kept`` must be judged on its own."""
    control = _leftover(root, _dead_pid(), "ctrl0000")
    with files.staging(root / "y"):
        pass
    assert not control.exists(), "the sweep did not run"
    assert kept.exists()


def test_staging_keeps_a_live_process_s_directory(root):
    live = subprocess.Popen(["sleep", "30"])
    try:
        kept = _leftover(root, live.pid)
        _swept_beside(root, kept)
        assert (kept / "photo.heic").read_bytes() == b"photo"
    finally:
        live.kill()
        live.wait()


def test_staging_keeps_a_directory_whose_pid_answers_eperm(root, monkeypatch):
    real_kill = os.kill

    def fake(pid, sig):
        if pid == 424242:
            raise PermissionError(1, "Operation not permitted")
        return real_kill(pid, sig)

    monkeypatch.setattr(files.os, "kill", fake)
    _swept_beside(root, _leftover(root, 424242))


def test_staging_never_follows_a_symlink_named_like_a_staging_directory(root):
    victim = root / "victim"
    victim.mkdir()
    (victim / "f").write_text("keep")
    link = root / f".macos-apps-mcp-export-{_dead_pid()}-abcd1234"
    link.symlink_to(victim)
    _swept_beside(root, victim)
    assert link.is_symlink()
    assert (victim / "f").read_text() == "keep"


def test_staging_keeps_a_directory_wider_than_0700(root):
    _swept_beside(root, _leftover(root, _dead_pid(), mode=0o755))


def test_staging_keeps_its_own_process_s_directory(root):
    _swept_beside(root, _leftover(root, os.getpid()))


@pytest.mark.parametrize(
    ("pid", "suffix"),
    [
        ("0", "abcd1234"),
        ("1", "abcd1234"),
        ("99999999999999999999", "abcd1234"),
        ("x1", "abcd1234"),
        ("DEAD", "abc"),
        ("DEAD", "abcd1234.bak"),
        ("DEAD", "ABCD1234"),
    ],
)
def test_staging_keeps_names_outside_the_exact_pattern(root, pid, suffix):
    kept = _leftover(root, _dead_pid() if pid == "DEAD" else pid, suffix)
    _swept_beside(root, kept)


def _boom(*args, **kwargs):
    # takes **kwargs: staging() calls rmtree with the onexc keyword
    raise PermissionError(1, "Operation not permitted")


def test_staging_cleanup_error_after_success_is_logged_not_raised(
    root, monkeypatch, caplog
):
    monkeypatch.setattr(files.shutil, "rmtree", _boom)
    with (
        caplog.at_level(logging.WARNING, logger="macos_apps_mcp.files"),
        files.staging(root / "y") as d,
    ):
        pass
    assert str(d) in caplog.text


def test_staging_cleanup_error_does_not_replace_the_body_s_error(root, monkeypatch):
    monkeypatch.setattr(files.shutil, "rmtree", _boom)
    with pytest.raises(NativeError, match="typed"), files.staging(root / "y"):
        raise NativeError("typed")
