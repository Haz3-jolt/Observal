---
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: Apache-2.0
name: observal-agents
command: observal
description: Create, update, version, install, and manage Observal agents. Use when the user wants to create or pull an agent, update an existing one, release a version, scaffold YAML, add components, build, publish, bulk-create, manage co-authors, archive, delete, or restore agents.
version: 2.0.0
owner: observal
---

# Observal Agents: Agent Lifecycle Management

## Critical Rules

1. **EXECUTE commands**: run them in your shell. Set timeout to 60 seconds.
2. **Use single quotes** for `--prompt` and `--description` values.
3. **Use machine output by default:** pass `--output json` on every command that supports it. Finite commands return one JSON document; streaming commands return JSON Lines. Use human output only for an explicitly interactive workflow. Use `--raw` only when raw config is requested, and never combine it with `--output json`.
4. **Pass `--yes`** on destructive commands (`archive`, `delete`, `unarchive`, `bulk-create`).
5. **Resolve 409:** `observal agent publish --update` for in-place edits, `observal agent release --bump` for reviewed releases.
6. **When in doubt about a flag, run `<command> --help` first.**

---

## Procedure: Create Agent

Required: `--name`, `--description`, `--prompt`. Optional: `--model`, `--harness` (repeatable), `--prompt-file`, `--from-file`.

Before choosing a model, query the registry for every selected harness and pick an available exact model:

```bash
observal registry models --harness kiro --output json
observal registry models --harness claude-code --output json
```

> **WARNING:** Without `--name` and `--prompt`, the command launches an interactive wizard. Always pass at least `--name`, `--description`, and `--prompt`.

```bash
observal agent create \
  --name AGENT_NAME \
  --description 'Short description' \
  --prompt 'System prompt content' \
  --model claude-sonnet-4-6 \
  --harness kiro --harness claude-code \
  --output json
```

Error branching:
- **`409`**: switch to Procedure: Update Agent or Release Agent Version.
- **`422`**: missing required field. Check message, fix, retry.
- **`Connection failed`**: server unreachable; use `observal-advanced` skill's Local Fallback.

---

## Procedure: Update Agent

Skips review queue. Overwrites in place.

1. Write `observal-agent.yaml`. **Critical:** include `model_config_json: {}` and `external_mcps: []` literally.
   ```bash
   mkdir -p /tmp/myagent && cat > /tmp/myagent/observal-agent.yaml << 'EOF'
   name: existing-agent-name
   version: "1.0.0"
   description: "Updated description"
   model_name: claude-sonnet-4-6
   model_config_json: {}
   models_by_harness: {}
   external_mcps: []
   prompt: |
     Updated system prompt here.
   supported_harnesses:
     - kiro
     - claude-code
   components: []
   EOF
   ```
2. Push: `observal agent publish --update --dir /tmp/myagent --output json`
3. Confirm: `observal agent show existing-agent-name --output json`

---

## Procedure: Release Agent Version

Goes through review queue. Use for "new version", "bump", or "release".

1. Write `observal-agent.yaml` (same schema as Update Agent).
2. Release:
   ```bash
   observal agent release AGENT_NAME --bump patch --dir /tmp/myagent --output json
   ```
   Bump types: `patch`, `minor`, `major`.
3. Verify: `observal agent versions AGENT_NAME --output json`

---

## Procedure: Author Agent Locally

1. Scaffold with flags (no YAML hand-writing):
   ```bash
   observal agent init --dir ./my-agent --name AGENT_NAME --description 'Short description' --prompt 'System prompt' --model claude-sonnet-4 --harness kiro --harness claude-code --output json
   ```
   Use `--prompt-file ./PROMPT.md` for long prompts. Omit flags only when the user wants the wizard.
2. Find components, then add by UUID:
   ```bash
   observal registry mcp list --search 'github docker' --output json
   observal registry skill list --search 'frontend design' --output json
   observal registry skill list --team platform-tools --output json
   observal agent add mcp COMPONENT_UUID --dir ./my-agent --output json
   observal agent add skill COMPONENT_UUID --dir ./my-agent --output json
   ```
3. Validate: `observal agent build --dir ./my-agent --output json`
4. Publish: `observal agent publish --dir ./my-agent --output json`
   - `--draft` saves without submitting. `--submit` submits a saved draft.
   - Use `--team TEAM_HANDLE --visibility public` for a public teamspace agent.
   - Use `--team TEAM_HANDLE --visibility team` for a private agent visible only to team members.

---

## Procedure: Bulk Create

```bash
observal agent bulk-create --from-file agents.json --dry-run --output json
observal agent bulk-create --from-file agents.json --yes --output json
```

---

## Procedure: Archive / Restore

```bash
observal agent archive AGENT_NAME --yes --output json
observal agent delete AGENT_NAME --yes --output json
observal agent transfer-owner AGENT_NAME @username --yes --output json
observal agent unarchive AGENT_NAME --yes --output json
```

---

## Procedure: Pull Agent

```bash
observal agent pull NAMESPACE/AGENT --harness kiro --no-prompt --output json
observal agent pull NAMESPACE/AGENT --harness claude-code --scope project --dry-run --no-prompt --output json
```

JSON pull requires `--no-prompt`. Supply repeated `--env NAME=VALUE` and `--header NAME=VALUE` inputs when requested. Never echo those values. Check `files`, `warnings`, and `setup_commands`; a failed skill, setup command, or lockfile write is not success. Dry-run changes no files or metadata.

---

## Browse Agents

```bash
observal agent list --output json
observal agent list --namespace platform-tools --output json
observal agent list --team platform-tools --output json
observal agent list --search 'incident resolution' --output json
observal agent list --search keyword --output json
observal agent list --page 2 --limit 20 --output json
observal agent my --output json
observal agent show AGENT_NAME --output json
observal agent versions AGENT_NAME --output json
```

After `list`, use row numbers (1, 2, 3...) in subsequent commands. Team members see approved private teamspace agents in normal results. `--team TEAM_HANDLE` narrows to what that teamspace owns. Direct references use `TEAM_HANDLE/AGENT_SLUG`.

---

## Procedure: Manage Co-Authors

Co-authors have full edit and publish access (equal to owner).

```bash
# List co-authors
observal agent co-authors list NAMESPACE/AGENT --output json

# Add by email or username
observal agent co-authors add NAMESPACE/AGENT user@example.com --output json
observal agent co-authors add NAMESPACE/AGENT @username --output json

# Remove by user UUID (from list output)
observal agent co-authors remove NAMESPACE/AGENT USER_UUID --output json
```



## Error Reference

| Error | Fix |
|-------|-----|
| `409` / `already have an agent named` | Use `publish --update` or `release --bump` |
| `422` `model_config_json` | Add `model_config_json: {}` to YAML |
| `422` `external_mcps` | Add `external_mcps: []` to YAML |
| `422` `system prompt is required` | Add `--prompt` or `prompt:` in YAML |

---

## Output Contract

1. One sentence stating intent.
2. The exact command in a fenced code block.
3. The result: success or specific error.
4. The next action, or "done".
