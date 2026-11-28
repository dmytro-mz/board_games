---
name: bgg-weight
description: Look up the BoardGameGeek complexity weight for a game (GameSpec.weight, the chip on a game tile). Use when adding a game or updating weights.
---

`GameSpec.weight` (0–5, two decimals) is set in each `src/<game>/web/spec.py`. Take it from BGG itself, for the exact
edition we implement (e.g. the 1999 Lost Cities card game, Ticket to Ride: *Europe*); aggregator sites and web search
are stale. `curl` and the XML API fail (Cloudflare 403 / token 401), but the preview browser works:

1. `preview_open` any `https://boardgamegeek.com/boardgame/<id>`; wait ~6 s until the "Just a moment…" page clears.
2. Find ids: `fetch("/search/boardgame?q=<name>&nosession=1")` → `items[].objectid`.
3. Read weights: `fetch("/boardgame/<id>")` and regex the HTML for `"avgweight":"1.2238","numweights":"210"`
   (`/api/geekitems` does not contain it). Round to two decimals.
