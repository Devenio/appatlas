# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "anthropic>=1"]
# ///
"""Enrich screens in library.db.

    uv run enrich.py colors [--limit N]             # free: palette, dHash, mean color from 64px thumbnails
    uv run enrich.py label  [--limit N] [--model M] # Claude vision: name, screen type, flow, UI elements

`label` needs Anthropic credentials (ANTHROPIC_API_KEY or `ant auth login`).
Both skip screens already done, so they can be stopped and resumed.
"""
import argparse
import base64
import io
import json
import sqlite3
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field

from seed import index

ROOT = Path(__file__).parent
SCREEN_TYPES = ("welcome", "onboarding", "sign_in", "permission", "paywall", "home", "feed", "list", "detail",
                "search", "profile", "settings", "editor", "camera", "player", "chat", "map", "checkout", "stats",
                "empty_state", "marketing", "other")
FLOWS = ("Welcome", "Onboarding", "Sign In", "Paywall", "Home", "Discover & Search", "Detail", "Create & Edit",
         "Tracking & Logging", "Stats & Progress", "Social", "Messaging", "Checkout", "Profile", "Settings",
         "Notifications", "Media Playback", "App Store Promo")
ELEMENTS = ("Bottom Tab Bar", "Floating Bottom Nav", "Top Navigation Bar", "Large Title", "Search Bar",
            "Segmented Control", "Rounded Primary CTA", "Secondary Button", "Text Link", "Skip Text Link",
            "Close Button", "Top Progress Bar", "Page Dots", "Card", "Card Grid", "Horizontal Carousel",
            "List Rows", "Section Header", "Toggle", "Slider", "Text Input", "Date Picker", "Chips", "Avatar",
            "Badge", "Chart", "Progress Ring", "Calendar", "Map", "Video Player", "Media Thumbnail",
            "Illustration", "Photo Background", "Plan Selector", "Feature Checklist", "Ratings & Testimonials",
            "Bottom Sheet", "Modal Dialog", "Toast or Banner", "Floating Action Button", "Keyboard",
            "Device Mockup")


class Label(BaseModel):
    name: str = Field(description='Short screen name, e.g. "Paywall · annual plan with 7-day trial"')
    screen_type: Literal[SCREEN_TYPES]
    flow: Literal[FLOWS] = Field(description="The journey this screen belongs to")
    elements: list[Literal[ELEMENTS]] = Field(description="UI element families visible on the screen")
    description: str = Field(description="2-3 sentences: layout, hierarchy, primary action, visual style")


def load(url, width=None):
    """Image bytes. App Store urls are resized by Apple's CDN; captures are files under ROOT."""
    if not url.startswith("http"):
        return (ROOT / url).read_bytes()
    if width and "mzstatic.com" in url:
        url = url.rsplit("/", 1)[0] + f"/{width}x0w.jpg"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
        return r.read()


def signature(data):
    """(top-5 hex palette, 64-bit dHash as signed int, mean color as 0xRRGGBB)."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    q = img.quantize(5)
    pal = q.getpalette()
    colors = ["#%02x%02x%02x" % tuple(pal[i * 3:i * 3 + 3]) for _, i in sorted(q.getcolors(), reverse=True)]
    px = img.convert("L").resize((9, 8)).get_flattened_data()
    bits = [px[y * 9 + x] > px[y * 9 + x + 1] for y in range(8) for x in range(8)]
    h = sum(1 << i for i, bit in enumerate(bits) if bit)
    r, g, b = img.resize((1, 1)).getpixel((0, 0))
    return json.dumps(colors), h - (1 << 64) if h >= 1 << 63 else h, (r << 16) | (g << 8) | b


def colors(db, limit):
    rows = db.execute(f"select rowid, url from screens where dhash is null limit {limit}").fetchall()

    def work(row):
        try:
            return row[0], signature(load(row[1], width=64))
        except Exception as e:  # dead CDN link or bad image: leave it null, retry next run
            print(f"  skip {row[1][:70]}: {e}", file=sys.stderr)

    with ThreadPoolExecutor(32) as pool:
        for n, res in enumerate(pool.map(work, rows), 1):
            if res:
                db.execute("update screens set colors = ?, dhash = ?, mean_rgb = ? where rowid = ?", (*res[1], res[0]))
            if n % 500 == 0 or n == len(rows):
                db.commit()
                print(f"colors {n}/{len(rows)}")


def label(db, limit, model):
    import anthropic
    client = anthropic.Anthropic(max_retries=5)
    # refusals reroute server-side; Haiku has no server-side fallback
    fallback = {} if "haiku" in model else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    rows = db.execute(f"""select s.rowid, s.url, s.source, a.name, a.genre from screens s join apps a on a.id = s.app_id
                          where s.screen_type is null and s.device = 'iphone'
                          order by coalesce(a.overall_rank, 100 + a.genre_rank, 1000), a.id, s.idx
                          limit {limit}""").fetchall()

    def work(row):
        rowid, url, source, app, genre = row
        if url.startswith("http"):
            image = {"type": "url", "url": url}
        else:
            mime = "image/jpeg" if url.lower().endswith((".jpg", ".jpeg")) else "image/png"
            try:
                image = {"type": "base64", "media_type": mime, "data": base64.b64encode(load(url)).decode()}
            except OSError as e:  # capture file moved or deleted: skip it, keep the run going
                print(f"  skip {url}: {e}", file=sys.stderr)
                return None
        kind = "an App Store screenshot (may be a promo frame)" if source == "appstore" else "a real in-app screen"
        try:
            res = client.beta.messages.parse(
                model=model, max_tokens=4000, output_format=Label, output_config={"effort": "low"}, **fallback,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": image},
                    {"type": "text", "text": f"This is {kind} from the iOS app {app!r} ({genre}). Label it for a "
                     "mobile design reference library. For a promo frame (marketing headline around a device "
                     "mockup) use screen_type 'marketing' and flow 'App Store Promo', but still list the UI "
                     "elements and describe the app UI shown inside the mockup."},
                ]}],
            )
        except anthropic.AuthenticationError:
            raise
        except anthropic.APIError as e:  # one bad image shouldn't stop the run
            print(f"  skip {url[:70]}: {e}", file=sys.stderr)
            return None
        if res.stop_reason == "refusal" or res.parsed_output is None:
            return None
        return rowid, res.parsed_output

    # ponytail: synchronous calls; the Message Batches API halves the cost for a full-library run
    with ThreadPoolExecutor(8) as pool:
        for n, res in enumerate(pool.map(work, rows), 1):
            if res:
                rowid, lab = res
                # coalesce: a flow set at capture time wins
                db.execute("update screens set name = ?, screen_type = ?, flow = coalesce(flow, ?), elements = ?, "
                           "description = ? where rowid = ?", (lab.name, lab.screen_type, lab.flow,
                                                              json.dumps(lab.elements), lab.description, rowid))
            if n % 50 == 0 or n == len(rows):
                db.commit()
                print(f"labeled {n}/{len(rows)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=["colors", "label"])
    p.add_argument("--limit", type=int, default=1_000_000)
    p.add_argument("--model", default="claude-opus-5-5", help="claude-haiku-5-5 is far cheaper for a full run")
    args = p.parse_args()
    db = sqlite3.connect(ROOT / "library.db", check_same_thread=False)
    colors(db, args.limit) if args.step == "colors" else label(db, args.limit, args.model)
    index(db)
