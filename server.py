# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2,<3"]
# ///
"""MCP server over library.db (built by seed.py, enrich.py, ingest.py).

    uv run server.py              # stdio, for local MCP clients
    uv run server.py http [port]  # streamable HTTP at /mcp, for hosting (default port 8000)
    uv run server.py check        # self-check against the db

APPATLAS_DB overrides the database path.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer

DB = Path(os.environ.get("APPATLAS_DB", Path(__file__).with_name("library.db")))
PAGE = 10
db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, check_same_thread=False)
db.row_factory = sqlite3.Row
mcp = MCPServer("appatlas")

APP_FIELDS = "a.id, a.name, a.developer, a.genre, a.overall_rank, a.genre_rank, round(a.rating, 2) rating, " \
             "a.rating_count, a.formatted_price price, substr(a.released, 1, 10) released, a.icon, " \
             "(select count(*) from screens s where s.app_id = a.id) screens_count, " \
             "(select group_concat(f, ', ') from (select s.flow || ': ' || count(*) f from screens s " \
             " where s.app_id = a.id and s.flow is not null group by s.flow order by count(*) desc)) flows"
SCREEN_FIELDS = "s.app_id || '/' || s.id ref, s.idx, s.device, s.source, s.flow, s.name, s.screen_type, " \
                "s.elements, s.colors, s.url"
# ponytail: chart position as the revenue proxy; overall top 100 first, then best genre-chart position
RANK = "coalesce(a.overall_rank, 100 + a.genre_rank, 1000)"  # searched-in apps have no rank
APP_RELEVANCE = "bm25(apps_fts, 10, 2, 5, 1)"  # name, developer, genres, description
SCREEN_RELEVANCE = "bm25(screens_fts, 5, 5, 5, 3, 2, 2, 1)"  # name, type, flow, elements, description, app, genres
SORTS = {"rank": RANK, "rating": "a.rating desc, a.rating_count desc",
         "ratings": "a.rating_count desc", "newest": "a.released desc"}


def fts(query):
    """Free text to an FTS5 OR-query; each word quoted so user input can't be FTS syntax."""
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in query.split())


def clean(row):
    d = {k: row[k] for k in row.keys() if row[k] is not None}
    for k in ("elements", "colors"):
        if k in d:
            d[k] = json.loads(d[k])
    if "url" in d and not d["url"].startswith("http"):  # captured screens are files next to the db
        d["url"] = str(DB.parent / d["url"])
    return d


def paged(sql, args, cursor):
    offset = int(cursor or 0)
    rows = db.execute(f"{sql} limit {PAGE + 1} offset {offset}", args).fetchall()
    return {"items": [clean(r) for r in rows[:PAGE]], "next_cursor": str(offset + PAGE) if len(rows) > PAGE else None}


def where(conds):
    return (" where " + " and ".join(conds)) if conds else ""


@mcp.tool()
def search_apps(query: str = "", genre: str | None = None, rating_min: float | None = None,
                rating_count_min: int | None = None, released_after: str | None = None,
                free_only: bool = False,
                sort: Literal["relevance", "rank", "rating", "ratings", "newest"] | None = None,
                cursor: str | None = None) -> dict:
    """Search top-grossing iOS apps, 10 per page, each with its flows and screen counts. `query` is natural
    language matched against name, developer, genres and App Store description. `genre` is the primary genre,
    e.g. "Health & Fitness". `released_after` is an ISO date. `sort` defaults to relevance with a query, else
    rank (top-grossing chart position, the revenue proxy). Pass `next_cursor` back to continue."""
    join, conds, args = "", [], []
    if query.strip():
        join = "join apps_fts on apps_fts.rowid = a.id"
        conds.append("apps_fts match ?")
        args.append(fts(query))
    for cond, val in (("a.genre like ?", genre and f"%{genre}%"), ("a.rating >= ?", rating_min),
                      ("a.rating_count >= ?", rating_count_min), ("a.released >= ?", released_after)):
        if val is not None:
            conds.append(cond)
            args.append(val)
    if free_only:
        conds.append("a.price = 0")
    sort = sort or ("relevance" if join else "rank")
    order = APP_RELEVANCE if sort == "relevance" and join else SORTS.get(sort, RANK)
    return paged(f"select {APP_FIELDS} from apps a {join}{where(conds)} order by {order}, a.id", args, cursor)


