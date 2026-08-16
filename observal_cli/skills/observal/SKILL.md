---
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: Apache-2.0
name: observal
command: observal
description: "Core Observal CLI operations: pull agents, scan installed components, diagnose harness configs, authenticate, manage CLI settings and teamspaces, work through Inbox, get recommendations, and discuss agent insights. Use when the user wants to install an agent, check setup, login, configure the CLI, manage a team or invitation, review their work feed, ask what to install, or ask how an agent is doing."
version: 2.5.0
owner: observal
---

# Observal: Core CLI Operations

## Critical Rules

1. **EXECUTE commands**: run them in your shell, do not just display them.
2. **Set timeout to 60 seconds**: most commands make HTTP calls.
3. **Use single quotes** for `--prompt` and `--description` values to avoid shell quoting issues.
4. **Do NOT run `observal auth status` first.** Other commands surface auth problems clearly on their own.
5. **When in doubt about a flag, run `<command> --help` first.** Never guess flag names.
6. **Use machine output by default:** pass `--output json` on every command that supports it. Finite commands return one JSON document; streaming commands return JSON Lines. Use human output only for an explicitly interactive workflow. Use `--raw` only when raw config is requested, and never combine it with `--output json`.
7. **Pass `--yes` / `-y` on destructive commands** so they do not block on a confirmation prompt.
8. **Use canonical registry identities:** prefer the returned `qualified_name` (`namespace/slug`) for agent and component show, install, pull, archive, and transfer commands. Bare names work only when unambiguous.
9. **Resolve 409 conflicts deterministically:** if the error says a name is ambiguous, retry with `namespace/slug`; otherwise use `--update` for in-place edits or `--bump` for versioned releases.
10. **Only fall back to local file writes** if a command exits with `Connection failed` or `Not configured`.
11. **Never invent `OTEL_*` or `CLAUDE_CODE_ENABLE_TELEMETRY` environment variables.** Telemetry flows through session push hooks and reconciliation only.

---
## Procedure: Natural-Language Registry Search

For requests like "find me an agent for incident resolution" or "what skill helps design good frontends", extract the useful keywords and search JSON first.

```bash
observal agent list --search 'incident resolution' --output json
observal registry skill list --search 'frontend design' --output json
observal registry skill list --team platform-tools --search 'frontend design' --output json
observal registry mcp list --search 'github docker' --output json
```

Summarize the top matches by `qualified_name`, description, and why they fit. If no results, retry with fewer keywords.

For open-ended asks instead ("what am I missing", "what should I install"), do not guess keywords — ask what fits this user's own sessions with `observal registry recommend --output json`. Check `personalized` first: `false` means no session history yet, so these are merely the most-used components; say so rather than implying they were chosen for the user. Fields and dismissals are in the `observal-registry` skill.

## Procedure: Pull Agent

Install an agent's full config (rules, MCP servers, hooks, skills, sandboxes, prompts) into a local harness.

```bash
observal agent pull NAMESPACE/AGENT_SLUG --harness kiro --no-prompt --dir . --output json
```

**For Pi (`--harness pi`):**
When pulling for Pi, the CLI downloads the agent into an isolated profile using its stable slug. If two installed namespaces use the same slug, the CLI qualifies the local profile name to avoid a collision.
**Crucial:** After pulling, run `/agent <local-profile-name>` inside Pi using the exact local profile name printed by the CLI.

**Flags:**
- `--harness` (required): `claude-code`, `kiro`, `cursor`, `vscode`, `codex`, `copilot`, `copilot-cli`, `opencode`, `antigravity`, `goose`, `pi`
- `--version <semver>`: install a specific version (e.g. `1.2.0`). Omit for latest.
- `--scope user|project`: install scope for harnesses that support user or project installs
- `--model <name>` or `--model <harness>=<name>`: override saved model (repeatable)
- `--tools t1,t2`: Claude Code tool whitelist
- `--env KEY=VALUE`: MCP environment variable value (repeatable)
- `--header Header-Name=VALUE`: MCP auth header value (repeatable)
- `--dry-run`: preview file writes without touching disk
- `--no-prompt`: skip interactive confirmation
- `--dir <path>`: target directory (default: current)

