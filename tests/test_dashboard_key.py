"""The dashboard page key (PLAT-02, D-19): the key file, the Guard's key matrix, the
``dashboard`` CLI role and the ``doctor`` note.

The key file is reached only through ``deploy._DASHBOARD_KEY_FILE``, patched to a tmp
path here and suite-wide in ``tests/conftest.py``. No test binds a port or opens a
browser, and every key in this file is a fixed fake.
"""

import os
import stat

import pytest

from macos_apps_mcp import audit, deploy
from macos_apps_mcp import server as _server  # noqa: F401 — fills registry.TOOLS
from tests._dashboard import FORM, KEY, ORIGIN, TOKEN, build, get, request

SECURITY_HEADERS = (
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "cache-control",
)
NEEDS = "macos-apps-mcp dashboard"
LINK_COOKIE = (
    f"macos_apps_mcp_key={KEY}; HttpOnly; Max-Age=34560000; Path=/; SameSite=strict"
)


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    path = tmp_path / "d" / "dashboard_key"
    monkeypatch.setattr(deploy, "_DASHBOARD_KEY_FILE", path)
    return path


@pytest.fixture
def daemon_state(tmp_path, monkeypatch):
    """The daemon role with a private deny-list file and state dir."""
    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    monkeypatch.delenv("MACOS_APPS_ADAPTERS_OFF", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(deploy, "_ADAPTERS_OFF_FILE", tmp_path / "off" / "adapters_off")
    return tmp_path


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def _has_headers(r):
    assert all(h in r.headers for h in SECURITY_HEADERS)
    assert r.headers["referrer-policy"] == "same-origin"


# --- the key file -------------------------------------------------------------------


def test_key_file_is_created_once_with_private_modes(keyfile):
    keyfile.parent.mkdir(mode=0o755)
    os.chmod(keyfile.parent, 0o755)
    key = deploy.dashboard_key(create=True)
    assert key and len(key) == 43 and key == keyfile.read_text()
    assert _mode(keyfile) == 0o600 and _mode(keyfile.parent) == 0o700
    assert deploy.dashboard_key(create=True) == key  # a restart reads the same key
    assert deploy.dashboard_key() == key
    keyfile.unlink()
    assert deploy.dashboard_key(create=True) != key


def test_reading_without_create_never_writes(keyfile):
    assert deploy.dashboard_key() is None
    assert not keyfile.exists() and not keyfile.parent.exists()


@pytest.mark.parametrize(
    "content",
    ["", "   ", "short", "A" * 20 + " " + "B" * 22, "A" * 20 + ";" + "B" * 22],
)
def test_unusable_key_file_is_none_and_never_rewritten(keyfile, content):
    keyfile.parent.mkdir()
    keyfile.write_text(content)
    assert deploy.dashboard_key(create=True) is None
    assert deploy.dashboard_key() is None
    assert keyfile.read_text() == content


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 file")
def test_unreadable_key_file_is_none_and_unchanged(keyfile):
    keyfile.parent.mkdir()
    keyfile.write_text(KEY)
    keyfile.chmod(0)
    try:
        assert deploy.dashboard_key(create=True) is None
    finally:
        keyfile.chmod(0o600)
    assert keyfile.read_text() == KEY


def test_a_directory_at_the_key_path_is_none(keyfile):
    keyfile.mkdir(parents=True)
    assert deploy.dashboard_key(create=True) is None
    assert keyfile.is_dir()


def test_failed_write_leaves_no_key_and_no_temp_file(keyfile, monkeypatch):
    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    assert deploy.dashboard_key(create=True) is None
    assert not keyfile.exists()
    assert list(keyfile.parent.iterdir()) == []


# --- an unusable key refuses everything (503) ---------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/usage"),
        ("GET", "/static/dashboard.css"),
        ("GET", "/key?k=anything"),
        ("POST", "/adapters"),
    ],
)
def test_no_usable_key_answers_503_on_every_route(method, path):
    headers = {**FORM, "origin": ORIGIN} if method == "POST" else None
    r = request(
        method, path, app=build(key=None), headers=headers, content=f"token={TOKEN}"
    )
    assert r.status_code == 503
    assert "dashboard_key" in r.text and "launchctl kickstart" in r.text
    assert "set-cookie" not in r.headers
    _has_headers(r)


