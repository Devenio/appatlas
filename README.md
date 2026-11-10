# AppAtlas

A free design library of top-grossing iOS apps, served to AI agents over MCP,
plus two skills that teach an agent to research those apps and build from what wins.

- **Library** (`library.db`, SQLite): 3,020 apps across 23 genres (2,300 from
  Apple's top-grossing charts, the rest from niche searches such as habit
  trackers, meditation and fasting), 35,291 screens (21,520 iPhone,
  13,771 iPad), with color palettes and visual-similarity signatures.
- **MCP server** (`server.py`): 9 tools covering apps, screens, flows, UI
  elements and similar screens. Runs locally over stdio or hosted over HTTP.
- **Skills** (`skills/`): `appatlas-usage`, which covers research playbooks
  and the tool map, and `appatlas-app-design-skill`, which covers native Expo
  and React Native build rules and a simulator verification loop.

## What the data is, and isn't

| Field | Source | Notes |
|---|---|---|
| Apps, ratings, price, description, release date | iTunes Lookup API | Free and public |
| `overall_rank`, `genre_rank` | Apple's top-grossing RSS charts (top 100 each) | The revenue **proxy**. There is no revenue or download data. |
| Screens with `source: appstore` | App Store screenshots | Often marketing frames: useful for home screens and features, weak for onboarding and paywalls |
| Screens with `source: capture` | You, via `ingest.py` | Real flows in journey order. None ship yet; this is where quality comes from. |
| `colors`, similarity | `enrich.py colors` | Done for every screen |
| `flow`, `screen_type`, `name`, `elements`, `description` | `enrich.py label` (Claude vision) | **Not run yet**: needs your Anthropic key; see below |

## Use it

You need [uv](https://docs.astral.sh/uv/). The server installs its one dependency on first run.

**Claude Code, as a plugin** (MCP server and both skills):

```
/plugin marketplace add Devenio/appatlas
/plugin install appatlas@appatlas
```

**Claude Code, inside this repo:** `.mcp.json` registers the server automatically.

**Any other MCP client (stdio):**

```json
{ "mcpServers": { "appatlas": { "command": "uv", "args": ["run", "-q", "/path/to/appatlas/server.py"] } } }
```

**Skills only, for other agents:** copy `skills/*` into your agent's skills folder.

**Hosted:** `uv run server.py http 8000` serves streamable HTTP at `/mcp`.
Put it behind HTTPS and auth before exposing it.

## Tools

| Tool | Use |
|---|---|
| `search_apps` | Natural-language app search, with filters for genre, rating, ratings count, release date and free, and sorting by relevance, rank, rating, ratings count or newest |
| `get_app` | One app in full, with screen counts by source and flow |
| `list_app_screens` | An app's screens in journey order: captures first, then App Store |
| `search_screens` | Screens across the library, by text, flow, screen type, UI element, genre or app |
| `get_screen` | One screen, plus 5 visually similar screens from other apps |
| `list_flows`, `get_flow_apps` | The flow taxonomy, and the top apps for one flow |
| `list_ui_elements`, `get_element_screens` | UI element families, and the screens that use one |

## Grow the library

```bash
python3 seed.py us "habit tracker" "meditation"   # refresh charts, add niche search results
python3 ingest.py <app_id> --adb --flow Onboarding  # capture a real flow from an Android device or emulator
python3 ingest.py <app_id> --ios --flow Paywall     # ...or an iPhone over USB (libimobiledevice)
python3 ingest.py <app_id> ./my-screens --flow Paywall  # ...or a folder of screenshots, in filename order
uv run enrich.py colors                           # palettes and similarity for new screens (free)
uv run enrich.py label --limit 500                # Claude vision labels (paid, resumable)
uv run server.py check                            # self-check
uv run --with "mcp>=2,<3" --with pillow --with anthropic python tests/test_regressions.py
```

The iOS Simulator can't run App Store apps, so real iOS flows need a physical
iPhone. Most top apps look nearly the same on Android, where capture runs
from a script against an emulator.

**Labeling cost:** `label` defaults to `claude-opus-5-5`, which costs roughly
a cent per screen. `--model claude-haiku-5-5` is about 40× cheaper. Start
with `--limit` on the top-ranked apps, which is the order it runs in anyway.

## Legal

The code is MIT-licensed. `skills/` is adapted from
[Appllama/appllama-skills](https://github.com/Appllama/appllama-skills)
(also MIT); AppAtlas is not affiliated with Appllama. App metadata and
screenshots belong to Apple and the apps' developers, and are here as a
design reference for research.
