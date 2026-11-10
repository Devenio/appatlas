"""Add real in-app screens, in journey order, to an app already in library.db.

    python3 ingest.py <app_id> <folder> [--flow Onboarding]  # images in filename order
    python3 ingest.py <app_id> --adb [--flow Paywall]        # Android device/emulator: Enter grabs, q stops
    python3 ingest.py <app_id> --ios [--flow Paywall]        # iPhone over USB (libimobiledevice)

Files land in screens/<app_id>/cap_N.<ext>. Then run `uv run enrich.py colors` and `uv run enrich.py label`.
App not in the library yet? `python3 seed.py us "its name"` adds it.
"""
import argparse
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from seed import index

ROOT = Path(__file__).parent
GRAB = {"adb": ["adb", "exec-out", "screencap", "-p"], "ios": ["idevicescreenshot", "-"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("app_id", type=int)
    p.add_argument("folder", nargs="?", type=Path)
    p.add_argument("--adb", action="store_true")
    p.add_argument("--ios", action="store_true")
    p.add_argument("--flow")
    args = p.parse_args()
    if not (args.folder or args.adb or args.ios):
        p.error("give a folder, --adb or --ios")
    if args.folder and not args.folder.is_dir():
        p.error(f"{args.folder} is not a folder")

    db = sqlite3.connect(ROOT / "library.db")
    if not db.execute("select 1 from apps where id = ?", (args.app_id,)).fetchone():
        sys.exit(f"App {args.app_id} is not in library.db; add it with: python3 seed.py us \"<app name>\"")
    dest = ROOT / "screens" / str(args.app_id)
    dest.mkdir(parents=True, exist_ok=True)
    n = db.execute("select coalesce(max(idx), 0) from screens where app_id = ? and source = 'capture'",
                   (args.app_id,)).fetchone()[0]

    def add(data, ext):
        nonlocal n
        n += 1
        path = dest / f"cap_{n}{ext}"
        path.write_bytes(data)
        db.execute("insert into screens (app_id, id, idx, device, source, url, flow) "
                   "values (?, ?, ?, 'iphone', 'capture', ?, ?)",
                   (args.app_id, f"cap_{n}", n, str(path.relative_to(ROOT)), args.flow))
        print(f"added {args.app_id}/cap_{n}")

    if args.folder:
        for f in sorted(f for f in args.folder.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")):
            add(f.read_bytes(), f.suffix.lower())
    else:
        cmd = GRAB["adb" if args.adb else "ios"]
        if not shutil.which(cmd[0]):
            sys.exit(f"{cmd[0]} not found; install {'Android platform-tools' if args.adb else 'libimobiledevice'}")
        while input("Enter = grab screen, q = done: ").strip().lower() != "q":
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode or not res.stdout:
                print(res.stderr.decode() or "grab failed", file=sys.stderr)
                continue
            add(res.stdout, ".png")
    index(db)


if __name__ == "__main__":
    main()
