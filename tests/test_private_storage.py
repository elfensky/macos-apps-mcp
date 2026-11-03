"""#540: real filesystem permissions; native calls stay behind fakes."""

import os
import stat
from pathlib import Path

import pytest

from macos_apps_mcp import audit, cli, doctor
from macos_apps_mcp.adapters import mail_recover


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(audit, "_STATE_DIR_REPAIRS", {})
    return tmp_path / "macos-apps-mcp"


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_fresh_state_is_private_even_with_permissive_umask(state):
    mask = os.umask(0)
    try:
        assert audit.state_dir() == state
    finally:
        os.umask(mask)
    assert mode(state) == 0o700
    assert audit.state_dir_repaired_mode() is None


def test_default_state_location_uses_the_same_permissions(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = audit.state_dir()
    assert path == tmp_path / ".local/state/macos-apps-mcp"
    assert mode(path) == 0o700


@pytest.mark.parametrize("permissions", [0o755, 0o750, 0o711, 0o777])
def test_existing_state_is_narrowed_without_changing_contents(state, permissions):
    state.mkdir()
    state.chmod(permissions)
    private_data = state / "mail_fts.sqlite"
    private_data.write_bytes(b"existing private data")
    private_data.chmod(0o644)
    parent_mode = mode(state.parent)
    assert audit.state_dir() == state
    assert mode(state) == 0o700
    assert mode(private_data) == 0o644  # the parent protects it; no recursive sweep
    assert private_data.read_bytes() == b"existing private data"
    assert mode(state.parent) == parent_mode
    assert audit.state_dir_repaired_mode() == permissions


def test_existing_owner_only_mode_is_not_widened(state):
    state.mkdir(mode=0o500)
    try:
        assert audit.state_dir() == state
        assert mode(state) == 0o500
    finally:
        state.chmod(0o700)


@pytest.mark.parametrize("dangling", [False, True])
def test_state_symlink_is_refused_without_chmod_of_target(state, dangling):
    target = state.parent / "elsewhere"
    if not dangling:
        target.mkdir(mode=0o755)
    state.symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError):
        audit.state_dir()
    if not dangling:
        assert mode(target) == 0o755
        assert list(target.iterdir()) == []
    else:
        assert not target.exists()


def test_state_regular_file_is_refused(state):
    state.write_bytes(b"keep")
    with pytest.raises(OSError):
        audit.state_dir()
    assert state.read_bytes() == b"keep"


def test_foreign_owned_directory_is_refused_without_chmod(state, monkeypatch):
    state.mkdir(mode=0o755)
    monkeypatch.setattr(audit.os, "geteuid", lambda: state.stat().st_uid + 1)
    with pytest.raises(PermissionError, match="owned by another user"):
        audit.state_dir()
    assert mode(state) == 0o755


def test_chmod_failure_stops_private_data_write(state, monkeypatch):
    state.mkdir(mode=0o755)

    def denied(*args):
        raise PermissionError("chmod denied")

    monkeypatch.setattr(audit.os, "fchmod", denied)
    with pytest.raises(PermissionError, match="chmod denied"):
        audit.state_dir()
    assert audit.audit_write({"private": "data"}) is False
    audit.usage_log("private_tool")  # non-fatal logging still writes nothing
    assert list(state.iterdir()) == []
    assert audit.state_dir_repaired_mode() is None
    assert "chmod denied" in audit.audit_read()[0]["error"]
    assert "chmod denied" in audit.read_all()[0]["error"]
    assert audit.usage_read() == {}


@pytest.mark.parametrize("role", [None, "daemon"])
def test_startup_hardens_state_before_serving(state, monkeypatch, role):
    state.mkdir(mode=0o755)
    observations = []
    name = "macos_apps_mcp.daemon.serve" if role else "macos_apps_mcp.server.main"
    monkeypatch.setattr(name, lambda: observations.append(mode(state)))
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp"] + ([role] if role else []))
    cli.main()
    assert observations == [0o700]
    assert audit.state_dir_repaired_mode() == 0o755


def test_startup_failure_does_not_serve(state, monkeypatch):
    state.write_bytes(b"not a directory")
    served = []
    monkeypatch.setattr("macos_apps_mcp.daemon.serve", lambda: served.append(True))
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp", "daemon"])
    with pytest.raises(OSError):
        cli.main()
    assert served == []


