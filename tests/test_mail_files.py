"""0.9.4 — the one place mail becomes a file on disk (#81 save, #85 export).

An attachment NAME is attacker-controlled: it arrives in inbound mail from anyone, and
``save_mail_attachment`` is the first feature in this repo that turns untrusted mail
into a FILESYSTEM PATH. These tests come first and they are the point of the module —
the lazy version of this code is the wrong version.

The rules being pinned:

* the basename is DERIVED, never concatenated — no traversal, no absolute path, no
  separator of any convention survives;
* the destination is inside an allowlisted root, checked AFTER symlink resolution;
* an existing file is never silently overwritten (Mail's own ``save`` verb DOES
  overwrite silently — device-verified — so the refusal has to happen in Python, before
  the Apple Event).
"""

from __future__ import annotations

import pytest

from macos_apps_mcp.adapters import mail_files


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
    safe = mail_files.safe_basename(hostile)
    assert "/" not in safe
    assert "\\" not in safe
    assert ":" not in safe
    assert not safe.startswith(".")
    assert ".." not in safe


@pytest.mark.parametrize(
    "hostile, expected",
    [
        ("", "attachment"),
        ("   ", "attachment"),
        (".", "attachment"),
        ("..", "attachment"),
        ("../", "attachment"),
        ("evil/", "attachment"),
        (".ssh", "_.ssh"),
        (".bashrc", "_.bashrc"),
        ("normal.pdf", "normal.pdf"),
        ("report 2026.final.pdf", "report 2026.final.pdf"),
    ],
)
def test_degenerate_names_fall_back_not_resolve(hostile, expected):
    assert mail_files.safe_basename(hostile) == expected


def test_nul_and_control_bytes_are_stripped():
    # A NUL truncates a C string: "safe.pdf\x00.sh" is one name to Python and another to
    # anything that hands the path to a C API.
    assert mail_files.safe_basename("safe.pdf\x00.sh") == "safe.pdf.sh"
    assert mail_files.safe_basename("a\r\nb\tc.pdf") == "abc.pdf"


def test_bidi_override_is_stripped_not_preserved():
    # U+202E RIGHT-TO-LEFT OVERRIDE renders "exe.txt" as "txt.exe" — a display spoof
    # that survives every path check because it is not a path character at all.
    name = "invoice\u202egpj.exe"
    safe = mail_files.safe_basename(name)
    assert "\u202e" not in safe
    assert safe == "invoicegpj.exe"


def test_absurdly_long_names_are_truncated_keeping_the_extension():
    safe = mail_files.safe_basename("A" * 4096 + ".pdf")
    assert len(safe.encode()) <= 200
    assert safe.endswith(".pdf")


def test_unicode_name_survives_intact():
    # Sanitizing must not mangle a legitimate non-ASCII filename.
    assert mail_files.safe_basename("rapport-été.pdf") == "rapport-été.pdf"


# --- the destination root ------------------------------------------------------------


def test_dest_defaults_to_the_root_itself(root):
    assert mail_files.resolve_dest("") == root.resolve()


def test_relative_dest_lands_under_the_root(root):
    want = (root / "invoices/2026").resolve()
    assert mail_files.resolve_dest("invoices/2026") == want


def test_absolute_dest_outside_the_root_is_refused(root, tmp_path):
    with pytest.raises(ValueError, match="outside"):
        mail_files.resolve_dest(str(tmp_path / "elsewhere"))


def test_relative_traversal_out_of_the_root_is_refused(root):
    with pytest.raises(ValueError, match="outside"):
        mail_files.resolve_dest("../../etc")


def test_a_symlink_pointing_out_of_the_root_is_refused(root, tmp_path):
    """The containment check runs AFTER resolution. Checking the un-resolved path
    accepts a symlink inside the root that points anywhere on disk."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        mail_files.resolve_dest("escape")


def test_resolve_dest_does_not_create_a_directory_it_refuses(root, tmp_path):
    target = tmp_path / "never-created"
    with pytest.raises(ValueError):
        mail_files.resolve_dest(str(target))
    assert not target.exists()


def test_resolve_dest_creates_the_directory_it_accepts(root):
    out = mail_files.resolve_dest("deep/nested/path")
    assert out.is_dir()


# --- the whole path, end to end ------------------------------------------------------


def test_target_path_of_a_traversal_name_stays_in_the_root(root):
    path = mail_files.target_path("invoices", "../../../../etc/passwd")
    assert path == (root / "invoices" / "passwd").resolve()
    assert path.is_relative_to(root.resolve())


def test_target_path_refuses_an_existing_file(root):
    (root / "x.pdf").write_bytes(b"mine")
    with pytest.raises(FileExistsError, match="already exists"):
        mail_files.target_path("", "x.pdf")
    assert (root / "x.pdf").read_bytes() == b"mine"  # untouched


def test_target_path_refuses_an_existing_file_even_via_a_hostile_name(root):
    (root / "passwd").write_bytes(b"mine")
    with pytest.raises(FileExistsError):
        mail_files.target_path("", "../../etc/passwd")


# --- the size cap --------------------------------------------------------------------


def test_size_cap_refuses_before_anything_is_written():
    with pytest.raises(ValueError, match="larger than"):
        mail_files.check_size(mail_files.MAX_BYTES + 1, "huge.zip")


def test_size_cap_allows_the_boundary():
    mail_files.check_size(mail_files.MAX_BYTES, "big.zip")


def test_unknown_size_is_allowed_through(root):
    # `file size` is missing on some attachments; the post-write stat is the backstop.
    mail_files.check_size(None, "unknown.bin")


def test_written_file_must_not_be_empty(root):
    """Device-verified 2026-08-05: saving an attachment on a NOT-downloaded message
    makes Mail fetch it. But an offline account cannot, and a 0-byte file that looks
    like a successful save is worse than a loud failure — so the file is removed and
    the call raises."""
    empty = root / "empty.pdf"
    empty.touch()
    with pytest.raises(ValueError, match="0 bytes"):
        mail_files.confirm_written(empty)
    assert not empty.exists()


def test_confirm_written_returns_the_byte_count(root):
    f = root / "ok.pdf"
    f.write_bytes(b"%PDF-1.4 hello")
    assert mail_files.confirm_written(f) == 14
    assert f.exists()
