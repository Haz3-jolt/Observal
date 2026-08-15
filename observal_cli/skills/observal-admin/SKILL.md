---
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: Apache-2.0
name: observal-admin
command: observal
description: Observal core administration and submission review operations, including users, settings, diagnostics, security events, audit logs, SAML, and SCIM. Use when the user needs to administer the server or decide pending Registry submissions.
version: 2.0.0
owner: observal
---

# Observal Admin Operations

Core administration requires `admin`. Review commands also work for global reviewers and authorized teamspace owners or reviewers.

## Critical Rules

1. Execute commands in the shell with a 60-second timeout.
2. Use machine output by default: pass `--output json` on every command that supports it. Finite commands return one JSON document; streaming commands return JSON Lines. Use human output only for an explicitly interactive workflow. Use `--raw` only when raw config is requested, and never combine it with `--output json`.
3. Pass `--force` on destructive JSON commands so they never prompt.
4. If permission is denied, run `observal auth whoami --output json`.
5. Never repeat generated passwords, SCIM tokens, submitted headers, database URLs, environment values, or audit content unless the user explicitly needs that secret at creation time.
6. Local server and migration commands use shell, Docker, filesystem, and database authority; they do not require an API role.

## Procedure: Settings and Diagnostics

```bash
observal admin settings --output json
observal admin set KEY VALUE --output json
observal admin diagnostics --output json
observal admin trace-privacy --output json
observal admin trace-privacy-set true --output json
observal admin cache-clear --output json
```

Sensitive setting values are redacted by the server. The setting update command does not echo the supplied value.

## Procedure: Users

```bash
observal admin users --output json
observal admin create-user EMAIL NAME --role user --output json
observal admin reset-password EMAIL --generate --output json
observal admin set-role EMAIL admin --output json
observal admin delete-user EMAIL --force --output json
```

Valid roles are `super_admin`, `admin`, `reviewer`, and `user`. JSON password reset requires `--generate`. Create and reset responses can contain one-time passwords, treat the whole result as secret.

## Procedure: Review Queue

```bash
observal admin review list --output json
observal admin review list --type mcp --output json
observal admin review list --tab agents --output json
observal admin review list --team-id TEAM_UUID --output json
observal admin review show REVIEW_ID --output json
observal admin review approve REVIEW_ID --output json
observal admin review approve AGENT_UUID --agent --output json
observal admin review approve BUNDLE_UUID --bundle --output json
observal admin review reject REVIEW_ID --reason 'Not reproducible' --output json
```

Component types are `mcp`, `skill`, `hook`, `prompt`, and `sandbox`. `--agent` and `--bundle` are mutually exclusive. Review detail may contain submitted configuration, so do not quote it unnecessarily.

## Procedure: Security and Audit

```bash
observal admin security-events --limit 50 --offset 0 --output json
observal admin audit-log --limit 100 --offset 0 --output json
observal admin audit-log --actor EMAIL --source server --output json
observal admin audit-log-export --output json
observal admin audit-log-export --output json --file audit.json
```

Audit filters include action, actor, resource type, sensitivity, outcome, source, and date range. Table-mode export produces CSV. JSON-mode export produces JSON. Use `--force` before overwriting an existing export in JSON mode.

## Procedure: SAML and SCIM

```bash
observal admin saml-config --output json
observal admin saml-config-set \
  --idp-entity-id ID \
  --idp-sso-url URL \
  --idp-x509-cert "$(cat idp-cert.pem)" \
  --active \
  --output json
observal admin saml-config-delete --force --output json
observal admin scim-tokens --output json
observal admin scim-token-create --description 'Okta' --output json
observal admin scim-token-revoke TOKEN_UUID --force --output json
```

Every SAML update requires the entity ID, SSO URL, and certificate. SCIM creation returns the bearer token once, treat the entire result as secret.

## Procedure: Local Server

```bash
observal server status --output json
observal server start --background --output json
observal server logs api --lines 100 --output json
observal server upgrade --dry-run --output json
observal server upgrade --version VERSION --force --output json
observal server rollback --force --output json
observal server versions --output json
```

JSON start and restart require `--background`. Reset, upgrade, and rollback require `--force` for JSON mutation. Rollback restores PostgreSQL and Docker images, not ClickHouse telemetry.

## Procedure: Database Migration

```bash
observal server migrate export --file registry.tar.gz --output json
observal server migrate validate --archive registry.tar.gz --output json
observal server migrate import --archive registry.tar.gz --output json
observal server migrate export-telemetry --manifest registry.manifest.json --output-dir telemetry-export --output json
observal server migrate validate-telemetry --input-dir telemetry-export --output json
observal server migrate import-telemetry --input-dir telemetry-export --output json
```

Source commands read `DATABASE_URL` and `CLICKHOUSE_URL`; target commands read `TARGET_DATABASE_URL` and `TARGET_CLICKHOUSE_URL`. PostgreSQL export uses `--file`; `--output` always selects table or JSON. ClickHouse export requires a new destination directory.

## Output Contract

1. State the intent in one sentence.
2. Show the exact command in a fenced block.
3. Report success or the categorized error.
4. Give the next action, or say `done`.
