# SMA-898 — Mobile story click-through is 1/3 of desktop: 0.07 vs 0.19 click_story per session

Linear: SMA-898, project "World News Map" (f6a4e139-b47a-4043-a00b-ec0526445d8c), team SMA.
Repo: ~/workspace/global-news-map-service. Work in the worktree
~/workspace/global-news-map-service-wt-sma898-mobile, branch cc/sma898-mobile-ctr
(based on develop, currently at origin/main 55ecff1). Do NOT push to main; open a PR
branch → main at the end. Do NOT merge.

## Problem (GA daily loop, updated 2026-11-28)

Mobile is 83% of the audience but barely clicks through to stories.

* Last 7d: mobile 270 users / 272 sessions, 19 click_story = **0.07/session**;
  desktop 46 users / 56 sessions, 11 click_story = **0.20/session**.
* Overall: click_story=30 vs stories_shown=398 (~8% CTR). Users pick countries fine
  (select_country=339) but on mobile they rarely tap a story.
* Mobile engagement is otherwise strong (85% engaged sessions), so this is not a
  dead audience — the story tap itself is the weak step.
* Spike-day confirmation: on Nov 25 (219 users, almost all mobile, landing on
  /country/cambodia from a Facebook Messenger share) CTR was **7 click_story /
  247 stories_shown (2.8%)** — even worse than the 7d average.

## Diagnosis already done by the daily loop — verify it, do not redo from zero

The loop read the story tap path in `app/static/app.js` / `app/static/style.css`:

* Whole-card click already exists (SMA-566): tapping anywhere on a card opens the
  story (`window.open`, `_blank`) and fires click_story. An explicit
  "Read the full story at {source} →" CTA also exists (SMA-566). So the missing
  piece is NOT "no click cue on the card".
* Mobile layout is single-column (media query ≤900px): map on top, story panel
  below it. `stories_shown` fires on every panel render whether or not the panel
  is visible — so mobile impressions are counted even when the stories are below
  the fold.
* `pendingPanelScroll` scrolls the panel into view on explicit post-boot selection
  ONLY (`navBooted && !restoringPop`). On boot — including a /country/<slug>
  deep-link landing, which is where the spike traffic arrived — there is NO
  scroll: the visitor sees the map first and must scroll down to reach the
  stories, while `stories_shown` has already fired.

Leading hypothesis: on mobile country deep links, most visitors never scroll the
story panel into view, so most counted impressions are never seen — the CTR
denominator is inflated and the tap never gets a chance. Verify this with a real
mobile-viewport check (below) and refute or confirm it with measurements before
choosing the fix.

## Task

1. **Measure first.** Load /country/cambodia (and the homepage country-select flow)
   at a ~390px mobile viewport in headless Chromium and record: is the first story
   card in the viewport on load? After a country tap? How far must the user scroll
   to reach the first card? Do the same for desktop width as a control. Tooling:
   headless shell chromium-1234 is in ~/.cache/ms-playwright (screenshots + DOM
   dumps work); if you need scripted viewport measurement, a Playwright copy lives
   in the netflix-party checkout's extension/node_modules (load with
   createRequire) — check it exists before relying on it. For live-site checks
   through headless Chromium, route external requests via the chain proxy
   http://127.0.0.1:8898 with bypass localhost (verified up); localhost needs no
   proxy. If no viewport tooling works, say so explicitly instead of guessing.
2. **Ship ONE concrete fix aimed at the diagnosed friction.** Likely shape: on
   mobile country/region deep-link loads, bring the story panel into view after
   the boot render (the panel is the content the visitor came for). Hard
   constraint from SMA-689: do NOT reintroduce auto-scroll on the world boot
   render — the welcome hook and map must stay visible on first load of `/`.
   Scope the scroll to deep-link country/region loads only, or an equivalent
   that does not touch the `/` boot experience. If measurement refutes the
   below-fold hypothesis, ship the fix the actual diagnosis supports instead —
   but exactly one fix, not a bundle.
3. Do NOT: change the events fired (click_story/stories_shown semantics stay as
   they are — the loop measures against them), redesign the page, touch feeds,
   crawl timing, or spend money.
4. Verify locally (uvicorn — use port **8012** to avoid clashing with a parallel
   session): curl the country page, re-run the mobile-viewport measurement against
   the local server and confirm the first story card is reachable/visible per the
   fix's intent. Run the repo test suite and confirm green; add a regression test
   if the suite has a natural place for one.

## Verify

1. Mobile-viewport measurement (before/after) documented with numbers.
2. Test suite green.
3. Commit, push branch `cc/sma898-mobile-ctr`, open a PR to main. Do NOT merge.
4. On Linear issue SMA-898, leave a comment listing: the measured diagnosis
   (viewport numbers before/after), the one fix shipped and why, and that the
   loop will judge it on next runs' mobile click_story/session.
   Use the Linear MCP CLI (`linear call-tool --name save_comment
   --arguments-json '{"issueId":"SMA-898","body":"..."}'`).

## Acceptance criteria (from SMA-898)

1. Diagnose: what tapping a story looks like on a phone — measured, not assumed.
2. Ship one concrete mobile story-UX fix aimed at the diagnosed friction.
3. Next loop run: mobile click_story/session moves up from 0.07, or a concrete
   blocker is documented.
4. No spend, no user approval needed.

Report the PR URL and what changed.