@pytest.fixture
def source(tmp_path):
    payload = b"Subject: private\r\n\r\nbody"
    path = tmp_path / "source.emlx"
    path.write_bytes(str(len(payload)).encode() + b"\n" + payload + b"<plist/>")
    return mail_recover.Target(
        id="private@example.test",
        folder="imap://test/INBOX",
        rowid=10,
        path=str(path),
        fidelity="full",
    )


def test_backup_has_private_modes_and_exact_bytes_before_act(
    state, source, monkeypatch
):
    monkeypatch.setattr(mail_recover, "locate", lambda items: items)
    observed = []

    def act(targets):
        saved = Path(targets[0].backup)
        observed.append((mode(saved), saved.read_bytes()))
        assert [mode(p) for p in [saved.parent, *saved.parents[1:4]]] == [0o700] * 4
        return {source.id: "ok"}

    mask = os.umask(0)
    try:
        result = mail_recover.recoverable("move", [source], act)
    finally:
        os.umask(mask)
    assert observed == [(0o600, b"Subject: private\r\n\r\nbody")]
    assert result["succeeded"] == 1


def test_existing_backup_directories_are_narrowed_only_on_the_write_path(state):
    receipt = state / "backup" / "mail" / "receipt"
    receipt.mkdir(parents=True)
    for path in [state, state / "backup", receipt.parent, receipt]:
        path.chmod(0o755)
    old_receipt = receipt.parent / "old"
    old_receipt.mkdir(mode=0o755)
    assert mail_recover._backup_dir("receipt") == receipt
    assert [mode(p) for p in [state, state / "backup", receipt.parent, receipt]] == [
        0o700
    ] * 4
    assert mode(old_receipt) == 0o755


@pytest.mark.parametrize(
    "component", [".", "backup", "backup/mail", "backup/mail/receipt"]
)
def test_backup_permission_failure_never_acts(state, source, monkeypatch, component):
    mail_recover._backup_dir("receipt")
    path = state / component
    path.chmod(0o755)

    def denied(fd, permissions):
        raise PermissionError("chmod denied")

    monkeypatch.setattr(audit.os, "fchmod", denied)
    monkeypatch.setattr(mail_recover, "_receipt_id", lambda op: "receipt")
    monkeypatch.setattr(mail_recover, "locate", lambda items: items)
    acted = []
    with pytest.raises(PermissionError, match="chmod denied"):
        mail_recover.recoverable("move", [source], lambda ts: acted.append(ts))
    assert acted == []
    assert not list(state.rglob("*.eml"))
    assert not (state / "audit.jsonl").exists()


@pytest.mark.parametrize("component", ["backup", "backup/mail", "backup/mail/receipt"])
def test_backup_directory_symlinks_cannot_redirect_writes(
    state, source, monkeypatch, component
):
    state.mkdir(mode=0o700)
    link = state / component
    link.parent.mkdir(parents=True, exist_ok=True)
    elsewhere = state.parent / "elsewhere"
    elsewhere.mkdir(mode=0o755)
    link.symlink_to(elsewhere, target_is_directory=True)
    monkeypatch.setattr(mail_recover, "_receipt_id", lambda op: "receipt")
    monkeypatch.setattr(mail_recover, "locate", lambda items: items)
    acted = []
    with pytest.raises(OSError):
        mail_recover.recoverable("move", [source], lambda ts: acted.append(ts))
    assert acted == []
    assert mode(elsewhere) == 0o755
    assert list(elsewhere.iterdir()) == []
    assert not (state / "audit.jsonl").exists()


@pytest.mark.parametrize("symlink", [False, True])
def test_backup_collision_never_overwrites_or_follows_existing_file(
    state, source, monkeypatch, symlink
):
    dest = mail_recover._backup_dir("receipt") / "10.eml"
    original = state.parent / "original" if symlink else dest
    original.write_bytes(b"keep")
    original.chmod(0o644)
    if symlink:
        dest.symlink_to(original)
    monkeypatch.setattr(mail_recover, "_receipt_id", lambda op: "receipt")
    monkeypatch.setattr(mail_recover, "locate", lambda items: items)
    acted = []
    with pytest.raises(FileExistsError):
        mail_recover.recoverable("move", [source], lambda ts: acted.append(ts))
    assert original.read_bytes() == b"keep"
    assert mode(original) == 0o644
    assert acted == []


