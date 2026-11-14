# SMA-829: Internationalize the site by visitor language and translate all headlines into the visitor's language

Linear: SMA-829 — "Internationalize the site by visitor language and translate all headlines into the visitor's language"
Repo: spuffy-stl/global-news-map. Base branch: `develop` (HEAD 6c689bd). Work in
this worktree on branch `cc/sma829-i18n-translation`. Open a PR to `main` when done.
Do NOT merge — the orchestrator reviews and merges.

## Decision (already made, do not re-litigate)

User decision (voice call 2026-11-13): the site should detect each visitor's
language and translate all headlines into the language the visitor speaks.
English is the default/fallback. The point: an English reader reads world news
in English; a Korean reader in Korean — same trusted local outlets per country,
every headline in the reader's language.

## Read first

- `app/main.py` (server + routes), `app/crawler.py` (6-hourly crawl),
  `app/db.py` (storage — confirm engine/schema for stories), `app/sessions.py`
  (session/event logging), `app/static/index.html` + `app/static/app.js` +
  `app/static/style.css` (frontend), `app/sources.yaml` (141 countries,
  233 feeds). Understand how a headline flows from feed → DB → API → page
  before designing anything. Do not assume the storage shape — read it.

## Recommended design (adopt unless you find a concrete reason not to, and say so in the PR)

1. **Language detection, priority order:** saved preference (cookie /
   localStorage, set by the switcher) > `Accept-Language` header > IP-based
   geo (best-effort only, if a lookup is already available — do NOT add a
   paid geo service) > English default.
2. **UI chrome i18n:** labels, buttons, and region/country names where
   sensible, driven by the detected language, with a visible language
   switcher that overrides and persists. Start with the languages the
   translation provider handles; English + Korean must work on day one.
3. **Headline translation — lazy, per-language, cached:** do NOT pre-translate
   into N languages at crawl time. Translate on first request for a given
   (headline, language) pair and persist the translation in the DB next to
   the original, so a headline is never translated twice. Only new headlines
   get translated, only when a visitor actually asks for that language.
4. **Original always retrievable:** the original-language headline stays
   stored and reachable in the UI (show alongside, or on hover/click — pick
   the least intrusive option and say which in the PR).
5. **Translation provider:** evaluate Google Cloud Translation API vs the
   obvious alternatives on cost at current crawl volume and pick the
   cheapest reliable one. No new paid service is enabled by this PR.

## Hard constraints (do not violate)

- **Privacy:** detect language from IP at request time only. NEVER store IPs,
  never log per-visitor language history, no persistent cross-session
  identifiers. (Analytics stance: no PII.)
- **Cost — flag-gated, DEFAULT OFF:** all live translation spend sits behind
  a flag / env var, default OFF. With the flag off, the site behaves exactly
  as today (original-language headlines, English UI). The PR body MUST report
  the estimated monthly cost at current volume (233 feeds, 6-hourly crawl,
  new-headlines-per-day measured from the DB) so the user approves the spend
  before anyone enables it. No translation spend is incurred by merging.
- **No regressions:** 6-hourly crawl cadence, feed health checks, and the
  session/event logging in `app/sessions.py` keep working. Do not change the
  analytics event schema, except adding the visitor language to the session
  record if it is trivial and clearly labelled.
- **No other behaviour.** No feed changes, no source changes, no CSS redesign
  beyond what the switcher needs.

## Verify locally (before pushing)

- `python3 -m py_compile` every touched Python file; `node --check
  app/static/app.js` (or equivalent syntax check).
- Start the app with uvicorn and curl the homepage with
  `Accept-Language: ko` and `Accept-Language: en`: confirm the UI strings
  and a known non-English headline come back translated (with the flag ON
  in a local test env), and that with the flag OFF everything renders
  exactly as today.
- Confirm the language switcher persists a choice across reloads and that
  the original headline is reachable for a translated story.
- Confirm a translated headline is served from cache on the second request
  (no second provider call).
- Confirm no IPs are written to any log, DB table, or analytics event
  (grep the diff for IP storage).

## Deliver

- Commit on `cc/sma829-i18n-translation` with message
  `SMA-829: internationalize by visitor language; translate headlines into the visitor's language (flag-gated, default off)`.
- Push the branch, open a PR to `main` with `gh pr create` titled
  `SMA-829: internationalize by visitor language + translate headlines`,
  body: detection order, provider choice + why, monthly cost estimate at
  current volume, what the flag controls, and the file list. Stop after the
  PR opens; do not merge.
- If any step fails (test failure, `gh` auth, push rejection), report exactly
  what failed and stop — do not force anything.
