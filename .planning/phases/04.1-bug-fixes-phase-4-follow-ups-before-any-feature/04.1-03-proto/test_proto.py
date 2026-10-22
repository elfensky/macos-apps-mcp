import os, subprocess, sys, shutil, logging
from pathlib import Path
import pytest
sys.path.insert(0, os.path.dirname(__file__))
import staging_proto as sp

def names(d): return sorted(p.name for p in d.iterdir())

def mk(d, pid, suffix="abcd1234", mode=0o700):
    p = d / f".macos-apps-mcp-export-{pid}-{suffix}"; p.mkdir(mode=mode); (p / "photo.heic").write_bytes(b"x"); p.chmod(mode); return p

def dead_pid():
    p = subprocess.Popen(["true"]); p.wait(); return p.pid

def test_real_hard_exit_leaves_residue_next_call_removes_it(tmp_path):
    code = ("import sys,os; sys.path.insert(0, %r); import staging_proto as sp; from pathlib import Path\n"
            "with sp.staging(Path(%r)/'x.heic') as d:\n (d/'x.heic').write_bytes(b'photo'); os._exit(0)\n") % (os.path.dirname(__file__), str(tmp_path))
    subprocess.run([sys.executable, "-c", code], check=True)
    left = names(tmp_path); assert len(left) == 1 and left[0].startswith(".macos-apps-mcp-export-")
    with sp.staging(tmp_path / "y.heic") as d:
        assert names(tmp_path) == [d.name]          # the dead one is gone, ours is the only one
    assert names(tmp_path) == []

def test_live_pid_dir_is_kept(tmp_path):
    live = subprocess.Popen(["sleep", "30"])
    try:
        keep = mk(tmp_path, live.pid)
        with sp.staging(tmp_path / "y"): pass
        assert keep.exists()
    finally: live.kill(); live.wait()

def test_eperm_means_alive(tmp_path, monkeypatch):
    keep = mk(tmp_path, 424242)
    def kill(pid, sig): raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(os, "kill", kill)
    with sp.staging(tmp_path / "y"): pass
    assert keep.exists()

@pytest.mark.parametrize("bad", ["0", "1", "99999999999999999999", "x1", "123"])
def test_odd_names_are_not_touched(tmp_path, bad):
    p = tmp_path / f".macos-apps-mcp-export-{bad}-abcd1234"; p.mkdir(mode=0o700)
    with sp.staging(tmp_path / "y"): pass
    assert p.exists() or bad == "123"   # 123 may be a dead pid here; only 0/1/huge/garbage are guaranteed kept

def test_symlink_and_wrong_mode_are_not_followed(tmp_path):
    victim = tmp_path / "victim"; victim.mkdir(); (victim / "f").write_text("k")
    link = tmp_path / f".macos-apps-mcp-export-{dead_pid()}-abcd1234"; link.symlink_to(victim)
    wide = mk(tmp_path, dead_pid(), "wxyz9876", mode=0o755)
    with sp.staging(tmp_path / "y"): pass
    assert (victim / "f").read_text() == "k" and link.is_symlink() and wide.exists()

def test_dead_pid_dir_removed(tmp_path):
    gone = mk(tmp_path, dead_pid())
    with sp.staging(tmp_path / "y"): pass
    assert not gone.exists()

def test_cleanup_error_after_body_success_is_logged_not_raised(tmp_path, monkeypatch, caplog):
    def boom(*a, **k): raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(sp.shutil, "rmtree", boom)
    with caplog.at_level(logging.WARNING, logger="macos_apps_mcp.files"):
        with sp.staging(tmp_path / "y") as d:
            result = {"status": "written"}
    assert result == {"status": "written"} and str(d) in caplog.text

def test_cleanup_error_does_not_replace_the_body_error(tmp_path, monkeypatch):
    monkeypatch.setattr(sp.shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(PermissionError(1, "x")))
    with pytest.raises(RuntimeError, match="typed"):
        with sp.staging(tmp_path / "y"): raise RuntimeError("typed")
