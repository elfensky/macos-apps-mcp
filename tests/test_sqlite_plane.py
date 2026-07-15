"""Unit tests for the dual-backend sqlite read plane (#58) — the shared plumbing the
Messages/Notes planes (#59/#60) build on. Uses synthetic fixture .db files (a couple of
tables/columns), never a real macOS store."""

from __future__ import annotations

import os
import sqlite3

import pytest

from macos_apps_mcp.runtime import (
    FullDiskAccessDenied,
    NativeError,
    SchemaDrift,
    _open_sqlite_ro,
    read_via_sqlite,
    run_native,
    verify_sqlite_schema,
)

# A minimal fingerprint mirroring how a real adapter declares what it reads.
_FINGERPRINT = {"message": {"guid", "text"}, "chat": {"guid", "name"}}


def _make_db(path, *, rows=(("g1", "hi"),)):
    """Build a synthetic store with the tables/columns the fingerprint expects."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE message (guid TEXT, text TEXT, extra TEXT)")
    conn.execute("CREATE TABLE chat (guid TEXT, name TEXT)")
    conn.executemany("INSERT INTO message (guid, text) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def db(tmp_path):
    return _make_db(tmp_path / "chat.db")


# --- opener --------------------------------------------------------------------------


def test_open_ro_reads_rows(db):
    conn = _open_sqlite_ro(db)
    try:
        assert conn.execute("SELECT text FROM message").fetchone()[0] == "hi"
    finally:
        conn.close()


def test_open_ro_forbids_writes(db):
    # mode=ro must reject writes at the SQLite layer — a read plane never mutates it.
    conn = _open_sqlite_ro(db)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            conn.execute("INSERT INTO message (guid, text) VALUES ('g2', 'x')")
    finally:
        conn.close()


def test_open_ro_immutable_opens(db):
    # the opt-in immutable knob still opens a (static) store for reading.
    conn = _open_sqlite_ro(db, immutable=True)
    try:
        assert conn.execute("SELECT count(*) FROM message").fetchone()[0] == 1
    finally:
        conn.close()


def test_open_ro_handles_path_with_spaces(tmp_path):
    # real Apple paths contain spaces ("Application Support") — the URI must encode it.
    d = tmp_path / "Application Support"
    d.mkdir()
    conn = _open_sqlite_ro(_make_db(d / "NoteStore.sqlite"))
    try:
        assert conn.execute("SELECT text FROM message").fetchone()[0] == "hi"
    finally:
        conn.close()


def test_open_ro_missing_file_is_not_fda(tmp_path):
    # a genuinely-absent store is NOT an FDA denial — a "grant FDA" nudge would mislead.
    with pytest.raises(NativeError) as ei:
        _open_sqlite_ro(tmp_path / "nope.db")
    assert not isinstance(ei.value, FullDiskAccessDenied)
    assert "does not exist" in str(ei.value)


def test_open_ro_directory_path_is_typed_not_raw(tmp_path):
    # a non-file path (here a directory) must surface as a typed NativeError, not a raw
    # IsADirectoryError that would escape server._guard with no remediation.
    with pytest.raises(NativeError) as ei:
        _open_sqlite_ro(tmp_path)  # a directory, not a db file
    assert not isinstance(ei.value, FullDiskAccessDenied)


def test_open_ro_uri_reflects_immutable(db, monkeypatch):
    # the immutable knob must change the URI, not merely "still open" — a dropped branch
    # or typo'd flag would pass a smoke test since plain mode=ro also opens fine.
    seen = []
    real = sqlite3.connect
    monkeypatch.setattr(
        "macos_apps_mcp.runtime.sqlite3.connect",
        lambda database, **k: seen.append(database) or real(database, **k),
    )
    _open_sqlite_ro(db, immutable=False).close()
    _open_sqlite_ro(db, immutable=True).close()
    assert "mode=ro" in seen[0] and "immutable=1" not in seen[0]
    assert "immutable=1" in seen[1]


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
def test_open_ro_permission_denied_is_fda(db):
    # a read blocked by permissions is the FDA signal — surfaced as a typed, remediable
    # error (chmod 000 stands in for the real Full-Disk-Access denial).
    os.chmod(db, 0o000)
    try:
        with pytest.raises(FullDiskAccessDenied, match="Full Disk Access"):
            _open_sqlite_ro(db)
    finally:
        os.chmod(db, 0o644)  # restore so tmp_path teardown can delete it


# --- schema fingerprint --------------------------------------------------------------


def test_verify_schema_passes_on_match(db):
    conn = _open_sqlite_ro(db)
    try:
        verify_sqlite_schema(conn, _FINGERPRINT)  # no raise
    finally:
        conn.close()


def test_verify_schema_is_case_insensitive(tmp_path):
    # SQLite identifiers are case-insensitive; a capitalization-only difference between
    # the fingerprint and the store's defined column names is NOT drift.
    p = tmp_path / "cased.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE Message (GUID TEXT, Txt TEXT)")
    conn.commit()
    conn.close()
    ro = _open_sqlite_ro(p)
    try:
        verify_sqlite_schema(ro, {"message": {"guid", "txt"}})  # no raise
    finally:
        ro.close()


def test_verify_schema_missing_table_raises(db):
    conn = _open_sqlite_ro(db)
    try:
        with pytest.raises(SchemaDrift, match="absent"):
            verify_sqlite_schema(conn, {"handle": {"id"}})  # table not in the fixture
    finally:
        conn.close()


def test_verify_schema_missing_column_raises(db):
    conn = _open_sqlite_ro(db)
    try:
        with pytest.raises(SchemaDrift, match="missing column"):
            verify_sqlite_schema(conn, {"message": {"guid", "renamed_since_macos"}})
    finally:
        conn.close()


def test_verify_schema_corrupt_db_is_drift(tmp_path):
    # a not-a-database file can't have its schema read — treated as drift so the
    # dual-backend degrades rather than crashing on a corrupt store.
    bad = tmp_path / "corrupt.db"
    bad.write_bytes(b"this is not an sqlite database")
    conn = _open_sqlite_ro(bad)
    try:
        with pytest.raises(SchemaDrift):
            verify_sqlite_schema(conn, _FINGERPRINT)
    finally:
        conn.close()


# --- dual-backend wrapper (read_via_sqlite) ------------------------------------------


def _query(conn):
    return [r[0] for r in conn.execute("SELECT text FROM message")]


def test_read_via_sqlite_happy_path(db):
    assert read_via_sqlite(db, _FINGERPRINT, _query) == ["hi"]


def test_read_via_sqlite_schema_mismatch_falls_back(db):
    # THE acceptance case: fingerprint mismatch → the adapter's AppleScript backend.
    drifted = {"message": {"guid", "gone_in_macos_27"}}
    result = read_via_sqlite(db, drifted, _query, fallback=lambda: ["from-applescript"])
    assert result == ["from-applescript"]


def test_read_via_sqlite_schema_mismatch_without_fallback_raises(db):
    # Messages content has no fallback → surface loudly, never a silent empty.
    drifted = {"message": {"guid", "gone_in_macos_27"}}
    with pytest.raises(SchemaDrift):
        read_via_sqlite(db, drifted, _query)


def test_read_via_sqlite_query_error_is_not_swallowed_as_fallback(db):
    # a NON-sqlite bug in the query fn must propagate — only STORE-unavailable signals
    # fall back, so a real parser bug is never masked by the AppleScript path.
    def boom(conn):
        raise ValueError("query bug")

    with pytest.raises(ValueError, match="query bug"):
        read_via_sqlite(db, _FINGERPRINT, boom, fallback=lambda: ["masked"])


def test_read_via_sqlite_sqlite_error_during_query_falls_back(db):
    # corruption past the schema pages surfaces only when query() reads a data page —
    # a sqlite error there must degrade to fallback, not escape raw (#58 review).
    def corrupt(conn):
        raise sqlite3.DatabaseError("database disk image is malformed")

    assert read_via_sqlite(db, _FINGERPRINT, corrupt, fallback=lambda: ["fb"]) == ["fb"]


def test_read_via_sqlite_sqlite_error_without_fallback_raises_typed(db):
    # no fallback (Messages content) → surface as a typed NativeError (SchemaDrift), so
    # server._guard converts it to a directive instead of leaking a raw sqlite error.
    def corrupt(conn):
        raise sqlite3.DatabaseError("malformed")

    with pytest.raises(SchemaDrift):
        read_via_sqlite(db, _FINGERPRINT, corrupt)


def test_read_via_sqlite_runs_inline_when_already_on_worker(db):
    # a consumer already ON the native worker (e.g. inside its own run_native block that
    # also needs osascript) must run read_via_sqlite INLINE — routing through run_native
    # again would deadlock the max_workers=1 pool (submit-from-worker waits forever).
    def on_worker():
        return read_via_sqlite(db, _FINGERPRINT, _query)

    assert run_native(on_worker) == ["hi"]


def test_read_via_sqlite_missing_store_does_not_fall_back(tmp_path):
    # a genuinely-absent store surfaces loudly even WITH a fallback — it is not the
    # FDA/drift "store unavailable" signal the dual-backend degrades on (deliberate:
    # a wrong "grant FDA"/"schema changed" nudge would mislead).
    called = []
    with pytest.raises(NativeError):
        read_via_sqlite(
            tmp_path / "nope.db",
            _FINGERPRINT,
            _query,
            fallback=lambda: called.append(1) or ["fb"],
        )
    assert not called  # fallback never invoked for a missing store


def test_read_via_sqlite_closes_conn_on_schema_drift(db, monkeypatch):
    # the finally: conn.close() is the only close on the drift path — assert the
    # connection is actually released so a leak can't regress silently.
    spies = []
    real = sqlite3.connect

    class Spy:
        def __init__(self, conn):
            self.conn = conn
            self.closed = False

        def execute(self, *a):
            return self.conn.execute(*a)

        def close(self):
            self.closed = True
            self.conn.close()

    def fake(*a, **k):
        s = Spy(real(*a, **k))
        spies.append(s)
        return s

    monkeypatch.setattr("macos_apps_mcp.runtime.sqlite3.connect", fake)
    with pytest.raises(SchemaDrift):
        read_via_sqlite(db, {"message": {"absent_col"}}, _query)
    assert spies and spies[0].closed


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
def test_read_via_sqlite_fda_denied_falls_back(db):
    os.chmod(db, 0o000)
    try:
        result = read_via_sqlite(
            db, _FINGERPRINT, _query, fallback=lambda: ["fallback"]
        )
        assert result == ["fallback"]
    finally:
        os.chmod(db, 0o644)


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
def test_read_via_sqlite_fda_denied_without_fallback_raises(db):
    os.chmod(db, 0o000)
    try:
        with pytest.raises(FullDiskAccessDenied):
            read_via_sqlite(db, _FINGERPRINT, _query)
    finally:
        os.chmod(db, 0o644)


def test_full_disk_access_denied_kind():
    # machine code doctor (#48) / agents branch on — pin the exact value.
    assert FullDiskAccessDenied.kind == "full_disk_access_denied"