# --- the Guard's order and the key matrix -------------------------------------------


@pytest.mark.parametrize("path", ["/usage", f"/key?k={KEY}"])
@pytest.mark.parametrize("cookie", [True, False])
def test_host_is_checked_before_the_key(path, cookie):
    r = get(path, host="evil.example", cookie=cookie)
    assert r.status_code == 400 and "set-cookie" not in r.headers


@pytest.mark.parametrize(
    "path", ["/", "/usage", "/adapters", "/static/dashboard.css", "/nope"]
)
def test_no_cookie_is_refused_everywhere(path):
    r = get(path, cookie=False)
    assert r.status_code == 403 and NEEDS in r.text
    _has_headers(r)


def test_head_without_the_cookie_is_refused():
    assert request("HEAD", "/usage", cookie=False).status_code == 403


@pytest.mark.parametrize(
    "cookie",
    [
        "macos_apps_mcp_key=wrong",
        "macos_apps_mcp_key=",
        "other=" + KEY,
        b"macos_apps_mcp_key=\xff\xfe",  # a non-ASCII byte: refused, never a 500
    ],
)
def test_wrong_cookie_is_refused(cookie):
    r = get("/usage", headers={"cookie": cookie}, cookie=False)
    assert r.status_code == 403 and NEEDS in r.text


def test_the_link_sets_the_cookie_and_redirects_home():
    r = get(f"/key?k={KEY}", cookie=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert r.headers.get_list("set-cookie") == [LINK_COOKIE]
    _has_headers(r)


@pytest.mark.parametrize("path", ["/key", "/key?k=", "/key?k=wrong", f"/key?x={KEY}"])
def test_the_link_with_a_wrong_key_is_refused_without_a_cookie(path):
    r = get(path, cookie=False)
    assert r.status_code == 403 and NEEDS in r.text
    assert "set-cookie" not in r.headers
    _has_headers(r)


def test_a_tossed_duplicate_cookie_cannot_shadow_the_real_one():
    both = f"macos_apps_mcp_key=evil; macos_apps_mcp_key={KEY}"
    assert get("/usage", headers={"cookie": both}, cookie=False).status_code == 200
    alone = get("/usage", headers={"cookie": "macos_apps_mcp_key=evil"}, cookie=False)
    assert alone.status_code == 403


def test_the_form_token_still_guards_writes(daemon_state):
    form = {**FORM, "origin": ORIGIN}
    body = "action=toggle&adapter=photos&on=0"
    no_token = request("POST", "/adapters", headers=form, content=body)
    assert no_token.status_code == 403 and "Forbidden token" in no_token.text
    no_cookie = request(
        "POST", "/adapters", headers=form, content=f"token={TOKEN}&{body}", cookie=False
    )
    assert no_cookie.status_code == 403 and NEEDS in no_cookie.text
    assert not deploy._ADAPTERS_OFF_FILE.exists()


# --- nothing leaks ------------------------------------------------------------------


def test_a_refusal_echoes_no_request_value():
    r = get("/%3Cscript%3Ex%3C/script%3E?q=%3Cscript%3E", cookie=False)
    assert r.status_code == 403 and r.headers["content-type"].startswith("text/plain")
    assert "<script" not in r.text


def test_the_key_is_in_no_page_audit_or_usage_record(daemon_state):
    pages = [get("/usage").text, get("/adapters").text]
    toggle = request(
        "POST",
        "/adapters",
        headers={**FORM, "origin": ORIGIN},
        content=f"token={TOKEN}&action=toggle&adapter=photos&on=0",
    )
    assert toggle.status_code == 303
    assert audit._audit_path().exists()
    for path in (audit._audit_path(), audit._usage_path()):
        if path.exists():
            pages.append(path.read_text())
    assert all(KEY not in page for page in pages)
