"""Synthetic mailbox classification cost; no native or personal data access."""

import hashlib
import json
import platform
import sqlite3
import statistics
import subprocess
import sys
import time
import types
from urllib.parse import quote

from macos_apps_mcp.adapters import mail_index, mailbox_url
from tests.envelope import SCHEMA

BASE = "dce3324195b33ad2afe02d150adc6db786f359e0"


def baseline_module(filename, vocabulary=None):
    source = subprocess.run(
        ["git", "show", f"{BASE}:macos_apps_mcp/adapters/{filename}.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    module = types.ModuleType(f"macos_apps_mcp.adapters._benchmark_{filename}")
    module.__package__ = "macos_apps_mcp.adapters"
    sys.modules[module.__name__] = module
    if vocabulary is not None:
        source = source.replace(
            "from . import mail_ids, mailbox_url", "from . import mail_ids"
        )
        module.mailbox_url = vocabulary
    exec(compile(source, f"baseline/{filename}.py", "exec"), module.__dict__)
    return module


variants = {
    "baseline": baseline_module("mail_index", baseline_module("mailbox_url")),
    "expanded_per_message": baseline_module("mail_index", mailbox_url),
    "per_mailbox": mail_index,
}

c = sqlite3.connect(":memory:")
c.executescript(SCHEMA)
c.executescript("""
CREATE INDEX messages_mailbox_deleted ON messages(mailbox, deleted);
CREATE INDEX messages_conversation ON messages(conversation_id);
CREATE INDEX messages_mid ON messages(message_id);
CREATE INDEX global_header ON message_global_data(message_id_header);
CREATE INDEX global_mid ON message_global_data(message_id);
CREATE INDEX references_ref ON message_references(reference);
INSERT INTO subjects VALUES(1,'Synthetic message');
INSERT INTO addresses VALUES(1,'fixture@example.invalid','Fixture');
""")
leaves = [
    "INBOX",
    "Travel",
    "Archive",
    "Trash",
    "Junk E-mail",
    "Sent Items",
    "Corbeille",
    "Gelöschte Elemente",
    "Удаленные",
    "Courrier indésirable",
    "Éléments envoyés",
    "Verzonden berichten",
    "Alle Nachrichten",
    "Prullenbak",
    "Нежелательная почта",
]
for i in range(1, 156):
    leaf = leaves[(i - 1) % len(leaves)] if i <= 45 else f"Projects/Folder {i}"
    c.execute(
        "INSERT INTO mailboxes VALUES(?,?,NULL)",
        (i, "imap://A/" + quote(leaf, safe="/&()")),
    )
# 50,000 physical rows, 25,000 distinct ids. Duplicates and logical Gmail labels.
n = 50000
c.executemany(
    "INSERT INTO message_global_data VALUES(?,?,?)",
    ((i, f"<m{i}@fixture.invalid>", i) for i in range(1, n // 2 + 1)),
)
c.executemany(
    "INSERT INTO messages VALUES(?,1,1,?,?,?,?,0,0,0,?,100,?,NULL)",
    (
        (
            i,
            (i + 1) // 2,
            1 + (i % 150),
            1700000000 + i,
            1700000000 + i,
            i % 100,
            (i + 1) // 2,
        )
        for i in range(1, n + 1)
    ),
)
c.execute("UPDATE mailboxes SET source=1 WHERE ROWID=151")
c.execute("INSERT INTO labels SELECT ROWID,151 FROM messages WHERE mailbox=1")
c.execute("INSERT INTO labels SELECT ROWID,152 FROM messages WHERE mailbox=1")
c.execute("DELETE FROM messages WHERE mailbox=152")  # no rows there by construction
c.commit()
c.execute("ANALYZE")
result = {
    "python": platform.python_version(),
    "sqlite": sqlite3.sqlite_version,
    "mailboxes": 155,
    "messages": n,
    "results": {},
}
for variant, reader in variants.items():
    queries = {
        "search": reader.build_header_query(limit=25),
        "id_lookup": reader.build_header_query(
            message_ids=["<m100@fixture.invalid>"], limit=25
        ),
        "thread": reader.build_thread_query("<m100@fixture.invalid>", 25),
        "stats": reader.build_stats_query(0),
        "sent_triage": reader.build_sent_triage_query(25),
        "overview": reader.build_overview_query(),
    }
    result["results"][variant] = {}
    for name, (sql, params) in queries.items():
        c.execute(sql, params).fetchall()
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            rows = c.execute(sql, params).fetchall()
            timings.append((time.perf_counter() - start) * 1000)
        digest = hashlib.sha256(repr(sorted(rows)).encode()).hexdigest()
        result["results"][variant][name] = {
            "median_ms": round(statistics.median(timings), 2),
            "rows": len(rows),
            "sha256": digest,
        }
for name in result["results"]["per_mailbox"]:
    assert (
        result["results"]["per_mailbox"][name]["sha256"]
        == result["results"]["expanded_per_message"][name]["sha256"]
    ), name
print(json.dumps(result, indent=2))
c.close()