**Merge behavior:** MCP configs are merged with existing harness config files, not overwritten. Existing user entries are preserved.

**Version pinning:** When `--version` is specified, the exact content from that version is installed. The lockfile (`~/.observal/lockfile.json`) records the pin. If another agent depends on the same component at a different version, a warning is displayed.

If the user did not specify an harness, ask which one before running. After install, check local files:

```bash
observal scan --harness kiro --output json
```

`scan` verifies MCPs, skills, hooks, and agents. Prompts/sandboxes are injected into rules/MCP config; use the pull output/lockfile for membership.

---
## Procedure: Outdated

Check pulled agents and separately installed MCPs, skills, and hooks for newer registry versions.

```bash
observal outdated --output json
observal outdated --harness claude-code --output json --no-report
```

Reads `~/.observal/lockfile.json` and compares each supported pin against the active registry. JSON returns `items`, `summary`, and `report`; use it for automation. Findings also land in your inbox as `update_available` items; `--no-report` suppresses that write but still reads the registry. Reporting is best-effort and its status is always exposed.

---
## Procedure: Inbox

```bash
observal inbox list --state open --action-required --output json
observal inbox show ITEM_UUID --output json
observal inbox done ITEM_UUID --output json
observal inbox read-all --kind update_available --yes --output json
```
Use list UUIDs. Reading does not resolve; use `done`, `dismiss`, or `reopen` only as requested. Confirm an `action_command` before running it. JSON `read-all` requires `--yes` and affects only its filters.

---
## Procedure: Scan harnesses

Read-only inventory of installed components across all detected harnesses. **Never modifies any file.**

```bash
observal scan --output json
observal scan --harness kiro --output json
observal scan --harness claude-code --output json
```

Reports: detected harnesses, MCP servers, skills, hooks, agents, and unregistered components.

---
## Procedure: Doctor

Diagnose only. Does not fix anything.

```bash
observal doctor --output json
```

Reports: Observal config validity, server reachability, lockfile metadata drift against the active Registry, hook installation status per harness, and skill presence. In JSON mode, diagnosis exits zero when checks run and reports health through `healthy`, `issues`, and `warnings`. Use `--yes --output json` to apply fixable warnings without prompting. Installed version pins remain unchanged.

---

## Procedure: Doctor Patch

Install session telemetry hooks. Run with `--dry-run` first when the user is unsure.

```bash
observal doctor patch --all-harnesses --dry-run --output json
observal doctor patch --all-harnesses --output json
observal doctor patch --harness kiro --output json
observal doctor patch --harness claude-code --output json
```

**Required:** select `--all-harnesses` or at least one `--harness`. MCP commands and URLs are not modified. For Pi, Doctor installs the bundled TypeScript extension directly at `~/.pi/agent/extensions/observal.ts` and removes the legacy npm package registration.

---

## Procedure: Doctor Cleanup

Remove Observal-managed hooks and settings from harness configs. Leaves user content untouched. JSON writes require `--yes`; dry runs do not.

```bash
observal doctor cleanup --dry-run --output json
observal doctor cleanup --yes --output json
observal doctor cleanup --harness kiro --yes --output json
```

**Support bundles:** Generate with `observal doctor support bundle --file /tmp/observal-support.tar.gz --output json`, then inspect with `observal doctor support inspect /tmp/observal-support.tar.gz --output json`. Remote failures remain explicit; treat the archive as sensitive.

## Procedure: Auth

```bash
observal auth login
OBSERVAL_PASSWORD_FILE=/path/to/password observal auth login --server https://observal.example.com --email me@x.com --output json
observal auth login --sso --output json
observal auth whoami --output json
observal auth status --output json
observal auth logout --output json
OBSERVAL_CURRENT_PASSWORD_FILE=/path/to/current OBSERVAL_NEW_PASSWORD_FILE=/path/to/new observal auth change-password --output json
observal auth set-username new-handle --output json
```

Human login asks for the server URL; leave it blank for `http://localhost`. Never place a password directly in command arguments. JSON credential login requires the server, email, and password environment or file input. Fresh-server JSON bootstrap also requires `--name`; human login prompts for it when omitted. JSON SSO emits an `authorization_required` event followed by an `authenticated` event. A username becomes the user's registry namespace and cannot be changed after the user owns an agent or component.

