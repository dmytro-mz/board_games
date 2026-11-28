# Performance

What the server and the clients cost, why, and what was changed to make them cheaper (November 2026). Every
number comes from the benchmarks in `scripts/platform/` on an M3 Pro (11 cores), headless Chrome; raw output goes
to `tmp/bench/` (gitignored). `scripts/platform/perf_check.py` guards the key numbers with budgets.

| Tool | Measures |
|---|---|
| `bench_server.py` | every bot game played headless through its real room and driver: snapshot build, encoding, bytes raw / on the wire (permessage-deflate as negotiated), longest event-loop block, CPU |
| `bench_load.py` | a real server process with N rooms of bot games at real speed and 4 websocket clients per room: message round trip p50/p99/max, server CPU and memory |
| `bench_client.py` | the room page + a game in Chrome over CDP: cold/warm loads (optionally over an emulated network), idle CPU in the lobby and at the table, CPU/frames/long tasks while bots play, heap and DOM over a long session, what's left after going back to selection |
| `bench_trace.py` | a Chrome trace of a game, summarised by trace event, plus the CSS animations that run |
| `bench_growth.py` | which part of a page grows over a long session |
| `compare_shots.py` | every demo stage rendered by two checkouts, diffed pixel by pixel |
| `bench_report.py` | the tables below from two sets of results |

## 1. Architecture assessment

Where resources actually went (baseline), from most to least important:

1. **Bots blocking the event loop.** The server is one asyncio loop. Pandemic's planner and Skyjo's bots thought
   on it: a Pandemic turn plan blocked the loop for up to 280–500 ms, 18 times per game. The time-budgeted search
   bots (Avenue, Sumo, Toy Battle) already ran in a thread, but a thread holds the GIL: while one thinks (1–1.5 s
   per move), every message of every room waits 15–45 ms (p95, one room), and with several rooms the bots share one
   core: at 10 rooms the round trip was 278 ms (p50) / 1 s (p99), at 40 rooms 3.3 s / 7.7 s, and every bot searched
   with a fraction of a core (weaker play under load).
2. **Clients drawing frames while nothing happens.** Nine games ran a permanent `requestAnimationFrame` loop for
   the turn timer (even with timers off), costing 10–15 ms CPU per second in every game lobby and up to 61 ms/s at
   a table. On top, "your move" pulses animating `box-shadow` (Toy Battle, Phase 10, Avenue) or an SVG element's
   opacity (Karak) re-layerize and repaint the whole page 60 times a second: 38–150 ms/s at an idle table.
3. **Static files.** `Cache-Control: no-cache` on everything: a warm reload made 13–20 requests, 9–16 of them
   revalidations (each a round trip; ~650–790 ms over a 60 ms link). No compression: a cold load moved 91–462 kB
   of game code and 46 kB of shell; plus 624 kB of JPEG tile thumbnails.
4. **Server memory.** 50 MB idle, of which FastAPI + pydantic were ~14 MB; all eleven games together ~6 MB.

What was **not** a bottleneck (so it was left alone, despite being on the list of suspects):

- **Full snapshots per listener per event.** Building a `state_for` takes 11–46 µs; a whole game spends 1–61 ms
  building, 1–85 ms encoding, 1–99 ms deflating. permessage-deflate (negotiated by uvicorn and every browser)
  already shrinks the stream 6–20× thanks to context takeover between similar snapshots: 4–856 kB per player per
  game. A diff protocol or a binary format would save tens of ms of CPU per game and a few hundred kB per hour of
  play, at the cost of a second client-side state model in eleven games. Not worth it.
- **JSON speed** (orjson): encoding is ~0.03 ms per message.
- **Two sockets per player**: each costs ~40 kB of server memory and an idle ping every 20 s; merging them would
  mean tunnelling the game's socket through the room page with postMessage in every game.
- **Rendering technology.** While bots play, every game holds 60 fps (p95 frame 16.7–16.8 ms) with zero long tasks;
  game JavaScript is a small share of the frame (Karak: 33 ms of script in 8 s). A Canvas/WebGL rewrite would
  only shave paint costs that don't show, and would risk the look.
