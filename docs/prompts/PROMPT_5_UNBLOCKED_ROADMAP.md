# Unblocked Work Roadmap — Post-Enterprise Mode

> Updated: 2026-04-14
>
> With PRs #265, #266, #269, #278 merged, the following foundational pieces are
> done: **4-tier RBAC**, **Alembic migrations**, **JWT auth (ES256)**, **ee/
> scaffold**, **deployment mode guards**, **event bus**, **demo accounts**,
> **settings reconciler**, **thinking spans**, **local trace buffering**,
> **payload encryption**.
>
> This document maps what's now unblocked, the dependency chains between issues,
> and which tracks can be worked **in parallel worktrees** without file conflicts.

---

## Dependency Graph

```
#192 API key rotation ─────► #191 OTLP auth ─────► #196 Multi-tenancy ─────► #231 GDPR
                                                                        └───► #209 Team access*

#228 Audit logging ────────► #233 SIEM integration

#204 Alert evaluation ─────► #226 HMAC webhooks

#187 Docker hardening ─────► #197 Quickstart script
                       └───► #207 Terraform module

#188 CI hardening ─────────► #234 Pentest framework

#214 PyPI release ─────────► #215 npm release
                       └───► #216 yarn release

#232 Horizontal scaling ───► #225 Disaster recovery / HA

(* #209 also needs Alembic ✅ and RBAC ✅, but benefits from multi-tenancy)
```

**Critical path**: #192 → #191 → #196 → #231. This is the longest chain and
unblocks the most downstream work. Prioritize it.

---

## Parallel Worktree Tracks

Each track touches **non-overlapping files** so they can be developed
concurrently in separate git worktrees. Tracks are ordered by priority.

### Track 1: Auth Security Chain (P1, critical path)
**Branch:** `feat/api-key-rotation`
**Issues:** #192 → #191 → #196 (sequential within track)
**Files:** `models/user.py`, `models/api_key.py` (new), `api/deps.py`,
`api/routes/auth.py`, `api/routes/keys.py` (new), `api/routes/otlp.py`,
`api/routes/otel_dashboard.py`, `config.py`, `alembic/versions/`

| Step | Issue | What |
|------|-------|------|
| 1 | #192 | Multi-key model (`ApiKey` table), rotation endpoint, expiry, `last_used_at`, prefix convention (`obs_live_...`), stop regenerating keys on login |
| 2 | #191 | `verify_ingestion_key` dependency, wire into OTLP + hooks endpoints, rate limit, `OTLP_AUTH_REQUIRED` setting |
| 3 | #196 | `get_current_org_id` dependency, replace `DEFAULT_PROJECT`, org-scoped admin checks, `WHERE org_id` on all queries |

**Why sequential:** Each step depends on the auth model changes from the
previous step. #191 needs the new ApiKey lookup. #196 needs authenticated OTLP
to stamp `project_id`.

---

### Track 2: Frontend Improvements (P2, zero backend conflicts)
**Branch:** `feat/frontend-auth-ux`
**Issues:** #200, #261, #240 (independent within track)
**Files:** `web/src/**` only

| Issue | What |
|-------|------|
| #200 | `AuthError` class, 401 interceptor, session expiry toast, AdminGuard feedback, httpOnly cookie migration |
| #261 | Replace hardcoded "User" in dashboard with actual user name/email from auth context |
| #240 | Agent and model filter dropdowns on trace span tree page |

**No backend changes** — purely frontend. Can run from day 1 alongside any
backend track.

---

### Track 3: Alert Engine + Webhooks (P2, isolated API surface)
**Branch:** `feat/alert-evaluation-engine`
**Issues:** #204 → #226 (sequential)
**Files:** `api/routes/alert.py`, `services/alert_evaluator.py` (new),
`services/webhook_delivery.py` (new), `models/alert.py`,
`alembic/versions/`, `worker.py`

| Step | Issue | What |
|------|-------|------|
| 1 | #204 | Periodic evaluation loop (arq job), ClickHouse metric queries, condition evaluation, `alert_history` table, webhook URL SSRF validation |
| 2 | #226 | HMAC signing secret per webhook, `X-Observal-Signature` header, delivery tracking table, retry with exponential backoff |

**Minimal overlap** with Track 1 — alert routes are separate from auth routes.
Only potential conflict is `alembic/versions/` (different migration files, merge
cleanly).

---

### Track 4: Audit Logging (P1, mostly new files)
**Branch:** `feat/audit-logging`
**Issues:** #228 → #233 (sequential)
**Files:** `services/audit.py` (new), `services/security_events.py` (new),
`services/clickhouse.py` (DDL only), `api/routes/admin.py` (light touches),
`otel-collector-config.yaml`

| Step | Issue | What |
|------|-------|------|
| 1 | #228 | `AuditEvent` schema, emit from auth/admin/agent routes, `audit_log` ClickHouse table, `GET /api/v1/admin/audit-log` endpoint |
| 2 | #233 | OTEL Collector SIEM pipeline, `syslog`/`otlphttp`/`splunk_hec` exporters, `SIEM_*` env vars |

