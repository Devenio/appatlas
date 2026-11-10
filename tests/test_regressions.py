"""Regression checks for bugs found by monkey testing.

    uv run --with "mcp>=2,<3" --with pillow --with anthropic python tests/test_regressions.py
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ANTHROPIC_API_KEY", "test")  # label() must skip before any API call

import enrich  # noqa: E402
import seed  # noqa: E402
import server  # noqa: E402

# Malformed cursors get a clear error instead of an opaque tool failure.
for bad in ("abc", "-10", "1e3", "10.5", "0x10", "99999999999999999999", "²", "10; drop table apps"):
    for out in (server.search_apps(cursor=bad), server.search_screens(cursor=bad),
                server.list_app_screens(6448311069, cursor=bad), server.get_flow_apps("Paywall", cursor=bad)):
        assert "Invalid cursor" in out.get("error", ""), (bad, out)
assert server.search_apps(cursor="10")["items"]

# NUL bytes in free text used to end the FTS5 string early ("unterminated string").
assert server.search_apps(query="habit\x00tracker")["items"]
assert server.search_screens(query="\x00")["items"]

# A capture file that went missing is skipped; the labeling run carries on.
db = sqlite3.connect(":memory:", check_same_thread=False)
db.executescript(seed.SCHEMA)
db.execute("insert into apps (id, name, genre) values (1, 'X', 'Utilities')")
db.execute("insert into screens (app_id, id, idx, device, source, url) "
           "values (1, 'cap_1', 1, 'iphone', 'capture', 'screens/1/missing.png')")
enrich.label(db, 10, "claude-haiku-5-5")
assert db.execute("select screen_type from screens").fetchone()[0] is None

# A missing folder is a usage error, not a traceback.
res = subprocess.run([sys.executable, str(ROOT / "ingest.py"), "1", "/nonexistent-bongo"], capture_output=True, text=True)
assert res.returncode == 2 and "is not a folder" in res.stderr and "Traceback" not in res.stderr, res.stderr

print("regressions ok")