- **Leaks.** Going back to game selection frees everything (1 document, 336 nodes, 0.9 MB heap). The only thing
  that grows during a session is the game log feed (~370 nodes per game), which players can scroll back through.

## 2. Changes, with their measured effect

| # | Change | Why | Effect |
|---|---|---|---|
| 1 | **Bots think off the event loop.** `Table.think(key, compute)`: inside `plan()` or a step, under `drive()` the computation runs in a thread and the driver plans again; the step gets the result when it runs again for the same key (a stale key is never used; called directly, e.g. by tests, it computes inline). Used by Pandemic (`act`, `react`) and Skyjo (moves, setup flips). | A 100–500 ms decision on the loop stalls every room | Pandemic: longest loop block 280 → 0.6 ms, loop CPU per game 1484 → 41 ms; same game, same decisions (identical event sequence for a fixed seed) |
| 2 | **Search bots think in worker processes.** `think_apart(agent, method, *args)` runs the decision in a spawned worker process (lazily started, ≤ cpu−1 workers, prewarmed when a search bot sits down, gone after 2 idle minutes, and gone with the server). The bot object travels both ways, so its random generator continues exactly as in-process (`tests/platform/test_table.py`). Avenue, Sumo, Toy Battle. | A thinking bot holds the GIL: every message waits; bots share one core | One room: message p95 38–43 → 0.5–2.1 ms. 10 rooms: p50/p99 278/1046 → 0.4/0.8 ms. 40 rooms: 3.3 s/7.7 s → 0.7/17 ms, and bots get a full core each instead of a fraction (470 vs 289 messages/s: the games run at their intended speed). Memory while search bots play: +~27 MB for one worker and the resource tracker (+18 MB per extra concurrent worker), released 2 minutes after the last move |
| 3 | **FastAPI → Starlette.** Same routes, same JSON (errors keep `{"detail": …}`); a tiny `Router` keeps `Backend.routes(router)` | FastAPI + pydantic cost memory and import time for nothing we use | Idle server 50 → 38 MB (physical footprint, −24%) |
| 4 | **Versioned, immutable, gzipped static files.** `StaticDir` serves `/…/static/~<fingerprint>/…` with `Cache-Control: immutable` (the fingerprint covers the whole folder, recomputed from file stats on each page load, so an edit reaches the next load); `PageRewriter` versions a page's links, adds an import map for the shared modules and modulepreload hints for the whole import graph; text is gzipped once in memory; configs and the TTR map are encoded once with ETags; images get ETag 304s | Every reload revalidated every file; nothing was compressed; imports loaded in a waterfall | Warm reload: 13–20 requests (9–16 revalidations) → 4 requests (0), 640–790 → ~370 ms over a 60 ms link. Cold: game code 91–462 → 28–217 kB, shell 46 → 18 kB |
| 5 | **AVIF tile thumbnails** (owner approved), quality chosen per image for SSIM ≥ 0.99 against the old JPEG (`scripts/platform/thumb.py`); the unused `avel.jpg` is gone | The thumbnails were the biggest thing on a cold load | 731 → 324 kB |
| 6 | **No idle frames for turn timers.** `frameLoop(draw, running)` in `platform.js`: draws on the next frame and keeps going only while a timer runs; each game kicks it after every render and when a state sets or clears the timer. Nine games. | A permanent rAF loop wrote the timer bar every frame | Idle lobby 10–15 → 0.2–0.6 ms CPU/s in all games; idle table TTR 61 → 0.1, Lost Cities 15 → 0.1, Skyjo 13 → 0.1, Sumo 5 → 0.1 |
| 7 | **Compositor pulses** (owner: a slightly different glow is fine). Toy Battle's "draw" bag and Phase 10's draw piles: the glow is a pseudo-element whose opacity breathes (the compositor animates it) instead of an animated `box-shadow` | Each frame re-layerized and repainted the page | Idle table: Toy Battle 130 → 0.7 ms/s, Phase 10 58 → 0.9 ms/s |