@pytest.mark.parametrize("receipt", ["", ".", "..", "../elsewhere", "/elsewhere"])
def test_invalid_backup_directory_names_are_refused_before_creation(state, receipt):
    with pytest.raises(ValueError, match="one directory name"):
        mail_recover._backup_dir(receipt)
    assert not state.exists()


def test_failed_backup_write_removes_partial_file_and_never_acts(
    state, source, monkeypatch
):
    monkeypatch.setattr(mail_recover, "_receipt_id", lambda op: "receipt")
    monkeypatch.setattr(mail_recover, "locate", lambda items: items)
    real_fdopen = os.fdopen

    class FailedWrite:
        def __init__(self, fd, mode):
            self.file = real_fdopen(fd, mode)

        def __enter__(self):
            return self

        def write(self, payload):
            self.file.write(payload[:3])
            raise OSError("disk full")

        def __exit__(self, *args):
            self.file.close()

    monkeypatch.setattr(mail_recover.os, "fdopen", FailedWrite)
    acted = []
    with pytest.raises(OSError, match="disk full"):
        mail_recover.recoverable("move", [source], lambda ts: acted.append(ts))
    assert not (state / "backup/mail/receipt/10.eml").exists()
    assert not (state / "audit.jsonl").exists()
    assert acted == []


def test_missing_source_stays_an_honest_absent_backup(state, source):
    Path(source.path).unlink()
    result = mail_recover._backup("move", "receipt", [source])
    assert result[0].fidelity == "absent"
    assert result[0].backup is None
    assert not state.exists()


@pytest.fixture
def diagnostic(monkeypatch):
    """Run the real report, with every native probe replaced at its boundary."""
    monkeypatch.setattr(doctor, "_eventkit_surfaces", lambda request: [])
    monkeypatch.setattr(doctor, "_automation_surfaces", lambda request: [])
    for name in ("shortcuts", "fda", "accessibility", "mail_index"):
        monkeypatch.setattr(
            doctor,
            f"_{name}_surface",
            lambda: {"surface": "fake", "status": "ok", "ok": True},
        )
    monkeypatch.setattr(doctor, "_responsible_process", lambda: "test")
    monkeypatch.setattr(
        doctor.deploy, "grant_report", lambda: {"identities": {}, "reasons": {}}
    )
    monkeypatch.setattr(doctor.deploy, "agent_status", lambda: "test")
    return lambda: doctor.diagnose()["deployment"]["state_directory"]


def test_doctor_reports_exposed_state_without_silent_repair(state, diagnostic):
    state.mkdir(mode=0o755)
    assert diagnostic() == "exposed (0755); restrict the state directory to 0700"
    assert mode(state) == 0o755


def test_doctor_remembers_a_repair_before_its_call(state, diagnostic):
    state.mkdir(mode=0o755)
    audit.usage_log("doctor")  # the actual middleware order: logging comes first
    assert mode(state) == 0o700
    assert diagnostic() == "private (0700); repaired from 0755 by this process"
    assert "repaired from 0755" in diagnostic()  # not consumed by a first report


def test_doctor_preserves_exposure_observed_before_another_probe_repairs_it(
    state, diagnostic, monkeypatch
):
    state.mkdir(mode=0o755)

    def repairing_probe():
        audit.state_dir()
        return {"surface": "fake", "status": "ok", "ok": True}

    monkeypatch.setattr(doctor, "_mail_index_surface", repairing_probe)
    assert diagnostic().startswith("exposed (0755)")
    assert mode(state) == 0o700


def test_doctor_and_backup_usage_do_not_create_missing_state(state, diagnostic):
    assert diagnostic() == "absent; created private on use"
    assert mail_recover.backup_usage()["bytes"] == 0
    assert not state.exists()


def test_doctor_reports_symlink_without_changing_target(state, diagnostic):
    elsewhere = state.parent / "elsewhere"
    elsewhere.mkdir(mode=0o755)
    state.symlink_to(elsewhere, target_is_directory=True)
    assert "unsafe path" in diagnostic()
    assert mode(elsewhere) == 0o755


def test_doctor_reports_inspection_failure(state, diagnostic, monkeypatch):
    original = Path.lstat

    def denied(path):
        if path == state:
            raise PermissionError("stat denied")
        return original(path)

    monkeypatch.setattr(Path, "lstat", denied)
    assert diagnostic().startswith("unverified: PermissionError;")