---

## Procedure: Teamspaces

```bash
observal team list --output json
observal team show HANDLE --output json
observal team claim-personal --output json
observal team create 'Platform Tools' --handle platform-tools --visibility private --output json
observal team visibility set HANDLE public --output json
observal team visibility list-requests --output json
observal team visibility approve HANDLE --output json
observal team visibility reject HANDLE --reason 'Reason' --output json
observal team request join HANDLE --message 'Reason for access' --output json
observal team request mine HANDLE --output json
observal team request withdraw HANDLE --yes --output json
observal team request list HANDLE --status pending --output json
observal team members add HANDLE @USER --role member --output json
observal team invite preview INVITE_TOKEN --output json
observal team invite request INVITE_TOKEN --message 'Reason for access' --output json
observal team invite requests HANDLE INVITE_UUID --output json
observal team invite delete HANDLE INVITE_UUID --yes --output json
```

Public visibility remains private with `visibility_request_status: pending` until a reviewer approves it. Invitation requests also require owner approval.

Treat invite tokens and URLs as secrets. Never echo a token after use.

---

## Procedure: CLI Config

```bash
observal config show --output json
observal config path --output json
observal config set server_url https://observal.example.com --output json
observal config set timeout 60 --output json
observal config aliases --output json
observal config alias MY_AGENT namespace/slug --output json
```

Only `server_url`, `timeout`, `update_check`, `update_check_interval`, and `update_check_repo` are user-configurable. Authentication and identity fields are managed by `observal auth`. JSON config output never includes token values or fragments.

---
## Procedure: Discuss Agent Insights

Use this when the user asks how an agent is doing, what is working, what is broken, why a version changed, or what to improve.

Always fetch JSON first so you can reason over every report section, then answer conversationally.

```bash
observal ops insights list AGENT_NAME --output json
observal ops insights show AGENT_NAME latest --output json
observal ops insights show AGENT_NAME latest --section suggestions --output json
observal ops insights show AGENT_NAME latest --section friction_analysis --output json
```

Sections: `at_a_glance`, `what_they_work_on`, `interaction_style`, `usage_patterns`, `what_works`, `friction_analysis`, `suggestions`, `usage_cost_analysis`, `version_comparison`, `regression_detection`, `on_the_horizon`, and `fun_ending`.

For broad questions, run full `show` JSON and summarize health, top friction, top strengths, cost, and next actions. For narrow questions, fetch the specific section. If no completed report exists, offer to generate one:

```bash
observal ops insights generate AGENT_NAME --period 14 --wait --output json
observal ops insights generate AGENT_NAME --version 1.2.0 --compare 1.1.0 --period 30 --wait --output json
```

Keep the answer grounded in the JSON. Say when the report is missing a section or has low session count.

**Reuse suggestions come first.** A `suggestions.features_to_try` entry carrying a `component_ref` object already exists in this registry — the server validated it and strips the field from anything it could not resolve. Report those ahead of create-new suggestions, quoting `component_ref.qualified_name` and `latest_version` verbatim. No `component_ref` means it is not a registry component: never tell the user to install it. When nothing is reused, `narrative.registry_match` says why; see `observal-ops` for its fields.

---

## Error Reference

| Error | Action |
|-------|--------|
| `Connection failed` | Server unreachable. Use the `observal-advanced` skill's Local Fallback procedure |
| `Not configured` / `No server` | Run `observal auth login` |
| `403 Forbidden` | Check `observal auth whoami --output json`; user lacks required role |
| `404 Not found` | Verify `qualified_name` with `observal agent list --output json` |
| `409 Ambiguous` | Retry with the returned `namespace/slug` identity |

---

## Output Contract

For every CLI invocation, format your response:

1. One sentence stating intent.
2. The exact command in a fenced code block.
3. The result: success / specific error.
4. The next action, or "done".

---

For full command reference, read `references/commands.md`. For agent creation use the `observal-agents` skill. For registry operations use `observal-registry`. For observability use `observal-ops`. For admin tasks use `observal-admin`.
