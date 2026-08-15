---
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
name: observal-advanced
command: observal
description: Advanced Observal operations including session reconciliation, CLI upgrades, downgrades, rollback, status checks, and local fallback mode for offline use. Use when the user wants to reconcile sessions, manage the installed CLI version, or write Agent configs locally when the server is unreachable.
version: 2.0.0
owner: observal
---

# Observal Advanced Operations

## Critical Rules

1. Execute commands in the shell with a 60-second timeout.
2. Use machine output by default: pass `--output json` on every command that supports it. Finite commands return one JSON document; streaming commands return JSON Lines. Use human output only for an explicitly interactive workflow. Use `--raw` only when raw config is requested, and never combine it with `--output json`.
3. When in doubt about a flag, run `<command> --help` first.

## Procedure: Reconcile Sessions

Backfill local session records missed by the normally automatic hook or extension pipeline. Do not run it routinely when telemetry is healthy.

Manual recovery for all detected harnesses:

```bash
observal reconcile --output json
```

Target one harness or shorten the discovery window when needed:

```bash
observal reconcile --harness claude-code --since 24 --output json
observal reconcile --harness claude-code --since 24 --dry-run --output json
```

Dry run does not drain the outbox, contact ingestion, or change cursors.

---

## Procedure: Self-Manage CLI

```bash
observal self status --output json
observal self upgrade --force --output json
observal self upgrade --version 2.5.0 --force --output json
observal self downgrade --list --output json
observal self downgrade --version 2.4.0 --force --output json
observal self rollback --force --output json
```

Use `--force` for upgrade, downgrade, and rollback in JSON mode. Standalone binary changes require a published checksum because JSON mode never accepts an unsigned download interactively.

---

## Procedure: Local Fallback Mode

Use **only** when a command exits with `Connection failed` or `Not configured`.

| harness | User-scope path | Project-scope path |
|---|---|---|
| Claude Code | `~/.claude/agents/<name>.md` | `.claude/agents/<name>.md` |
| Kiro | `~/.kiro/agents/<name>.json` | `.kiro/agents/<name>.json` |
| Cursor | `~/.cursor/rules/<name>.mdc` | `.cursor/rules/<name>.mdc` |
| VS Code | `~/.config/Code/User/agents/<name>.md` | `.vscode/agents/<name>.md` |
| Codex CLI | `~/.codex/agents/<name>.md` | `.codex/agents/<name>.md` |
| Copilot CLI | `~/.config/github-copilot/agents/<name>.md` | `.github/copilot/agents/<name>.md` |
| OpenCode | `~/.opencode/agents/<name>.md` | `.opencode/agents/<name>.md` |

**Kiro** (`~/.kiro/agents/<name>.json`):

```json
{"name":"<name>","description":"<desc>","prompt":"<prompt>","model":"claude-sonnet-4-20250514","mcpServers":{},"tools":["*"],"resources":["skill://~/.kiro/skills/*/SKILL.md"]}
```

**Claude Code, VS Code, Codex CLI, Copilot CLI, OpenCode** (markdown):

```markdown
---
name: <name>
description: <desc>
---
<prompt>
```

**Cursor** (`.mdc`):

```markdown
---
name: <name>
description: <desc>
---
<prompt>
```

After writing locally, remind the user to run `observal agent create` once the server is reachable.

---

## Output Contract

1. One sentence stating intent.
2. The exact command in a fenced code block.
3. The result: success / specific error.
4. The next action, or "done".