Everything a player sees is unchanged except the two pulses in #7 (they fade instead of growing) and the
re-encoded thumbnails in #5. Timings are unchanged: bots still wait their delay, then think (in #1 the think runs
after the same delay as before; in #2 the time budget is the same, now on an unshared core).

## 3. Before / after

Generated by `uv run python scripts/platform/bench_report.py` (before = the commit before this work, run from a
worktree; after = this commit).

#### Server: headless bot games

| Game | Longest loop block (ms) | Blocks > 20 ms | Loop CPU per game (ms) | Snapshot build (µs) | Wire kB / player |
|---|---|---|---|---|---|
| ttr | 5.7 → **6.8** | 0 → **0** | 187 → **192** | 24 / 24 | 29 / 30 |
| pandemic | 279.5 → **0.6** | 18 → **0** | 1484 → **41** | 18 / 20 | 22 / 22 |
| karak | 0.8 → **0.8** | 0 → **0** | 215 → **178** | 28 / 27 | 559 / 437 |
| skyjo | 0.7 → **0.2** | 0 → **0** | 228 → **79** | 13 / 14 | 50 / 46 |
| phase10 | 6.7 → **6.6** | 0 → **0** | 1292 → **1275** | 44 / 45 | 856 / 856 |
| lostcities | 0.3 → **0.3** | 0 → **0** | 45 → **44** | 46 / 46 | 105 / 105 |
| toybattle | 6.7 → **0.2** | 0 → **0** | 30 → **34** | 17 / 19 | 5 / 6 |
| sumo | 3.2 → **0.3** | 0 → **0** | 211 → **135** | 11 / 11 | 14 / 10 |
| avenue | 6.4 → **0.3** | 0 → **0** | 30 → **33** | 18 / 21 | 4 / 5 |

#### Server: capacity

| Rooms (×4 clients) | Message RTT p50 / p99 / max (ms) | Server CPU (% of a core) | Memory (MB) | Messages/s |
|---|---|---|---|---|
| 1 | 1.5 / 2.4 / 2 → **1.4 / 7.0 / 7** | 1 → 1 | 51 → 39 | 13 → 13 |
| 10 | 277.7 / 1046.5 / 1135 → **0.4 / 0.8 / 3** | 100 → 167 | 69 → 121 | 101 → 119 |
| 40 | 3316.5 / 7685.9 / 7980 → **0.7 / 17.1 / 55** | 100 → 699 | 96 → 255 | 289 → 470 |

#### Client: CPU and frames

| Game | Idle lobby (ms CPU/s) | Idle table (ms CPU/s) | Play (ms CPU/s) | Frame avg / p95 (ms) | Warm reload: requests (304s) |
|---|---|---|---|---|---|
| ttr | 12.1 → **0.2** | 61.0 → **0.0** | 91 → **101** | 16.7/16.8 → 16.7/16.7 | 19 (11) → **5 (0)** |
| pandemic | 0.2 → **0.2** | 5.8 → **5.1** | 81 → **87** | 16.7/16.8 → 16.7/16.7 | 20 (16) → **4 (0)** |
| karak | 13.0 → **0.2** | 97.5 → **149.7** | 149 → **186** | 16.7/16.8 → 16.7/16.7 | 20 (16) → **4 (0)** |
| codenames | 10.3 → **0.2** | 0.0 → **0.0** | 0 → **0** | 0.0/0.0 → 0.0/0.0 | 19 (14) → **9 (4)** |
| skyjo | 6.4 → **0.2** | 13.3 → **0.1** | 32 → **58** | 16.7/16.7 → 16.7/16.7 | 13 (9) → **4 (0)** |
| phase10 | 12.0 → **0.2** | 58.3 → **0.9** | 43 → **42** | 16.7/16.8 → 16.7/16.8 | 15 (11) → **4 (0)** |
| lostcities | 11.7 → **0.2** | 14.8 → **0.1** | 49 → **54** | 16.7/16.8 → 16.7/16.8 | 14 (10) → **4 (0)** |
| toybattle | 14.7 → **0.2** | 129.5 → **0.7** | 60 → **86** | 16.7/16.7 → 16.7/16.7 | 16 (12) → **4 (0)** |
| sumo | 10.5 → **0.2** | 5.2 → **0.1** | 21 → **30** | 16.7/16.7 → 16.7/16.7 | 15 (11) → **4 (0)** |
| avenue | 14.5 → **0.2** | 37.6 → **68.3** | 46 → **60** | 16.7/16.7 → 16.7/16.7 | 17 (13) → **4 (0)** |
| skyteam | 0.3 → **0.6** | 0.0 → **0.0** | 0 → **0** | 0.0/0.0 → 0.0/0.0 | 14 (10) → **4 (0)** |