@mcp.tool()
def get_app(app_id: int) -> dict:
    """One app in full: metadata, chart ranks, ratings, price, description, screen counts by source and flow."""
    row = db.execute("select * from apps where id = ?", (app_id,)).fetchone()
    if not row:
        return {"error": f"No app {app_id}. Find ids with search_apps."}
    count = lambda col: dict(db.execute(f"select coalesce({col}, 'unlabeled'), count(*) from screens "
                                        f"where app_id = ? group by 1 order by 2 desc", (app_id,)).fetchall())
    return {**dict(row), "screens_by_source": count("source"), "screens_by_flow": count("flow")}


@mcp.tool()
def list_app_screens(app_id: int, flow: str | None = None, device: Literal["iphone", "ipad"] | None = None,
                     cursor: str | None = None) -> dict:
    """An app's screens in journey order, 10 per page: real captured screens (source "capture") first, then
    App Store screenshots (source "appstore", often marketing frames). Each has `ref` (app_id/screen_id),
    image url or local path, and labels when enriched."""
    conds, args = ["s.app_id = ?"], [app_id]
    for col, val in (("flow", flow), ("device", device)):
        if val:
            conds.append(f"s.{col} = ?")
            args.append(val)
    return paged(f"select {SCREEN_FIELDS} from screens s{where(conds)} order by s.source = 'appstore', s.idx",
                 args, cursor)


@mcp.tool()
def search_screens(query: str = "", flow: str | None = None, screen_type: str | None = None,
                   element: str | None = None, genre: str | None = None, app_id: int | None = None,
                   device: Literal["iphone", "ipad"] | None = "iphone", cursor: str | None = None) -> dict:
    """Screens across the library, 10 per page. `query` is free text matched against screen names,
    descriptions, UI elements, flows and the app's name and genres. Filters: `flow` (see list_flows),
    `screen_type` (e.g. paywall, onboarding, home), `element` (see list_ui_elements), primary `genre`, `app_id`."""
    join, conds, args = "", [], []
    if query.strip():
        join = "join screens_fts on screens_fts.rowid = s.rowid"
        conds.append("screens_fts match ?")
        args.append(fts(query))
    for cond, val in (("s.flow = ?", flow), ("s.screen_type = ?", screen_type), ("a.genre like ?", genre and f"%{genre}%"),
                      ("s.app_id = ?", app_id), ("s.device = ?", device),
                      ("exists (select 1 from json_each(s.elements) where value = ?)", element)):
        if val is not None:
            conds.append(cond)
            args.append(val)
    order = SCREEN_RELEVANCE if join else RANK
    return paged(f"select {SCREEN_FIELDS}, a.name app, a.genre from screens s join apps a on a.id = s.app_id "
                 f"{join}{where(conds)} order by {order}, s.source = 'appstore', s.idx, a.id", args, cursor)


@mcp.tool()
def get_screen(screen_ref: str) -> dict:
    """One screen in full (`screen_ref` = "app_id/screen_id", as returned in `ref`), plus up to 5 visually
    similar screens from other apps."""
    app_id, _, screen_id = screen_ref.partition("/")
    row = db.execute(f"select {SCREEN_FIELDS}, s.description, s.dhash, s.mean_rgb, a.name app, a.genre "
                     "from screens s join apps a on a.id = s.app_id where s.app_id = ? and s.id = ?",
                     (app_id, screen_id)).fetchone()
    if not row:
        return {"error": f"No screen {screen_ref!r}. Refs look like 1393061654/as_1; get them from list_app_screens."}
    screen = clean(row)
    h, rgb = screen.pop("dhash", None), screen.pop("mean_rgb", None)
    if h is None:
        return {**screen, "similar": []}

    def dist(c):  # ponytail: brute-force dHash + mean color scan, ~30k rows; swap for image embeddings at scale
        color = sum(abs((rgb >> s & 255) - (c["mean_rgb"] >> s & 255)) for s in (0, 8, 16)) / 24
        kind = 8 if c["screen_type"] and row["screen_type"] and c["screen_type"] != row["screen_type"] else 0
        return ((h ^ c["dhash"]) & (2 ** 64 - 1)).bit_count() + color + kind

    cands = db.execute("select app_id, id, dhash, mean_rgb, screen_type from screens where dhash is not null "
                       "and device = ? and app_id != ?", (row["device"], app_id)).fetchall()
    best, seen = [], set()
    for c in sorted(cands, key=dist):  # one screen per app
        if c["app_id"] not in seen:
            seen.add(c["app_id"])
            best.append(c)
        if len(best) == 5:
            break
    similar = [clean(db.execute(f"select {SCREEN_FIELDS}, a.name app from screens s join apps a on a.id = s.app_id "
                                "where s.app_id = ? and s.id = ?", (c["app_id"], c["id"])).fetchone()) for c in best]
    return {**screen, "similar": similar}


