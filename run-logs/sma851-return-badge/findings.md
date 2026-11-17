# SMA-851 findings: return badge zero clicks

Measured 2026-11-17 from the production session log (SMA-816), read-only via
`GET https://globalnewsmap.net/api/analytics/sessions?limit=100`.

## Window

The endpoint caps at 100 sessions, which covered 2026-11-15 09:21 →
2026-11-17 14:08 UTC (~2.2 days). That's not the GA 7d window. No other
read path to `sessions.db` was used (no new data collection).

## Counts

| | |
|---|---|
| Sessions | 100 (landing: 39 `/`, 44 `/country/*`, 1 `/region/*`, 16 with no landing event) |
| `return_visit` events | 3, in 2 sessions |
| …fired from a world-view landing (`/`) with `new_count > 0` (the badge was shown) | **3** |
| …fired from a deep-link landing (`/country/*`, `/region/*`) | **0** |
| `return_badge_click` | 0 |

Every return in the window came from a world view and had new stories, so
the badge rendered every time (`fireReturnVisit(items, true)` with n=15).
There were 45 deep-link sessions and none was a returning visitor (SMA-657
fires `return_visit` for deep-link returns, so any would show up). Within
this window the hypothesis that the badge is never shown is **not
confirmed**: there were 3 impressions and 0 clicks.

## The two returning sessions

```
b4e166df  11-16 14:37:34 session_start {path: /}
          11-16 14:37:34 return_visit  {hours_away: 553, new_count: 15}
          11-16 14:37:34 stories_shown {level: world, count: 15}
          11-16 15:23:13 session_end   {path: /}          # 46 min, zero interaction

43fe96ac  11-15 14:05:00 session_start {path: /}
          11-15 14:05:00 return_visit  {hours_away: 550, new_count: 15}
          11-15 14:05:00 stories_shown {level: world, count: 15}
          11-15 14:06:05 search_story  {country: Chile}  -> select_country Chile
          11-15 14:06:45 session_end   {path: /country/chile}
          11-15 14:06:45 page_load     {path: /}
          11-15 14:06:46 return_visit  {hours_away: 550, new_count: 15}   # again
```

## Most likely cause

1. **These "returning" clients don't look like real returning humans.**
   43fe96ac fired `return_visit` a second time 1m46s after the first, with
   the same `hours_away: 550`. If the 14:05 `stampVisit()` had persisted, the
   SMA-779 30-minute gate would have blocked the second fire. So this
   client's localStorage write didn't survive a full page load in the same
   tab. That pattern fits an automated/agent browser restoring a snapshotted
   profile (its stamp is ~23 days old, ~Oct 23–24), not a person returning.
   b4e166df sat idle for 46 minutes with no interaction at all. Both
   `hours_away` values (~550h) are far outside a daily-return cadence.
2. **When the badge does show, it adds nothing to click for.** With a
   ~23-day-old stamp, `new_count` = 15 = every story on the world list. Each
   card already carries a NEW dot and the list is right below, so "15 new
   since your last visit" scrolls to the first card on screen.
3. **The badge reads as a dismiss control.** `index.html` gives it
   `title="Dismiss"`, and it sits at the top-right among status chrome
   (next to the "Updated …" line). There's no arrow or verb to suggest it
   leads anywhere.

## Proposed fix (not shipped)

- First, measure the real audience. Have `return_visit` record whether the
  badge was shown (`badge: 0/1`; needs a prop allow-list entry, which is a
  small data-collection change, so it needs approval). Also re-run this count
  when the window holds >1 week (raise the endpoint's `limit` cap or add a
  date filter) before building more UI on 2–3 events.
- Only if real returners are confirmed, rework the affordance: show the
  badge only when `new_count` is a meaningful subset of the list (e.g.
  `0 < n < items.length`), drop `title="Dismiss"`, and phrase it as an
  action (“See 4 new stories ↓”).
- Don't build the deep-link badge yet. This window had 0 deep-link returns,
  so it would add 0 impressions.