**Low conflict risk.** Touches `admin.py` lightly (adding emit calls) — if
Track 1 is modifying `deps.py`/`auth.py` at the same time, these don't
overlap.

---

### Track 5: CLI Cleanup (P2, completely isolated)
**Branch:** `feat/cli-improvements`
**Issues:** #254, #201 (independent)
**Files:** `observal_cli/**` only

| Issue | What |
|-------|------|
| #254 | Remove deprecated `observal init` command |
| #201 | Better error messages, debug mode, credential security (mask API keys in logs) |

**Zero overlap** with any server or frontend track.

---

### Track 6: Docker + DevOps (P1, infrastructure only)
**Branch:** `feat/docker-hardening`
**Issues:** #187, #188 (independent) → unblock #197, #207, #234
**Files:** `docker/`, `.github/workflows/`, `Makefile`

| Issue | What |
|-------|------|
| #187 | Non-root containers, read-only filesystems, bind internal ports to 127.0.0.1, drop capabilities, resource limits |
| #188 | Add Semgrep/Bandit to CI, strict ruff rules, dependency audit (`pip-audit`), SARIF upload |

**Zero overlap** with application code tracks. After this track lands, #197
(quickstart script), #207 (Terraform), and #234 (pentest) become unblocked.

---

### Track 7: Data Layer Hardening (P1-P2, services only)
**Branch:** `feat/data-resilience`
**Issues:** #186, #193, #229 (independent)
**Files:** `api/routes/auth.py` (only `_reset_tokens`), `services/clickhouse.py`,
`services/redis.py`, `config.py`

| Issue | What |
|-------|------|
| #186 | Move `_reset_tokens` dict from in-memory to Redis with TTL |
| #193 | Connection pool sizing, retry with backoff, circuit breaker for ClickHouse/Redis |
| #229 | TDE for PostgreSQL, encrypted ClickHouse volumes, application-level field encryption for sensitive columns |

**Conflict note:** #186 touches `auth.py` (the `_reset_tokens` dict). If
running alongside Track 1, coordinate the merge — different sections of the
same file.

---

## Issues That Are Unblocked But NOT In a Track

These are actionable now but lower priority or don't fit neatly into a
parallel track. Pick them up opportunistically.

| # | P | Title | Notes |
|---|---|-------|-------|
| #223 | P1 | SCIM 2.0 provisioning | ee/ routes exist as 501 stubs. Needs RBAC ✅. Can start anytime but touches `ee/` and `models/` |
| #209 | P2 | Team-level agent access | Needs RBAC ✅ + Alembic ✅. Better after #196 (multi-tenancy) but can start the models/migrations now |
| #205 | P2 | API versioning + OpenAPI | Independent. Touches many route files (docstrings + decorators) — best done when other route-heavy tracks are idle |
| #195 | P1 | Self-observability | Structured logging + metrics. Touches `main.py` — coordinate with Track 1 if needed |
| #199 | P2 | Standardize API errors + pagination | Touches all route files. Same coordination concern as #205 |
| #230 | P1 | PII detection beyond API keys | Independent. New `services/pii_detector.py` + OTLP pipeline integration |
| #224 | P1 | Secrets manager integration | New plugin in `ee/plugins/`. Independent of everything |
| #203 | P2 | ClickHouse retention policy | Config + docs only. No code conflicts |
| #198 | P2 | Redis caching + compression | Touches `services/redis.py` — coordinate with Track 7 |

---

## Recommended Execution Order

**Start immediately (parallel worktrees):**
1. **Track 1** (auth chain) — longest critical path, unblocks the most
2. **Track 2** (frontend) — zero conflicts, quick wins
3. **Track 6** (docker/CI) — unblocks 3 downstream issues
4. **Track 5** (CLI) — zero conflicts, quick wins

**Start after Track 1 step 1 lands (#192):**
5. **Track 3** (alerts) — needs stable auth model
6. **Track 4** (audit) — can start earlier but benefits from stable routes

**Start after Track 6 lands:**
7. #197 (quickstart script)
8. #234 (pentest framework)

**Start after Track 1 completes (#196 merged):**
9. #209 (team access)
10. #231 (GDPR)
11. #223 (SCIM)

---

## Quick Reference: What Each Closed Issue Unblocked

| Closed | Unblocked |
|--------|-----------|
| #190 (RBAC) | #209, #223, #228, #200, #196 (partial) |
| #194 (Alembic) | #192, #204, #205, #209, #229 |
| #189 (Enterprise mode) | #197 (partial), design clarity for all ee/ work |
| #220 (Thinking spans) | — (leaf node) |
| #252 (Local buffering) | — (leaf node) |
| #167 (Prefix ID match) | — (leaf node) |
