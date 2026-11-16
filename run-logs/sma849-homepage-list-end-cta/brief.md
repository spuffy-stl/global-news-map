# SMA-849: Homepage world list is a dead end — add a list-end path to a country

Linear: SMA-849 — "Homepage world list is a dead end: 50 bot-free homepage sessions, 2% select a country, 0 click a story — add a list-end path to a country"
Repo: spuffy-stl/global-news-map. Base branch: `develop`. Work in
this worktree on branch `cc/sma849-homepage-list-end-cta`. Open a PR to `main` when done.
Do NOT merge — the orchestrator reviews and merges.

## Decision (already made, do not re-litigate)

Bot-free session log (SMA-816, last 100 sessions Nov 14–16): homepage starts
(n=50) select_any 1 (2%), click_story 0 (0%), stories_shown 43 (86%),
hook_explore 0, trending_click 0/17 since SMA-835 went live Nov 15; median
session 5s. Country-page starts (n=49) click stories at 10%. The GA signal
was NOT bot pollution — visitors land on /, read the world headlines in
place, and leave without touching the map or a story. The world list is
already clickable (whole-card click + title links + Read-full-story CTA all
fire click_story — verified in app/static/app.js), so 0/50 is behaviour, not
a missing handler. Add ONE next step at the end of the homepage world list
that routes the reader toward a country.

## Read first

- `app/static/app.js` — note `renderStories()` / `storyCard()` (world level
  renders 15 stories), the trending-strip click handler (SMA-835, around
  app.js:262-275), the session/event tracking (`trackEvent`, `click_story`,
  `trending_click`), and how `selectCountry` is invoked from a map click so
  the new affordance can reuse the same path.
- `app/static/index.html` + `app/static/style.css` (homepage layout — where
  the world list ends and what the visitor sees after it), `app/main.py`
  (server + routes), `app/sessions.py` (server-side session/event log — the
  measurement source of truth). Do not assume the storage or event shape —
  read it.

## Recommended design (adopt unless you find a concrete reason not to, and say so in the PR)

1. **One affordance, world level only:** at the end of the homepage world
   story list (level=world, after the 15 stories — not on country/region
   views), add a clear next step toward a country, e.g. a "Pick a country
   on the map to see its local headlines" prompt that focuses/highlights
   the map, or the equivalent single element. Keep copy short, in the
   existing i18n pattern if the surrounding strings are translated
   (check how `tr()` is used in app.js; do not invent a second i18n path).
2. **Do NOT** change what the world list shows, do NOT make world stories
   open country pages instead of the article, do NOT touch feeds, sources,
   the trending strip, or the hook. No redesign beyond what the one
   affordance needs.
3. **Tracking:** the affordance click must be measurable with the existing
   event schema (a clearly-labelled new event such as `world_list_cta_click`,
   or the existing select path if it fits) so the next daily loop can
   measure homepage-start select_any against the 2% (1/50) baseline.
   Do not change the analytics event schema except adding this one event.
4. **No new data collection, no spend, no new service.** Keep the homepage
   fast — the affordance must not add a data fetch or slow query to first
   paint.

## Verify locally (before pushing)

- `python3 -m py_compile` every touched Python file; `node --check app/static/app.js` (or equivalent syntax check).
- Start the app with uvicorn and curl the homepage: confirm the affordance
  renders at the end of the world list on `/` only (not on a /country/
  page), the map still renders, and world stories still load.
- Confirm the affordance click fires the tracked event (check the session
  log / event path) and that it leads somewhere real (map focus or a
  country selection — no dead click).
- Confirm no regression: trending strip still renders and tracks, hook
  still shows, crawl/feed health untouched.

## Deliver

- Commit on `cc/sma849-homepage-list-end-cta` with message
  `SMA-849: add list-end path to a country on the homepage world list`.
- Push the branch, open a PR to `main` with `gh pr create` titled
  `SMA-849: list-end path to a country on the homepage world list`, body:
  what the affordance is and where it renders, how the click is tracked,
  what the baseline was (2% homepage-start select, 0/50 story clicks),
  and the file list. Stop after the PR opens; do not merge.
- If any step fails (test failure, `gh` auth, push rejection), report exactly
  what failed and stop — do not force anything.
