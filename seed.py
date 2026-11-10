"""Seed library.db from Apple's free top-grossing charts and lookup API.

    python3 seed.py [country] ["search term" ...]

Charts only hold the top 100 per genre; search terms ("habit tracker") pull in up to
50 more apps each from the App Store search API for niches the charts miss.
Stdlib only. Safe to re-run: rows are upserted, screens for refreshed apps replaced.
"""
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

COUNTRY = sys.argv[1] if len(sys.argv) > 1 else "us"
TERMS = sys.argv[2:]
DB = "library.db"

# iOS App Store genre ids. Games, Stickers, Magazines, Catalogs left out: not app UI.
GENRES = {
    6000: "Business", 6001: "Weather", 6002: "Utilities", 6003: "Travel",
    6004: "Sports", 6005: "Social Networking", 6006: "Reference",
    6007: "Productivity", 6008: "Photo & Video", 6009: "News",
    6010: "Navigation", 6011: "Music", 6012: "Lifestyle",
    6013: "Health & Fitness", 6015: "Finance", 6016: "Entertainment",
    6017: "Education", 6018: "Books", 6020: "Medical", 6023: "Food & Drink",
    6024: "Shopping", 6026: "Developer Tools", 6027: "Graphics & Design",
}

SCHEMA = """
create table if not exists apps (
  id integer primary key,          -- App Store track id
  name text, developer text, genre text, genres text,
  overall_rank integer,            -- top-grossing rank across all apps (top 100 only)
  genre_rank integer,              -- best top-grossing rank in any genre chart
  rating real, rating_count integer,
  price real, formatted_price text, age_rating text,
  released text, updated text, version text,
  bundle_id text, icon text, store_url text, description text
);
create table if not exists screens (
  app_id integer references apps(id),
  id text,                         -- ref is app_id/id, like as_1
  idx integer,                     -- journey order (store order for App Store screens)
  device text, source text, url text,       -- source: appstore | capture (ingest.py)
  flow text, name text, screen_type text,   -- enrich.py label
  elements text, description text,          -- elements: JSON array of UI element families
  colors text, dhash integer, mean_rgb integer,  -- enrich.py colors
  primary key (app_id, id)
);
create virtual table if not exists apps_fts using fts5(
  name, developer, genres, description, content='apps', content_rowid='id'
);
create virtual table if not exists screens_fts using fts5(
  name, screen_type, flow, elements, description, app, genres
);
"""


def index(db):
    """Rebuild both search indexes; run after any write to apps or screens."""
    db.execute("insert into apps_fts(apps_fts) values ('rebuild')")
    db.execute("delete from screens_fts")
    db.execute("""insert into screens_fts(rowid, name, screen_type, flow, elements, description, app, genres)
                  select s.rowid, s.name, s.screen_type, s.flow, s.elements, s.description, a.name, a.genres
                  from screens s join apps a on a.id = s.app_id""")
    db.commit()


def get_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # Apple rate-limits with 403/429; back off and retry
            if i == tries - 1:
                raise
            print(f"  retry {url[:80]}... ({e})", file=sys.stderr)
            time.sleep(10 * (i + 1))


def chart(genre=None):
    g = f"/genre={genre}" if genre else ""
    feed = get_json(f"https://itunes.apple.com/{COUNTRY}/rss/topgrossingapplications/limit=200{g}/json")
    return [int(e["id"]["attributes"]["im:id"]) for e in feed["feed"].get("entry", [])]


def main():
    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)

    overall = {app_id: i + 1 for i, app_id in enumerate(chart())}
    genre_rank = {}
    for gid, gname in GENRES.items():
        ids = chart(gid)
        print(f"{gname}: {len(ids)}")
        for i, app_id in enumerate(ids):
            genre_rank[app_id] = min(genre_rank.get(app_id, 999), i + 1)
        time.sleep(1)
    searched = set()
    for term in TERMS:
        q = urllib.parse.urlencode({"term": term, "country": COUNTRY, "entity": "software", "limit": 50})
        found = [r["trackId"] for r in get_json(f"https://itunes.apple.com/search?{q}")["results"]]
        print(f"search {term!r}: {len(found)}")
        searched.update(found)
        time.sleep(3)
    ids = sorted(set(genre_rank) | set(overall) | searched)
    print(f"{len(ids)} unique apps")

    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        res = get_json(f"https://itunes.apple.com/lookup?id={','.join(map(str, batch))}&country={COUNTRY}&entity=software")
        for a in res["results"]:
            if a.get("wrapperType") != "software" or a.get("primaryGenreName") == "Games":
                continue
            app_id = a["trackId"]
            db.execute(
                "insert or replace into apps values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (app_id, a["trackName"], a.get("artistName"), a.get("primaryGenreName"),
                 ", ".join(a.get("genres", [])), overall.get(app_id), genre_rank.get(app_id),
                 a.get("averageUserRating"), a.get("userRatingCount"),
                 a.get("price"), a.get("formattedPrice"), a.get("contentAdvisoryRating"),
                 a.get("releaseDate"), a.get("currentVersionReleaseDate"), a.get("version"),
                 a.get("bundleId"), a.get("artworkUrl512"), a.get("trackViewUrl"), a.get("description")),
            )
            shots = [("iphone", u) for u in a.get("screenshotUrls", [])] + \
                    [("ipad", u) for u in a.get("ipadScreenshotUrls", [])]
            old = [r[0] for r in db.execute(
                "select url from screens where app_id = ? and source = 'appstore' order by idx", (app_id,))]
            if old == [u for _, u in shots]:
                continue  # unchanged: keep labels and colors
            db.execute("delete from screens where app_id = ? and source = 'appstore'", (app_id,))
            db.executemany(
                "insert into screens (app_id, id, idx, device, source, url) values (?,?,?,?,'appstore',?)",
                [(app_id, f"as_{i + 1}", i + 1, dev, url) for i, (dev, url) in enumerate(shots)],
            )
        db.commit()
        print(f"looked up {min(start + 100, len(ids))}/{len(ids)}")
        time.sleep(3)

    db.execute("delete from screens where app_id in (select id from apps where genre = 'Games')")
    db.execute("delete from apps where genre = 'Games'")
    index(db)
    n_apps, n_screens = db.execute("select (select count(*) from apps), (select count(*) from screens)").fetchone()
    print(f"done: {n_apps} apps, {n_screens} screens in {DB}")


if __name__ == "__main__":
    main()
