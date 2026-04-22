# Enterprise Edition — Web Frontend

Enterprise-only frontend pages and components. Mirrors the `ee/` backend pattern.

**License:** Separate enterprise license (`web/ee/LICENSE`). Commercial license required for production. Community contributions NOT accepted.

**Critical constraint:** `web/src/` must NEVER import from `web/ee/`. Dependency is strictly one-way: `web/ee/` imports from `web/src/`, never the reverse. The open-source frontend must be fully functional without `web/ee/`.

## Backend features awaiting frontend

These enterprise backend endpoints have NO corresponding frontend UI:

| Feature | Backend endpoint | Backend location |
|---------|-----------------|------------------|
| Audit log viewer | `GET /api/v1/admin/audit-log` | `ee/observal_server/routes/audit.py` |
| Audit log CSV export | `GET /api/v1/admin/audit-log/export` | `ee/observal_server/routes/audit.py` |
| Security events log | `GET /api/v1/admin/audit-log` (security_events) | `observal-server/api/routes/admin.py` |
| Admin diagnostics | `GET /api/v1/admin/diagnostics` | `observal-server/api/routes/admin.py` |
| SCIM provisioning | `/api/v1/scim/*` (stub — 501) | `ee/observal_server/routes/scim.py` |
| SAML SSO config | `/api/v1/sso/saml/*` (stub — 501) | `ee/observal_server/routes/sso_saml.py` |
| Organization management | Organization model exists, no CRUD UI | `observal-server/models/organization.py` |
| Webhook delivery tracking | `webhook_delivery.py` + alert_history | `observal-server/services/webhook_delivery.py` |

## What stays in `web/src/` (core)

Small conditional rendering stays in core pages — don't extract into ee/:
- SSO login button (`login/page.tsx` — `if (ssoEnabled)`)
- Enterprise settings section (`settings/page.tsx` — `if (deploymentMode === "enterprise")`)
- `useDeploymentConfig()` hook (used by both core and ee)
- Trace privacy toggle (settings page)
- Resource tuning apply button (settings page)

## Conventions

- Use shared components from `web/src/components/` (shadcn/ui, layouts, shared)
- Use shared hooks from `web/src/hooks/` (use-api, use-auth, use-deployment-config)
- Use shared types from `web/src/lib/types.ts`
- Enterprise pages should check `deploymentMode === "enterprise"` and redirect if not enterprise
- Follow the same OKLCH design system, 4pt spacing, and component patterns as core