#### Client: loading over a tunnel (60 ms RTT, 9 Mbit/s)

| Game | Cold: game kB | Cold: shell + thumbnails kB | Cold load (ms) | Warm: requests (304s) | Warm load (ms) |
|---|---|---|---|---|---|
| ttr | 262 → **111** | 670 → **283** | 1559 → **1041** | 19 (11) → **5 (0)** | 661 → **343** |
| pandemic | 462 → **160** | 670 → **283** | 1953 → **1156** | 20 (16) → **4 (0)** | 724 → **348** |
| karak | 279 → **87** | 670 → **283** | 1749 → **1201** | 20 (16) → **4 (0)** | 787 → **373** |
| codenames | 297 → **217** | 670 → **283** | 1477 → **989** | 19 (14) → **9 (4)** | 653 → **361** |
| skyjo | 91 → **28** | 670 → **283** | 1387 → **902** | 13 (9) → **4 (0)** | 638 → **361** |
| phase10 | 139 → **41** | 670 → **283** | 1539 → **997** | 15 (11) → **4 (0)** | 656 → **317** |
| lostcities | 129 → **38** | 670 → **283** | 1594 → **1141** | 14 (10) → **4 (0)** | 661 → **356** |
| toybattle | 191 → **54** | 670 → **283** | 1545 → **1033** | 16 (12) → **4 (0)** | 661 → **380** |
| sumo | 107 → **33** | 670 → **283** | 1535 → **1116** | 15 (11) → **4 (0)** | 668 → **357** |
| avenue | 181 → **52** | 670 → **283** | 1617 → **1028** | 17 (13) → **4 (0)** | 710 → **354** |
| skyteam | 128 → **40** | 670 → **283** | 1425 → **1008** | 14 (10) → **4 (0)** | 660 → **360** |

#### Client: long sessions

| Game | JS heap after GC, start → end of 60 s fast play (MB) | DOM nodes start → end | After back to selection |
|---|---|---|---|
| ttr | 2.0 → 2.2 | 2415 → 4961 | 1 document, 340 nodes, 0.9 MB |
| pandemic | 3.6 → 4.5 | 2682 → 13852 | 1 document, 340 nodes, 0.9 MB |
| karak | 2.2 → 2.7 | 5490 → 14359 | 1 document, 340 nodes, 0.9 MB |
| skyjo | 1.5 → 1.7 | 572 → 2456 | 1 document, 340 nodes, 0.9 MB |
| phase10 | 1.6 → 1.8 | 831 → 1941 | 1 document, 340 nodes, 0.9 MB |
| lostcities | 1.7 → 1.9 | 3892 → 10194 | 1 document, 340 nodes, 0.9 MB |
| toybattle | 2.0 → 2.2 | 7198 → 16205 | 1 document, 340 nodes, 0.9 MB |
| sumo | 1.7 → 1.7 | 1314 → 1473 | 1 document, 340 nodes, 0.8 MB |
| avenue | 1.8 → 2.1 | 1763 → 4242 | 1 document, 340 nodes, 0.8 MB |

Reading the client tables: "idle" windows are 8 s at the player's turn with no game events (re-measured when bots
were still moving). Idle costs at Karak and Avenue depend on the board (how much repaints with the pulse): the same
page with and without the old timer loop measures the same (Karak 147/150, Avenue 65/64 ms/s). "Play" is unchanged:
the two sessions ran under different machine load (±30%); back to back, base vs new: Skyjo 62–63 vs 58–60, Toy
Battle 70–76 vs 70–77 ms/s. The capacity rows with search bots use more CPU after the change because the bots now
get the cores they were starved of. DOM nodes during long sessions grow with the game log (§1); everything is freed
when the game's frame closes.

