# Authentication and RBAC — Design Spec

**Date:** 2026-08-29
**Status:** Approved for planning
**Scope:** Phase 1 only — authentication, roles, and run ownership. Explicitly NOT billing, NOT an admin dashboard, NOT per-tier limit enforcement.

## Goal

Bench currently has **no authentication of any kind**. Every API route is open, and the only guardrail is an IP-based daily run cap (`api/ratelimit.py`), which its own docstring describes as "spoofable... a cost guardrail, not a security control." Since each analysis spends real LLM money, and the product is heading toward paying customers, identity has to exist before anything else can be built on top of it.

Phase 1 delivers: users sign in with Google, every run belongs to a user, users see only their own runs, and the data model carries the `role` and `tier` fields that later phases (billing, admin tooling, tier limits) will read.

## Non-Goals

These are deliberately excluded to keep Phase 1 shippable. Each is a separate future project:

- **Billing / payments.** Depends on auth existing; its own subsystem.
- **Admin dashboard UI.** The `admin` role will exist and be enforceable, but no screen consumes it yet.
- **Per-tier rate limit enforcement.** `tier` is stored but does not yet change behaviour. The existing IP-based cap stays exactly as-is.
- **Email/password, magic links, other OAuth providers.** Google only.
- **Team/organisation accounts.** Single-user accounts only.

## Architecture

**Chosen approach: NextAuth.js in the frontend, JWT verified independently by FastAPI.**

Bench is a split deployment — a Next.js app (`:3000`) and a separate FastAPI backend (`:8000`) that the browser calls **directly**. The backend therefore cannot trust the frontend; it must verify identity itself.

```
Browser ──"Sign in with Google"──► NextAuth (Next.js)
                                        │
                                   Google OAuth
                                        │
                                        ▼
                            NextAuth issues signed JWT
                                        │
Browser ──Authorization: Bearer <JWT>──► FastAPI
                                        │
                            verify signature (shared secret)
                            → load User → attach to request
```

**Why this over the alternatives:**

- **vs. FastAPI owning the full OAuth flow:** Google's OAuth dance (redirect URIs, token exchange, refresh, CSRF state) is genuinely fiddly, and NextAuth is the mature, well-trodden library for exactly this shape. It also avoids cross-origin session cookies between `:3000` and `:8000` — the same class of `SameSite`/CORS problem that already caused a real outage in this project when the dev server moved to port 3001. Bearer tokens sidestep cookie-origin rules entirely.
- **vs. a managed provider (Clerk/Auth0):** `role` and `tier` need to be tightly coupled to the local `runs` table for ownership queries and future billing. Keeping the user table local avoids syncing an external identity store against our own foreign keys.

**Cost of this choice, stated plainly:** two layers know about auth, and the JWT signing secret must be shared between the Next.js and FastAPI processes. The mitigation is that FastAPI's half stays deliberately small — verify signature, look up user, done — and is fully unit-testable without a browser.

## Data Model

### New table: `users`

| Column | Type | Notes |
|---|---|---|
| `id` | String(32) PK | Generated locally, same scheme as `new_run_id()`. |
| `google_sub` | String(64), unique, indexed | Google's stable subject ID. The identity key — **not** email. |
| `email` | String(256), indexed | For display and admin lookup. Mutable at Google's end. |
| `name` | String(256), nullable | Display name. |
| `picture` | Text, nullable | Avatar URL. |
| `role` | String(16) | `user` \| `admin`. Default `user`. |
| `tier` | String(16) | `free` \| `paid`. Default `free`. |
| `created_at` | DateTime(tz) | |
| `last_login_at` | DateTime(tz), nullable | |

**`google_sub`, not email, is the identity key.** Google explicitly documents `sub` as the only stable per-user identifier; email addresses can be changed or reassigned. Keying on email would let an address change orphan an account, or in the worst case let a reassigned address inherit someone else's run history.

### Changed table: `runs`

Add `user_id: String(32), nullable, indexed, FK → users.id`.

**Nullable is deliberate and permanent**, not a migration convenience:
- Existing rows predate auth (backfilled — see Migration).
- Nullable keeps `_extract_verdict`-style worker paths from needing a user context they don't have.
- A future system/scheduled run has no human owner.

