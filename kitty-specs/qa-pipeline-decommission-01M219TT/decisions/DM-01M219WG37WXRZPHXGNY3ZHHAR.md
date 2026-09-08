# Decision Moment `01M219WG37WXRZPHXGNY3ZHHAR`

- **Mission:** `qa-pipeline-decommission-01M219TT`
- **Origin flow:** `specify`
- **Slot key:** `specify.teardown.webhook-timing`
- **Input key:** `webhook_teardown_timing`
- **Status:** `resolved`
- **Created:** `2026-09-08T20:03:24.391353+00:00`
- **Resolved:** `2026-09-08T20:07:55.958752+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

Stop the qa-dispatch-webhook and close the Funnel immediately (pre-mission manual action), or as the mission's ordered deploy step?

## Options

- Immediately, before the arc continues
- As the mission deploy step
- Other

## Final answer

As the mission deploy step — ordered, manifest-driven teardown with archive-first and pre/post verification

## Rationale

_(none)_

## Change log

- `2026-09-08T20:03:24.391353+00:00` — opened
- `2026-09-08T20:07:55.958752+00:00` — resolved (final_answer="As the mission deploy step — ordered, manifest-driven teardown with archive-first and pre/post verification")
