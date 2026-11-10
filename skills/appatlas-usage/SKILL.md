---
name: appatlas-usage
description: Use the AppAtlas MCP well — research real top-grossing iOS apps, their screens, flows, and UI elements, then build from what you learn. Load when the AppAtlas MCP is connected and the task involves building a mobile app or screen, researching app design patterns, studying onboarding/paywall/feature flows, improving an existing screen, or whenever a search_apps / list_app_screens / search_screens tool is available. Covers the tool map, pagination, what the data is (and isn't), and the full build-from-research playbooks.
license: MIT
metadata:
  author: AppAtlas (fork of github.com/Appllama/appllama-skills, MIT)
  version: 1.0.0
---

# AppAtlas Usage Skill

AppAtlas is a free, local design library of top-grossing iOS apps — App Store
chart rank, ratings, App Store screenshots, real captured screens where they
exist, and labels for flows, screen types, UI elements, and colors. The MCP
puts that library in an agent's hands: **not just a research tool, a
builder's tool.** You study what already wins, then you build something better.

Pair this skill with **appatlas-app-design-skill** for every design/implementation
step — this skill tells you what to study; that one tells you how to build.

## Ground rules (read first)

1. **Know what a screen is.** Every screen has a `source`:
   - `capture` — a real in-app screen, captured in journey order. This is the
     gold: onboarding, paywalls, and flows exactly as users see them.
   - `appstore` — an App Store screenshot. Often a marketing frame (headline
     plus device mockup): read the UI *inside* the mockup, and remember the
     app's marketing team chose and polished these. Good for home screens and
     hero features; weak evidence for onboarding and paywalls.
   Weight your conclusions accordingly, and say which kind of evidence a
   claim rests on.
2. **Rank is the revenue proxy.** There is no revenue data. `overall_rank` is
   the position in Apple's overall top-grossing chart (top 100 only);
   `genre_rank` is the best position in any genre's top-grossing chart. Lower
   is better. Apps with neither were added by name search, not by chart.
3. **Labels may be partial.** `flow`, `screen_type`, `name`, and `elements`
   exist only on screens that have been labeled. `list_flows` reports how many
   screens are still unlabeled. When a flow filter comes back thin, fall back
   to walking `list_app_screens` and reading the images yourself.
4. **Go deep.** Design language lives in the whole journey, not a sample —
   walk every screen of the apps that matter for the task, images included.
5. **Pagination is sequential.** Every list response carries `next_cursor`;
   pass it back with the same arguments to continue. `null` means the end.
6. **Images are URLs or local paths.** App Store screens are `https://` URLs
   on Apple's CDN; captured screens are absolute file paths — open them
   directly. Screen refs (`app_id/screen_id`) are stable.
7. **Errors are instructions.** A tool error says what to do next (wrong id →
   find it with `search_apps`; unknown ref → get refs from `list_app_screens`).

## Tool map

| Tool | What it gives you | Typical use |
|---|---|---|
| `search_apps` | 10 apps/page: name, genre, chart ranks, rating, ratings count, price, release date, screens count, **flows with screen counts**. Natural-language `query` + filters (`genre`, `rating_min`, `rating_count_min`, `released_after`, `free_only`) + `sort` (relevance, rank, rating, ratings, newest) | Find the top apps for a category or need |
| `get_app` | One app in full: description, version, age rating, ranks, screens by source and by flow | Decide if an app deserves a deep study |
| `list_app_screens` | 10 screens/page **in journey order** (captures first, then App Store), each with ref, image, flow, name, screen type, elements, colors. Filter by `flow` or `device` | Walk an app screen by screen |
| `search_screens` | Screens across the library. Free-text `query` over screen names, descriptions, elements, flows, and app name/genre; filters `flow`, `screen_type`, `element`, `genre`, `app_id`, `device` | Gather design references for one screen type |
| `get_screen` | One screen in full (description, palette) + up to 5 visually similar screens from other apps. Takes `screen_ref` = `app_id/screen_id` | Drill into one reference; find look-alikes |
| `list_flows` | The flow taxonomy with screen/app counts, plus how many screens are unlabeled | Discover what flows exist |
| `get_flow_apps` | Apps containing a flow, top-grossing first, with screen count inside that flow | Find the best examples of one flow |
| `list_ui_elements` | UI-element families with counts (one call) | Vocabulary for element-level research |
| `get_element_screens` | Screens featuring an element family | Study how winners build one component |

**Screen types:** welcome, onboarding, sign_in, permission, paywall, home,
feed, list, detail, search, profile, settings, editor, camera, player, chat,
map, checkout, stats, empty_state, marketing, other.

**The screen_ref handshake:** any `ref` from a result (e.g.
`1393061654/as_1`) can be pasted back by the user or fed straight to
`get_screen(screen_ref=...)` to see exactly that screen plus its closest
siblings across the library.

## The playbooks

| Scenario | Reference |
|---|---|
| Build an app from scratch (e.g. "build me a habit tracker") | [references/build-from-scratch.md](references/build-from-scratch.md) |
| Make an existing screen better | [references/improve-a-screen.md](references/improve-a-screen.md) |
| Flow & element research; general research method | [references/research-methods.md](references/research-methods.md) |

Both build playbooks end the same way: **the simulator loop from
appatlas-app-design-skill, repeated until you cannot find a flaw.** Research
without that loop is decoration.

## Local reference boards

When you pull screens for study, save them into a local working structure —
notes and downloads keep the research reviewable:

```
research/
  <category>/
    apps.md            # the shortlist: metrics, flows, verdicts
    <app-name>/
      screens.md       # per-screen notes: ref, name, flow, elements, colors
      img/             # downloaded screens, in journey order
    patterns.md        # cross-app synthesis: the category's design language
```

Download the screens as you study them — synthesis happens with the images
side by side, not from metadata. Refs are durable; re-fetch from the ref if
you need the pixels again.

## When the library is thin for a task

The library is the top-grossing charts plus whatever was added by search or
capture. If the category you need has few apps or no captured flows, tell the
user, and say how to extend it (from the AppAtlas repo):

- `python3 seed.py us "habit tracker"` — add the App Store's top results for a niche
- `python3 ingest.py <app_id> --adb --flow Onboarding` — capture a real flow from a device
- `uv run enrich.py colors` and `uv run enrich.py label` — compute palettes and labels for new screens
