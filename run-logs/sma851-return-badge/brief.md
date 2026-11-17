# SMA-851: Return badge never clicked — diagnose the return path

Linear: SMA-851 — "Return badge never clicked: return_badge_click=0 in 7d despite 4 return_visit events and 7 returning users"
Repo: spuffy-stl/global-news-map. Base branch: `develop`. Work in
this worktree on branch `cc/sma851-return-badge`. Open a PR to `main` when done.
Do NOT merge — the orchestrator reviews and merges.

## Decision (already made, do not re-litigate)

Daily loop 2026-11-17, GA 7d: 77 users, 84 sessions, 49 engaged. Returning
users 7 of 77 (9%), return_visit=4 events — the return path fires and GA
agrees. But return_badge_click=0 in 7d, as in every prior window.

## Read first (the leading hypothesis — verify it, do not assume it)

- `app/static/app.js` around lines 60–140 (return-visit hook: `fireReturnVisit`,
  `updateFreshBadge`, the `freshBadge` click handler, SMA-587 scroll-to-new),
  line ~987 (world view calls `updateFreshBadge`), and lines ~1621–1632
  (deep-link landings call `fireReturnVisit(items, false)`).
- `app/sessions.py` (server-side session/event log from SMA-816 — the
  measurement source of truth for what returning sessions actually saw).

Hypothesis from the orchestrator's code read: the badge can only ever show on
the world view — `updateFreshBadge` calls `fireReturnVisit(items, true)`,
while deep-link landings (`/country/<slug>`, `/region/<slug>`) call
`fireReturnVisit(items, false)`. AI Assistant is 52% of sessions and organic
search lands on country pages too, so most returning visitors may never see
the badge at all — 0 clicks could mean ~0 impressions, not disinterest.
Verify against the session log before changing anything: count returning
sessions in the recent window and how many showed the badge (i.e. fired
return_visit from a world view with new stories) vs fired return_visit from a
deep-link landing.

## Change

1. If the log confirms the badge is (near-)never shown: make the return badge
   reachable for deep-link returns too — show it on country/region views when
   a returning visitor has new stories, with the same "N new since your last
   visit" copy. Keep the existing event schema: `return_visit` fires as
   today, a badge click fires `return_badge_click`.
2. The SMA-587 click behaviour (scroll first NEW story into view + flash)
   must keep working from wherever the badge now shows. On a country view
   the NEW stories are that country's — scroll within the visible list; if
   no NEW card is in view, scrolling to the top of the list (or doing
   nothing beyond hiding the badge) is acceptable — say which you chose in
   the PR. Do NOT change what counts as a return (30-min gap, SMA-779), do
   NOT change the NEW-dot logic, do NOT touch feeds, the hook, or the
   trending strip.
3. If the log does NOT confirm the hypothesis (badge is shown regularly and
   still never clicked), do NOT build the deep-link change: report the
   measured impression count and the most likely cause with evidence, and
   propose the fix in the PR body instead of shipping a guess.
4. No new data collection, no spend, no new service.

## Verify locally (before pushing)

- `node --check app/static/app.js` (or equivalent syntax check);
  `python3 -m py_compile` every touched Python file.
- Start the app with uvicorn and curl the homepage + a /country/ page:
  confirm the badge path renders and the map/stories still load.
- Verify the click path headlessly if a harness exists in the repo
  (check how SMA-657 verified the deep-link return_visit firing); at
  minimum confirm the click handler fires `return_badge_click` by
  inspecting the session log / event path after a simulated returning
  visit. Do not claim a live-user result — report exactly what was
  verified locally.
- Confirm no regression: world-view badge still shows on return with new
  stories, hook still shows, trending strip still tracks.

## Deliver

- Commit on `cc/sma851-return-badge` with message
  `SMA-851: show return badge to deep-link returning visitors` (or, if the
  hypothesis was disproven, `SMA-851: diagnose return badge zero clicks`
  with the findings-only change — say which in the PR).
- Push the branch, open a PR to `main` with `gh pr create` titled
  `SMA-851: return badge for deep-link returning visitors` (or the
  diagnose title if applicable), body: the measured badge-impression
  count from the session log, what changed and where the badge now shows,
  how the click is tracked, and the file list. Stop after the PR opens;
  do not merge.
- If any step fails (test failure, `gh` auth, push rejection), report exactly
  what failed and stop — do not force anything.