`requested_by` (currently the caller's IP) is **kept, not replaced**. It continues to serve IP-level abuse limiting, which stays useful even with accounts — one account behind many IPs and many accounts behind one IP are both signals worth keeping separate. Once `user_id` exists, per-user budgeting can layer on top without discarding the IP signal.

## Access Control Rules

Two roles, enforced at the route layer:

- **`user`** — full access to their own runs only.
- **`admin`** — everything a user can do, plus read/act on any run regardless of owner.

| Endpoint | Rule |
|---|---|
| `GET /health` | **Public.** Ops/uptime probes must not require a token. |
| `GET /push/vapid-public-key` | **Public.** A public key, by definition; needed before subscription. |
| `POST /analyze` | Authenticated. New run is stamped with `user_id`. |
| `GET /runs` | Authenticated. Returns **only the caller's** runs (admins: all). |
| `GET /runs/{id}`, `/stream`, `/export.pdf`, `/export.xlsx` | Authenticated + **owner or admin**. |
| `POST /runs/{id}/stop`, `/resume`, `/subscribe` | Authenticated + **owner or admin**. |
| `GET /runs/{ticker}/{date}`, `/history` | Authenticated + ownership-filtered (see below). |

**Not-found over forbidden.** A non-owner requesting someone else's run gets **404**, not 403. A 403 confirms the run exists, leaking which tickers other users have analysed — run IDs are enumerable-ish and ticker interest is commercially sensitive. The route reads as "this run does not exist *for you*."

### The cache-sharing tension (important)

`POST /analyze` currently serves a cached run to *any* caller asking the same ticker/date/profile, and its docstring names this as intentional: *"two users asking the same question get the same answer rather than two independently sampled verdicts,"* and it "is what makes on-demand analysis affordable for a public audience."

Ownership breaks that outright: if runs are private, User B cannot be handed User A's run, and the cost-saving disappears exactly when a user base makes it matter most.

**Resolution for Phase 1:** the cache lookup stays global (any user's completed run for that ticker/date/profile can satisfy a request), but **serving a cached run does not transfer ownership** — instead it creates a lightweight *reference* for the requesting user. Concretely: `store.find()` remains global; when it hits, a new `runs` row is **not** created, and instead the existing run is recorded as visible to this user via a `run_viewers` association (`run_id`, `user_id`, `created_at`, unique on the pair). `GET /runs` returns runs the user owns **or** has a viewer row for. Ownership (`user_id`) still marks who paid for it.

This preserves the cost model exactly, keeps the "same question, same answer" property, and still prevents a user from browsing runs they never asked for. The cost is one extra small table; the alternative — per-user duplicate runs — multiplies LLM spend by the number of users asking the same popular ticker, which is the opposite of the product's stated economics.

## First-Admin Bootstrap

The first user to ever sign in is created with `role="admin"`; everyone after is `role="user"`. Determined by a count on the `users` table inside the same transaction as the insert, so a race cannot mint two admins.

This is chosen over an env-var allowlist (`ADMIN_EMAILS=...`) because it needs no configuration and no secret to be correct at deploy time. Its risk — a stranger signing in before the owner does — is real but bounded to the single-operator, not-yet-public situation this ships into. **Before any public launch, this must be revisited** (documented as a follow-up in the plan), most likely by seeding the admin row at deploy time.

## Migration of Existing Data

~30 existing runs (HAL, SAIL, EXIDEIND, LENSKART, etc.) have `requested_by` set to an IP and no user. Per decision: **assign all of them to the first admin account.**

Executed by an idempotent startup migration alongside the existing `create_tables()` pattern in `api/db.py`, which already performs guarded `ALTER TABLE ... ADD COLUMN` calls for exactly this kind of evolution:
1. Create `users` and `run_viewers` tables if absent.
2. Add `runs.user_id` if absent.
3. On first admin creation, `UPDATE runs SET user_id = <admin_id> WHERE user_id IS NULL`.

Step 3 runs once, keyed on the admin's creation, so a later signup never re-triggers it. Alembic remains unnecessary at this schema velocity, consistent with the existing documented decision in `create_tables()`.

## Error Handling

| Case | Response |
|---|---|
| No/blank `Authorization` header on a protected route | 401 + `WWW-Authenticate: Bearer` |
| Malformed, expired, or bad-signature JWT | 401 |
| Valid JWT, `google_sub` not in `users` | 401 (deleted account; forces re-auth) |
| Authenticated but not owner/admin | **404** (see rationale above) |
| Auth backend misconfigured (missing secret) | Fail **closed** — 500 and refuse the request |

**Fail closed, always.** A missing or unparseable secret must never degrade to "allow the request." The startup path validates that the JWT secret is present and non-trivial, and refuses to boot without it, so this surfaces at deploy time rather than as a silent open door.

## Testing Strategy

Auth is security-critical and gets adversarial tests, not just happy-path ones.

**Backend (pytest, mirroring existing `tests/test_api_*.py` patterns):**
- Token verification: valid, expired, wrong-signature, malformed, missing, `alg: none` rejection.
- Route protection: every protected endpoint returns 401 unauthenticated — asserted by enumerating the router, so a **newly added route is protected by default** and a future unguarded endpoint fails the suite.
- Ownership isolation: **user B gets 404 for user A's run** on every per-run endpoint (get, stream, export ×2, stop, resume, subscribe).
- `GET /runs` returns only the caller's runs; admin sees all.
- Admin override grants access where a plain user gets 404.
- First-signin-becomes-admin; second signin does not.
- Migration: existing null-`user_id` runs land on the admin, and the backfill does not re-run on a later signup.
- Cache-share: user B requesting user A's already-analysed ticker gets the same run, gains a viewer row, and creates no duplicate run.

**Frontend (vitest):** unauthenticated users are redirected to login; the API client attaches the token; session-less state renders the signed-out nav.

## Files Affected

**New:** `api/auth.py` (JWT verification + `get_current_user`/`require_admin` dependencies), `tests/test_auth.py`, `tests/test_route_protection.py`, `tests/test_run_ownership.py`, `web/app/src/app/api/auth/[...nextauth]/route.ts`, `web/app/src/app/login/page.tsx`.

**Modified:** `api/db.py` (User/RunViewer models, migration), `api/schemas.py` (User schemas), `api/dependencies.py` + `api/store.py` (owner-scoped queries), `api/routers/runs.py` (dependencies on all routes), `api/settings.py` (JWT secret, Google client config), `api/ratelimit.py` (user-aware identity), `web/app/src/lib/api-client/client.ts` (attach bearer token), `web/app/src/app/layout.tsx` (session provider), nav components.

## Open Questions for Later Phases

1. When does per-tier limiting replace the flat IP cap?
2. Should `run_viewers` rows expire, or accumulate forever?
3. Admin bootstrap hardening before public launch (see above).