@mcp.tool()
def list_flows() -> dict:
    """The flow taxonomy with screen and app counts. Flows come from labeling (enrich.py label)."""
    flows = db.execute("select flow, count(*) screens, count(distinct app_id) apps from screens "
                       "where flow is not null group by flow order by screens desc").fetchall()
    unlabeled = db.execute("select count(*) from screens where flow is null").fetchone()[0]
    return {"flows": [dict(f) for f in flows], "unlabeled_screens": unlabeled}


@mcp.tool()
def get_flow_apps(flow: str, cursor: str | None = None) -> dict:
    """Apps containing a flow, top-grossing first, each with its screen count inside that flow."""
    return paged(f"select {APP_FIELDS}, count(*) flow_screens from apps a join screens fs on fs.app_id = a.id "
                 f"where fs.flow = ? group by a.id order by {RANK}, a.id", [flow], cursor)


@mcp.tool()
def list_ui_elements() -> dict:
    """UI element families with screen counts, for element-level research."""
    rows = db.execute("select value element, count(*) screens from screens, json_each(screens.elements) "
                      "group by value order by screens desc").fetchall()
    return {"elements": [dict(r) for r in rows]}


@mcp.tool()
def get_element_screens(element: str, genre: str | None = None, cursor: str | None = None) -> dict:
    """Screens featuring one UI element family (exact name from list_ui_elements), top-grossing apps first."""
    return search_screens(element=element, genre=genre, cursor=cursor)


def check():
    first = search_apps()
    assert len(first["items"]) == PAGE and first["next_cursor"] == "10"
    assert first["items"][0]["overall_rank"] == 1
    second = search_apps(cursor=first["next_cursor"])
    assert not {a["id"] for a in first["items"]} & {a["id"] for a in second["items"]}

    hits = search_apps("calorie counter food", genre="Health & Fitness")
    assert hits["items"] and all(get_app(a["id"])["genre"] == "Health & Fitness" for a in hits["items"])
    assert search_apps('"; drop table apps --')["items"] is not None  # hostile input is just words
    assert "habit" in search_apps("habit tracker")["items"][0]["name"].lower()

    app = hits["items"][0]["id"]
    screens = list_app_screens(app)["items"]
    assert screens and screens[0]["ref"] == f"{app}/as_1"
    assert "error" in get_app(1) and "error" in get_screen("1/nope")

    found = search_screens("meditation sleep")["items"]
    assert found and all(s["device"] == "iphone" for s in found)
    shot = get_screen(found[0]["ref"])
    assert shot["ref"] == found[0]["ref"]
    assert len({s["ref"].split("/")[0] for s in shot["similar"]} | {shot["ref"].split("/")[0]}) == \
        len(shot["similar"]) + 1  # similar screens come from other apps, one per app
    assert "flows" in list_flows() and "elements" in list_ui_elements()
    print("check ok")


if __name__ == "__main__":
    if sys.argv[1:2] == ["check"]:
        check()
    elif sys.argv[1:2] == ["http"]:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=int(sys.argv[2]) if sys.argv[2:] else 8000)
    else:
        mcp.run()