## 4. Regression evidence

- `uv run pytest -n 8`: 925 passed (921 before + `test_table.py`: think inline/off-loop, stale thoughts, worker
  bots continue their random generator exactly; `test_server.py`: versioned links, import map, modulepreloads,
  immutable vs revalidated caching, 304s, path traversal, version changes on edit).
- `scripts/platform/ui_check.py`: two players through every game, no JavaScript errors.
- Every game's `ui_check.py` (avenue, codenames, karak, lostcities, pandemic, phase10, sumo, toybattle, ttr) and
  Pandemic's `flow_check.py` (three people, a phone, a spectator who reloads) pass.
- `compare_shots.py`: 32 demo stages × 2 sizes (64 shots) against the previous commit. Codenames, Pandemic, Sumo, TTR and every
  lobby are pixel-identical; Karak and Phase 10 differ by ≤ 0.05% (the same as two runs of the same checkout: an
  animation's phase); Lost Cities "draw" by 0.9–1.7% (the bobbing deck caught at another height); Toy Battle and
  Avenue play time-budgeted bots, so their later stages are different games (5–15% between two runs of the same
  checkout); looked at by eye, they match. The only intended difference is the Toy Battle bag glow.
- `perf_check.py`: all budgets met.

## 5. What is still expensive, and why it stays

| Cost | Why it stays |
|---|---|
| Search bots burn 1–1.5 s of a core per move (Sumo ~85 s per game, Toy Battle/Avenue ~10–20 s) | It is their strength: a time budget. Making the search faster would make them stronger. The owner chose to keep them as they are. |
| Karak's current-hero ring (SVG `opacity` pulse) and Avenue's pickable-card glow (`box-shadow` on a card with `overflow: hidden`) keep the page repainting at an idle table: Karak ~100–180, Avenue ~40–90 ms CPU/s, depending on the board | Chrome doesn't composite SVG children; Avenue's card clips any pseudo-element glow. Either needs the element moved out of the board / card (DOM restructuring in the game). Codenames' "your turn" status bar has the same `overflow: hidden` limit. |
| Rendering during bot play: 20–170 ms CPU/s, mostly Layerize + Paint of large SVG boards | 60 fps with no jank already; flattening static board art into images would cut it, at a real risk to the look |
| Google Fonts: 115–275 kB and two extra connections on a cold load | Self-hosting the (OFL) fonts would save the connections; the browser caches them across loads anyway |
| Memory while search bots play (+18 MB per concurrent worker) | The price of not sharing one core; released after 2 idle minutes |
| Phase 10 and Karak send 0.4–0.9 MB per player per game | Fine at ~0.3 kB/s; a diff protocol isn't worth eleven client rewrites (see §1) |
| Pandemic's table runs a few timers per second while waiting (0.1–10 ms CPU/s, as before) | Small and pre-existing; not traced to a single cause yet |
| Sky Team's table ticks every 0.5 s for its real-time clock | ~2 wakeups/s per Sky Team table; an exact wake-up would move its timeout by up to half a second |

## 6. Next steps

| Step | Expected gain | Effort |
|---|---|---|
| Move Karak's ring and Avenue's/Codenames' glows into composited layers (an HTML overlay or restructured card) | idle table Karak −100–180, Avenue −40–90 ms CPU/s | medium per game, needs screenshot review |
| Self-host the web fonts (woff2 in the platform's static folder, versioned) | −1 DNS + 2 TLS handshakes on cold loads (~150–300 ms over a tunnel) | small |
| Lazy-import Skyjo's numpy policy catalogue and Karak's neural bot until a table picks them | −8 MB idle server | small |
| Calibrate the search bots to node budgets equal to their current strength on this machine | ~same strength, deterministic, and then free to make the search faster (CPU −50% or more) | large; owner decision |
| Flatten static board art (Karak tiles, Toy Battle terrain) into one image per board | play CPU −30–50% in those games | large, visual risk |
