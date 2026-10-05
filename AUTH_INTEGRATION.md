# Auth Integration Contract

This backend delegates all authentication to an existing external service and stores **no credentials** locally.

> **Current call path (as of the frontend build):** the React frontend calls the external auth service **directly** from the browser (`frontend/src/lib/authServiceClient.ts`), not through this backend. `api/routes/auth.py` still exists and is fully functional as an alternate path, but the frontend doesn't use it. See [Call Path](#call-path-frontend-calls-the-auth-service-directly) below for why this changed and what it means for token handling.

## External Service

- Base URL: `https://authentication-api-zeta.vercel.app`
- Full endpoint reference: see that service's own `documentation/API_DOCS.md`.
- Auth model: email/password signup with email verification, OTP-based 2FA **enabled by default for every user**, JWT (HS256) session tokens, forgot/reset password via emailed links.
- CORS: confirmed wide open, so direct browser calls from the frontend work without extra configuration on the auth service.

## Call Path: Frontend Calls the Auth Service Directly

The React frontend (`lib/authServiceClient.ts`) calls `https://authentication-api-zeta.vercel.app` directly for signup/login/2FA/forgot-password/me/logout, unwrapping its `{msg, success, code, error, data}` envelope itself. This replaced an earlier backend-proxy design (see git history / `api/routes/auth.py`) once it was confirmed the auth service's CORS allows the frontend's origin directly.

Consequence: the auth service's own session cookie is set on `authentication-api-zeta.vercel.app`'s domain, not ours, so it never reaches this backend. The frontend instead holds the raw JWT itself (`lib/tokenStore.ts`, persisted to `localStorage`) and sends it as `Authorization: Bearer <token>` on every call to **this backend's** business-logic APIs (question bank, tests, attempts). `api/deps.py`'s `get_session_token` accepts the token from either the `Authorization` header (this path) or our own session cookie (the proxy path below), so both continue to work.

### The proxy path, still available

`api/routes/auth.py` still proxies `/api/auth/{signup,login,login/2fa-verify,forgot-password,me,logout}` to the same external service and sets an httpOnly cookie on successful login, exactly as documented further down. Nothing currently calls it, but it's kept working intentionally (e.g. for a future server-rendered client, or if direct browser calls to the auth service ever need to stop). Its trade-offs vs. the direct path:

| | Direct (current) | Proxy (`api/routes/auth.py`) |
|---|---|---|
| Moving parts | Frontend + auth service only | Frontend + our backend + auth service |
| Token storage | Raw JWT in frontend `localStorage` | httpOnly cookie, JS never sees the token |
| CORS | Needs the auth service to allow the frontend's origin (confirmed open) | Needs our backend to allow the frontend's origin only |
| XSS exposure | A script-injection bug could read the token from `localStorage` | Token never reachable from JS |

Implemented proxy routes (`api/routes/auth.py`), unchanged:

```text
POST   /api/auth/signup            -> proxies POST /v1/auth/signup
POST   /api/auth/login             -> proxies POST /v1/auth/otp/login
POST   /api/auth/login/2fa-verify  -> proxies POST /v1/auth/otp/login/2fa_verify, sets our session cookie on success
POST   /api/auth/forgot-password   -> proxies POST /v1/auth/forgot-password
GET    /api/auth/me                -> validated via cache / POST /v1/auth/me, returns our local profile shape
POST   /api/auth/logout            -> proxies DELETE /v1/auth/logout, clears our session cookie
```

Note: `/v1/auth/signup/set-password` and `/v1/auth/reset-password` are deliberately **not** proxied either way. The auth service's emails link directly to its own hosted HTML pages (`/pages/auth/set-password`, `/pages/auth/reset-password`), which post straight back to the auth service — the user never passes through our frontend or backend for those two steps.

## Token Validation

The auth service's session tokens are not purely stateless — `/v1/auth/me` checks the token against a server-side token log (to support single-use tokens and future revocation), so local JWT-signature verification alone isn't sufficient.

Approach: every protected request to our API triggers a validation step:

1. Read the token from `Authorization: Bearer <token>` (the direct-call path) or, failing that, our own session cookie (the proxy path) — see `api/deps.py:get_session_token`.
2. Look up `(token -> user profile)` in an in-memory cache, keyed by a hash of the token, TTL = `AUTH_CACHE_TTL_SECONDS` (default 60s).
3. On a cache miss, call `POST /v1/auth/me` with that token. On success, upsert the returned profile into the local `users` table (see `models/user.py`) and cache it. On `401`, respond `401` to the frontend (which clears its stored token).

This keeps autosave-heavy traffic (an API call per answer selection) from hammering the external service while still re-validating periodically.

## Session Expiry for Long-Running Exams

A full SSC CGL mock test runs 60–100+ minutes, but the auth service's session JWT defaults to a 15-minute expiry (`JWTTOKENEXPIRATIONMINUTES`), and re-login requires a fresh OTP since 2FA is mandatory for all users.

**Decision:** increase `JWTTOKENEXPIRATIONMINUTES` on the auth service deployment (it's owned by the same person building this platform) to comfortably exceed the longest test duration — e.g. **180 minutes** — rather than building any client-side workaround. This needs to be set as an env var on the auth service itself; it is **not** something this platform's codebase controls.

If that env var is ever reverted to the 15-minute default, exam-taking will break for any session older than 15 minutes — a user's `test_attempt` and all its `question_attempts`/timing data is still safe either way (the backend persists everything independent of the session), but they'd be forced through an OTP re-login mid-test.

## User Identity

- `user_id` from the auth service (e.g. `"AY12345678"`) is a short, auth-service-generated string — **not** a UUID. This platform stores it verbatim as the primary key of its local `users` table and as the FK target for `tests.created_by_user_id` and `test_attempts.user_id`.
- The local `users` row is a cache only (email, first_name, last_name, is_active), populated/refreshed on each successful `/v1/auth/me` validation. It is never the source of truth for identity or credentials.

## Data Scoping (default assumption — implemented, not yet confirmed)

Each user's tests, attempts, and analytics are scoped to their own `user_id` (enforced in `api/routes/tests.py` / `api/routes/attempts.py` via `created_by_user_id` / `user_id` filtering). The question bank itself is shared across all users of this deployment (`api/routes/question_bank.py` has no per-user filtering — anyone can import questions; any user can build tests from the full bank). This wasn't explicitly confirmed; flag it if full per-user question-bank isolation is actually wanted instead.

## Known Gap: Not Yet Tested Against the Real Auth Service

`lib/authServiceClient.ts` (frontend) and the unused `services/auth_client.py` / `api/routes/auth.py` (backend proxy) were both written against the service's documented API shape, but this was all built with no network access, so **neither path has ever made a real call** to `authentication-api-zeta.vercel.app`. Test the full signup → login → 2FA → `/api/auth/me`-equivalent flow against the live service before relying on it.
