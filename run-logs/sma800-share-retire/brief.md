# SMA-800: Retire the unused share UI

Linear: SMA-800 — "Share events still zero in 7d after Share UX v2 + wiring verification — diagnose or retire"
Repo: spuffy-stl/global-news-map. Base branch: `develop` (HEAD 6c689bd). Work in
this worktree on branch `cc/sma800-share-retire`. Open a PR to `main` when done.
Do NOT merge — the orchestrator reviews and merges.

## Decision (already made, do not re-litigate)

The panel-level Share button (SMA-445, pre-composed share text SMA-549) has
fired `share_country` exactly 0 times in every 7d GA window since it shipped,
0/100 sessions in the latest bot-free session-log window (Nov 12–13), while
`select_country` fired in 51/100 of those same sessions — the button is visible
on country views, the top landing surface, and still never used. Wiring was
verified twice (SMA-757, SMA-602). Diagnosis: nobody wants it. Retire the UI.

## Remove

1. `app/static/index.html` (~line 65): the `<button id="shareBtn" ...>↗ Share</button>`
   in the panel head. Leave the panelClose button.
2. `app/static/app.js`:
   - Line ~27: `var shareBtn = document.getElementById("shareBtn");`
   - Lines ~482–549: the whole share block — the SMA-445 comment,
     `CANONICAL_BASE`, `shareCountry`, `shareItems`, `setShareCountry`,
     `copyText`, `countryShareText`, and the `shareBtn` click handler.
     (Verify `CANONICAL_BASE` and `copyText` have no other uses before deleting.)
   - Line ~937: `shareItems = (level === "country") ? items : [];` (with its
     SMA-549 comment).
   - The `setShareCountry(...)` calls in `loadWorldHeadlines` (~968),
     `selectContinent` (~1013), `selectRegion` (~1039), `selectCountry` (~1066).
   - Lines ~888–893: update the SMA-690 comment — it currently says sharing
     "remains available at panel level (shareBtn, country views)". Change it to
     record that the panel share UI was retired in SMA-800 (zero use) and the
     per-card share pill was already removed in SMA-690.
3. `app/static/style.css` (~line 316): `#shareBtn.hidden { display: none; }`
4. `analytics/ga_report.py` (~line 24): remove `"share_country"` from EVENTS.
   (Precedent: `share_story` / `share_nudge_*` were deliberately removed from
   this list when their surfaces were removed, so their permanent 0s stop
   sending the loop on ghost hunts. Add a one-line note that the surface was
   retired in SMA-800.)

## Do NOT touch

- `app/sessions.py` (`share_country` in EVENTS + STAGES) and
  `analytics/sessions_report.py` (STAGES): the server-side funnel record stays,
  so the retirement stays measurable — the stage should read 0 forever, not
  vanish from the funnel record.
- `app/main.py` llms.txt copy ("shareable page"): that is about canonical
  country URLs, not the share button.
- No other behaviour. No new features, no copy changes, no CSS redesign.

## Verify locally (before pushing)

- `node --check app/static/app.js` (or equivalent syntax check).
- `python3 -m py_compile analytics/ga_report.py`.
- `grep -rn "shareBtn\|setShareCountry\|shareItems\|countryShareText\|share_country" app/static/ analytics/ga_report.py` returns nothing
  (except the intentional `share_country` entries in `app/sessions.py` and
  `analytics/sessions_report.py`, and the SMA-800 note in `ga_report.py`).
- Start the app with uvicorn and curl the homepage and one country page;
  confirm the served HTML/JS contains no `shareBtn` and the pages return 200.
- Confirm no other JS references a removed identifier (a grep for
  `shareCountry` / `CANONICAL_BASE` / `copyText` outside the deleted block
  must be empty).

## Deliver

- Commit on `cc/sma800-share-retire` with message
  `SMA-800: retire unused share UI (panel Share button, 0 uses in every window)`.
- Push the branch, open a PR to `main` with `gh pr create` titled
  `SMA-800: retire unused share UI`, body: one paragraph with the diagnosis
  (0 uses, wiring verified twice, button visible on country views) + the file
  list above. Stop after the PR opens; do not merge.
- If any step fails (test failure, `gh` auth, push rejection), report exactly
  what failed and stop — do not force anything.
