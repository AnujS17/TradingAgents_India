# v2: Global Run Cache Sharing — Deferred Design

**Date:** 2026-08-29
**Status:** Deferred — not scheduled. Revisit once concurrent multi-user traffic makes duplicate per-user runs on popular tickers cost real money.
**Depends on:** `docs/superpowers/specs/2026-08-29-auth-rbac-design.md` (Phase 1 — auth, roles, ownership) shipped first.

## Why this exists

Before auth, `POST /analyze` served a cached run to *any* caller asking about the same ticker/date/profile — a global cache. Its own docstring names this as deliberate: *"two users asking the same question get the same answer rather than two independently sampled verdicts,"* and it is *"what makes on-demand analysis affordable for a public audience."*

Phase 1 (private, per-user runs) intentionally gives this property up in favour of a simpler ownership model: every user's cache lookup is scoped to their own runs, so two different users asking about the same stock on the same day each spend their own run. That's a known, accepted cost regression versus the old behaviour — acceptable while there's no real concurrent user base to make the duplication expensive.

This document is what to build **when it stops being acceptable**: enough users, asking about enough of the same popular tickers, that redundant LLM spend on identical questions is a real line item.

## Design

**Keep runs owned by one user (who "paid" for it, for future billing), but let a cached hit be *shared* with other requesters without duplicating the run.**

### New table: `run_viewers`

| Column | Type | Notes |
|---|---|---|
| `run_id` | String(32), FK → runs.id | |
| `user_id` | String(32), FK → users.id | |
| `created_at` | DateTime(tz) | When this user first saw the shared run. |

Unique constraint on `(run_id, user_id)`.

### Behavioural change

`POST /analyze`:
1. `store.find()` becomes **global again** (any completed run for that ticker/date/profile, regardless of owner) instead of scoped to the requesting user.
2. On a hit: **do not** create a new `runs` row. Instead, upsert a `run_viewers` row `(run_id, requesting_user_id)`. Return the existing run exactly as today's no-auth behaviour does (200, not 202 — no new run was spent).
3. On a miss: behaves exactly like Phase 1 — a new run is created, owned by the requesting user.

`GET /runs` (and any other "my runs" listing):
- Returns runs where `user_id = caller` **OR** a `run_viewers` row exists for `(run_id, caller)`.
- Ownership (`user_id`) still identifies who originally spent the run — relevant for future per-user cost accounting / billing.

Per-run endpoints (`GET /runs/{id}`, `/stream`, `/export.*`, `/stop`, `/resume`) treat "owner OR has a viewer row" as the access-grant condition, same shape as Phase 1's "owner or admin" check, just OR'd with one more condition.

### Why not just make runs public read-only to everyone

Considered and rejected: it would leak which tickers *any* user has looked at to *every* user (via `GET /runs` or history endpoints), even ones they never asked about. The `run_viewers` design only grants visibility to users who **actually asked the question that produced the hit** — visibility follows a real request, not blanket exposure.

### Testing additions (on top of Phase 1's suite)

- User B requests a ticker/date user A already analysed → gets A's run, 200 (not 202), a `run_viewers` row is created, no new `runs` row exists.
- User B's `GET /runs` now includes that shared run; a third user C who never requested it does not see it.
- Re-requesting the same shared run a second time does not duplicate the `run_viewers` row (idempotent upsert / unique constraint holds).
- `force=true` still always spends a fresh run for the requester (existing accumulate-don't-replace behaviour), and does **not** create a viewer row on top of that — the requester now owns their own new run instead.

### Open question carried into this design

Should `run_viewers` rows ever expire, or accumulate forever? Unbounded growth is one row per (run, distinct viewer) — likely fine at any realistic scale, but worth a glance once real usage data exists rather than guessing now.
