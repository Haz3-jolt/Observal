# Plan: Lock File, Version Pinning & Version-Aware Insights

## Context

Observal has versioning infrastructure (Phase 1 of epic #615 is done), but three critical gaps remain:

1. **No client-side lock file** — `agent_lock_file.py` exists server-side but is never written to disk or consumed by the CLI. The `.observal/agent` marker only stores `{agent_id, agent_version, pulled_at}` for one agent.
2. **No version pinning** — `pull`/`install` always resolves `latest_version`. Users can't install older versions or pin components.
3. **Insights are version-blind** — The insight pipeline (`services/insights/generator.py`) never correlates performance against version changes. `layer_hash` field exists in ingest schema and ClickHouse but is never populated by the CLI.

Related epic: #615. This covers remaining Phase 2 work from #619 (resolver — simplified to exact pins) and #626 (consumer commands).

## Decisions Made

| Decision | Choice | Rationale |
|---|---|---|
| Lock file location | Global: `~/.observal/lockfile.json` | Machine-level truth for insights. IDE configs (.claude/, .cursor/) are already the sharable team artifact. |
| Version ranges | Exact pins only | No resolver complexity. `"1.2.0"` not `"^1.2.0"`. Expand later if needed. |
| User modifications | Track + warn on drift | Enables insights to distinguish "v1.2 as-shipped" from "v1.2 locally modified". |
| Server storage | Full JSON blob + hash | Debuggable, diffable server-side. ~10-50KB per unique snapshot (with file contents). |
| Insight comparison | Auto consecutive + optional baseline | Default: compare periods by layer_hash transition. Optional: user pins a baseline for long-term tracking. |
| Hash algorithm | sha256 (truncated to 16 hex chars) | Already used in codebase (`versioning.py`). No new dependency. Fast enough for lock file sizes. |

## Approach

### 1. Lock File Schema (`~/.observal/lockfile.json`)

Global lock file — canonical record of everything installed via Observal, organized by IDE. JSON for fast parsing (stdlib `json` is ~10x faster than PyYAML, and this file is read on every session push).

```json
{
  "lock_version": 1,
  "updated_at": "2026-06-01T12:00:00Z",
  "ides": {
    "claude-code": {
      "agents": [
        {
          "name": "my-agent",
          "id": "550e8400-e29b-41d4-a716-446655440000",
          "version": "1.2.0",
          "pulled_at": "2026-06-01T12:00:00Z",
          "scope": "project",
          "directory": "/home/user/myproject",
          "components": [
            {
              "type": "mcp",
              "name": "postgres-mcp",
              "id": "uuid",
              "version": "2.1.0",
              "integrity": "sha256-abc123def456..."
            },
            {
              "type": "skill",
              "name": "code-review",
              "id": "uuid",
              "version": "1.0.0",
              "integrity": "sha256-789abc..."
            },
            {
              "type": "hook",
              "name": "lint-guard",
              "id": "uuid",
              "version": "1.0.0",
              "integrity": "sha256-..."
            }
          ]
        }
      ],
      "standalone": [
        {
          "type": "mcp",
          "name": "custom-mcp",
          "id": "uuid",
          "version": "1.0.0",
          "scope": "user",
          "installed_at": "2026-06-01T12:00:00Z"
        },
        {
          "type": "skill",
          "name": "some-skill",
          "id": "uuid",
          "version": "1.0.0",
          "scope": "project",
          "directory": "/home/user/myproject",
          "installed_at": "2026-06-01T12:00:00Z",
          "integrity": "sha256-..."
        }
      ]
    },
    "cursor": {
      "agents": [],
      "standalone": []
    }
  }
}
```

**Key design notes:**
- `agents[].components[]` tracks components bundled with the agent (from `observal pull`)
- `standalone[]` tracks individually installed components (from `observal mcp install`, `observal skill install`)
- `integrity` = sha256 of the file content written to disk. Used for drift detection.
- `directory` field on project-scoped installs enables attributing sessions to the right agent by matching session cwd

### 2. Agent Attribution per IDE

Current attribution mechanisms:
- **Claude Code**: JSONL has `{"type": "agent-setting", "agentSetting": "name"}` — agent name embedded in session data by IDE itself
- **Cursor**: Writes `.cursor/agents/<name>.md` — filename = agent name
- **Kiro**: `OBSERVAL_AGENT_NAME` env var in hook commands
- **Fallback**: `.observal/agent` marker file (per-project, written by `pull`)

**New approach**: Drop the per-project `.observal/agent` marker entirely. Replace with the global lock file. Add a one-time **migration** on first CLI run that:
1. Scans all project directories for `.observal/agent` files
2. Reads each marker's `{agent_id, agent_version, pulled_at}`
3. Writes entries into the new `~/.observal/lockfile.json`
4. Deletes old `.observal/agent` files

The migration runs automatically (check for `~/.observal/lockfile.json` existence). Session push resolves agent context from the lock file:
1. Determine cwd from hook event
2. Look up lock file: find agent entry where `directory` matches cwd for the session's IDE
3. Include `agent_id`, `agent_version`, and `layer_hash` in ingest payload

### 3. Layer Hash Computation & Upload

The `layer_hash` field exists in ClickHouse `session_events` and the `SessionIngestRequest` schema but is never populated.

**Computation**: 
```python
# On every session push:
# 1. Scan IDE config dirs (user scope + project scope for the cwd)
# 2. Build sorted manifest: [{path, sha256, size, source}, ...]
# 3. Hash the manifest JSON string
layer_hash = sha256(json.dumps(manifest, sort_keys=True))[:16]
```

**Optimization (bandwidth)**:
- CLI maintains `~/.observal/.last_uploaded_layer` containing the last hash whose snapshot was uploaded
- On session push:
  - Compute layer_hash from manifest
  - If hash == `.last_uploaded_layer`: just send hash string in `layer_hash` field (no upload)
  - If hash differs: POST manifest to `/api/v1/layer-snapshots` endpoint, update `.last_uploaded_layer`
  - Always send hash in `layer_hash` field of ingest payload
- **Performance**: File hashing happens in the hook subprocess (non-blocking to IDE). Cache file hashes by mtime to avoid re-reading unchanged files.

### 4. Server-Side Layer Snapshot Storage

New endpoint + ClickHouse table:

```sql
CREATE TABLE IF NOT EXISTS layer_snapshots (
    hash            String,
    project_id      String,
    user_id         String,
    ide             LowCardinality(String),
    content         String CODEC(ZSTD(3)),   -- full manifest JSON with file contents
    uploaded_at     DateTime64(3, 'UTC') DEFAULT now(),
    file_count      UInt16,
    total_size      UInt32,
    observal_lockfile_hash String DEFAULT ''
) ENGINE = ReplacingMergeTree(uploaded_at)
ORDER BY (project_id, user_id, hash)
```

Typical snapshot size: 10-50KB compressed (rules/agents/skills are small text files).

### 5. Version-Aware Insights

The insight generator (`services/insights/generator.py`) needs:

1. **Layer hash grouping**: Query sessions grouped by `layer_hash`, detect transitions
2. **Snapshot resolution**: When layer_hash changes, fetch both snapshots, diff them
3. **Temporal comparison**: Compare metrics (cost, duration, success rate, tool errors) between consecutive hash periods
4. **New report section**: "Version Impact" — surfaces what changed and how it affected performance

For the materialized view `session_stats_agg`: add `layer_hash` column so aggregation queries can GROUP BY it efficiently.

### 6. Version Selector for Components (CLI + API)

Add `--version` flag to install commands:
- `observal agent pull my-agent --ide claude-code --version 1.2.0`
- `observal mcp install @db --ide cursor --version 2.1.0`  
- `observal skill install @sk --ide kiro --version 1.0.0`

API changes:
- `POST /api/v1/agents/{id}/install` body gets optional `version` field (currently always resolves latest)
- `POST /api/v1/mcps/{id}/install` body gets optional `version` field
- `POST /api/v1/skills/{id}/install` body gets optional `version` field

Server resolves the specific version instead of `latest_version_id`.

### 7. Full IDE Layer Tracking

The AI's behavior is shaped by **everything** in the IDE config dir, not just what Observal installed:
- `~/.claude/CLAUDE.md` (global rules)
- `~/.claude/agents/*.md` (all agents, including user-created ones)
- `~/.claude/skills/*/SKILL.md` (all skills)
- `~/.cursor/rules/*.mdc` (all rules)
- `~/.cursor/mcp.json` (all MCP servers)
- Project-level `.claude/`, `.cursor/`, etc.

**Approach: Manifest hash of the full IDE layer**

The `layer_hash` should represent the FULL state the AI sees, not just Observal-installed items:

1. **Build a manifest** of the relevant IDE config directory:
   - List all relevant files (rules, agents, skills, MCP configs, hooks)
   - For each: `{relative_path, sha256_of_content, size, content}`
   - Sort deterministically
2. **Hash the manifest** (of just paths + hashes, not content) → this is the `layer_hash`
3. **Upload the full manifest WITH content** to the server on change:
   ```json
   {
     "hash": "a1b2c3d4e5f6g7h8",
     "ide": "claude-code",
     "scope": "user",
     "files": [
       {
         "path": "CLAUDE.md",
         "hash": "sha256-abc...",
         "size": 2048,
         "source": "user",
         "content": "# CLAUDE.md\n\nBehavioral guidelines..."
       },
       {
         "path": "agents/my-agent.md",
         "hash": "sha256-def...",
         "size": 4096,
         "source": "observal",
         "content": "---\nname: my-agent\n---\n\nYou are..."
       },
       {
         "path": "skills/code-review/SKILL.md",
         "hash": "sha256-ghi...",
         "size": 1024,
         "source": "observal",
         "content": "---\ntitle: Code Review\n---\n..."
       }
     ],
     "observal_lockfile_hash": "xyz789..."
   }
   ```

**Why send full content (not just hashes)?**
- If insights detects "error rate went up after layer changed," we need to know WHAT changed to explain WHY
- Without content, we can say "something changed" but can't generate actionable advice
- The server is self-hosted / user-owned — it's their data going to their own infra
- Enables the insight engine to: diff two snapshots, identify which rule/prompt change caused a regression, suggest reverting specific changes
- Content is ZSTD-compressed in ClickHouse, typical total: 10-50KB per snapshot (rules/agents/skills are text files)

This means:
- **Layer hash changes** when the user edits CLAUDE.md, adds a custom agent, modifies an Observal-installed skill, etc.
- **Insights can see**: "After the user added 'always use TypeScript' to CLAUDE.md, the agent started generating TS in Python projects, causing test failures" — actionable, specific
- **Observal-installed items** are tagged `source: "observal"` so we can cross-reference with the lock file for version info
- **Drift detection** is built-in: if an Observal-installed file's content differs from what the registry version ships, it's been modified locally

**Which files to include per IDE:**

| IDE | User scope files | Project scope files |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md`, `~/.claude/agents/*.md`, `~/.claude/skills/*/SKILL.md`, `~/.claude/settings.json` (MCP section) | `.claude/CLAUDE.md`, `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`, `.claude/settings.local.json` |
| Cursor | `~/.cursor/rules/*.mdc`, `~/.cursor/mcp.json`, `~/.cursor/hooks.json`, `~/.cursor/agents/*.md` | `.cursor/rules/*.mdc`, `.cursor/mcp.json`, `.cursor/hooks.json`, `.cursor/agents/*.md` |
| Kiro | `~/.kiro/agents/*.json`, `~/.kiro/skills/*/SKILL.md`, `~/.kiro/settings/mcp.json` | `.kiro/agents/*.json`, `.kiro/skills/*/SKILL.md`, `.kiro/settings/mcp.json` |
| Pi | `~/.pi/agent/AGENTS.md`, `~/.pi/agent/mcp.json`, `~/.pi/agent/skills/*/SKILL.md`, `~/.pi/agent/settings.json` | `AGENTS.md`, `.pi/mcp.json`, `.pi/skills/*/SKILL.md` |

**Session push combines both scopes**: the layer_hash for a session = hash(user_scope_manifest + project_scope_manifest for the session's cwd).

### 8. Drift Detection (subset of layer tracking)

Drift is detected automatically as part of layer tracking:
- Lock file says `agents/my-agent.md` has integrity `sha256-abc`
- Layer manifest shows `agents/my-agent.md` has hash `sha256-xyz`
- Mismatch → this file was modified after install
- Server can diff manifests: "same Observal version but user modified the agent file"

## Files to Modify

### CLI (`observal_cli/`) — New Files
| File | Purpose |
|---|---|
| `observal_cli/lockfile.py` | Lock file CRUD: read, write, upsert agent/component, remove, compute hash, detect drift |
| `observal_cli/layer.py` | IDE layer scanning: discover config files per IDE, build manifest, compute layer_hash, cache file hashes |
| `observal_cli/cmd_outdated.py` | `observal outdated` command — compare lock file pins against registry latest |

### CLI (`observal_cli/`) — Modified Files  
| File | Change |
|---|---|
| `cmd_pull.py` | After writing IDE files, upsert agent + components into lock file |
| `cmd_mcp.py` (`_install_impl`) | After install, upsert standalone MCP into lock file |
| `cmd_skill.py` (`skill_install`) | After install, upsert standalone skill into lock file |
| `cmd_agent.py` | Add `--version` flag to pull, pass to install API |
| `sessions/base.py` (`build_payload`) | Read lock file hash, include as `layer_hash` |
| `sessions/agent_marker.py` | Replace with lock file lookup (remove old marker reader) |
| `main.py` | Register `outdated` command |

### Server (`observal-server/`) — New Files
| File | Purpose |
|---|---|
| `api/routes/layer_snapshot.py` | `POST /api/v1/layer-snapshots` — upload snapshot; `GET /{hash}` — retrieve |
| `services/insights/version_impact.py` | Version transition detection + metric comparison logic |

### Server (`observal-server/`) — Modified Files
| File | Change |
|---|---|
| `api/routes/agent/install.py` | Accept optional `version` field, resolve specific version |
| `api/routes/component_versions.py` | Install endpoint accepts version param |
| `services/clickhouse/schema.py` | Add `layer_hash` to `session_stats_agg` + update MV |
| `services/insights/generator.py` | Add version impact section to pipeline |
| `services/insights/session_meta_extractor.py` | Fetch `layer_hash` alongside session data |
| `services/insights/sections.py` | New "Version Impact" section prompt |

### Existing Code to Reuse
| What | Where | How |
|---|---|---|
| `compute_integrity_hash()` | `services/agent_lock_file.py` | Reuse for lock file entry integrity |
| `parse_semver()`, `validate_semver()` | `services/versioning.py` | Version validation |
| `build_payload()` layer_hash slot | `sessions/base.py` | Already accepts the field, just needs population |
| `SessionIngestRequest.layer_hash` | `api/routes/ingest.py` | Already defined, just needs CLI to send it |
| ClickHouse `session_events.layer_hash` | `clickhouse/schema.py` | Column exists, just unpopulated |
| `_resolve_agent()` | `sessions/base.py` | Extend to use lock file |

## Steps

### Phase A: Lock File Foundation
- [ ] Implement `observal_cli/lockfile.py` — read/write/upsert/remove/hash utilities
- [ ] Implement migration from `.observal/agent` markers → lock file (auto on first run)
- [ ] Update `cmd_pull.py` — write agent + components to lock file after pull (remove old marker write)
- [ ] Update `cmd_mcp.py` — write standalone MCP to lock file after install  
- [ ] Update `cmd_skill.py` — write standalone skill to lock file after install

### Phase B: Layer Hash & Upload
- [ ] Implement `observal_cli/layer.py` — IDE config dir scanning, manifest building, hash computation
- [ ] Per-IDE file discovery (which dirs/globs to scan for each IDE)
- [ ] File hash caching by mtime (`~/.observal/.file_hash_cache`)
- [ ] Update `sessions/base.py` `build_payload()` to compute and include layer_hash
- [ ] Implement `POST /api/v1/layer-snapshots` endpoint (server) — stores manifest + hash
- [ ] Add layer snapshot upload logic to session push (only on hash change)
- [ ] Add `layer_hash` to `session_stats_agg` MV (ClickHouse migration)

### Phase C: Version Selector
- [ ] Add `--version` flag to `observal pull` command
- [ ] Add `--version` flag to `observal mcp install` command  
- [ ] Add `--version` flag to `observal skill install` command
- [ ] Update `POST /api/v1/agents/{id}/install` to accept + resolve specific version
- [ ] Update MCP/skill install endpoints similarly
- [ ] Version selector in web UI (agent detail page) — pass version to install API

### Phase D: Version-Aware Insights
- [ ] Implement `services/insights/version_impact.py` — transition detection + comparison
- [ ] Update `session_meta_extractor.py` to fetch layer_hash per session
- [ ] Add "Version Impact" section to `sections.py`
- [ ] Wire into `generator.py` pipeline
- [ ] Baseline pinning: API to mark a layer_hash as baseline for an agent

### Phase E: Outdated Command
- [ ] Implement `observal outdated` command (compare lock file versions vs registry latest)

## Verification

- [ ] `observal pull agent --ide claude-code` → lock file has agent entry with components, `~/.observal/lockfile.json` exists
- [ ] `observal mcp install @mcp --ide cursor` → lock file has standalone MCP entry
- [ ] `observal skill install @sk --ide kiro` → lock file has standalone skill entry
- [ ] Session push includes `layer_hash` field in payload (inspect with `--verbose` or check server logs)
- [ ] Layer hash changes when: user edits CLAUDE.md, adds a custom agent, modifies Observal-installed skill, etc.
- [ ] Layer manifest uploaded only on first push after change (verify no re-upload on subsequent pushes)
- [ ] `observal outdated` → shows table of pinned vs latest for all lock file entries
- [ ] `observal pull my-agent --version 1.0.0 --ide claude-code` → installs specific version, lock file records it
- [ ] Insight report includes "Version Impact" section when layer_hash transitions detected in the period
- [ ] Server can diff two layer snapshots by hash to show exactly which files changed
- [ ] Privacy: manifest contains full content of IDE config files (user's own server) — verify no leakage to third parties
- [ ] Migration: existing `.observal/agent` markers auto-migrated to lock file on first CLI run post-update

## Glossary: What Lives Where & What Gets Sent

### Local Artifacts (never uploaded directly)

| Artifact | Path | Purpose |
|---|---|---|
| **Lock file** | `~/.observal/lockfile.json` | Tracks what Observal CLI installed (agents, MCPs, skills, hooks) with exact version pins. Used by `observal outdated` and to tag layer snapshot files as `source: "observal"`. |
| **Layer hash cache** | `~/.observal/.last_uploaded_layer` | Stores the last `layer_hash` that was successfully uploaded. Prevents re-uploading the same snapshot. |
| **File hash cache** | `~/.observal/.file_hash_cache.json` | Maps `{filepath: {mtime, hash}}` to avoid re-reading unchanged files on every session push. |

### What Gets Sent to Server

| What | When | Endpoint | Size | Contains |
|---|---|---|---|---|
| `layer_hash` (string) | Every session push | `POST /api/v1/ingest/session` (existing field) | 16 chars | sha256 hash representing the full IDE config state |
| **Layer snapshot** (JSON) | Only when `layer_hash` changes from last upload | `POST /api/v1/layer-snapshots` (new) | ~10-50KB compressed | Full file list with content (see below) |

That's it. Two things: a 16-char hash on every push, and a full snapshot only when something changes.

### Layer Snapshot Contents (uploaded on change)

```
{
  "hash": "<layer_hash>",         // same 16-char hash sent in ingest
  "ide": "claude-code",
  "files": [
    {
      "path": "CLAUDE.md",           // relative to IDE config root
      "hash": "sha256-<full>",        // sha256 of this file's content
      "size": 2048,
      "source": "user",              // "user" or "observal"
      "content": "<full file text>"   // actual content for diffing
    },
    ...
  ],
  "lockfile_hash": "<sha256[:16] of lockfile.json>"
}
```

### Hash Glossary

| Hash | What it hashes | Length | Purpose |
|---|---|---|---|
| `layer_hash` | Sorted list of `(path, file_hash)` pairs from the IDE config scan | 16 hex chars | Identifies the full IDE state. Changes when ANY config file is added/modified/removed. Stored on every session event in ClickHouse. |
| `lockfile_hash` | Contents of `~/.observal/lockfile.json` | 16 hex chars | Quick check if Observal-managed component versions changed (subset of layer). Embedded in snapshot. |
| `integrity` (per lock file entry) | Content of file at install time | Full sha256 | Detects if user modified an Observal-installed file after pull/install. |
| Per-file `hash` in snapshot | Content of that specific file | Full sha256 | Enables server-side diffing between two snapshots. |

### Data Flow Summary

```
                                    ┌─────────────────────────────┐
   On every session push:           │   POST /ingest/session      │
   ─────────────────────────────▶   │   { ..., layer_hash: "abc" }│
                                    └─────────────────────────────┘

   Only when layer_hash changes:    ┌─────────────────────────────┐
   ─────────────────────────────▶   │   POST /layer-snapshots     │
                                    │   { hash, ide, files[...] } │
                                    └─────────────────────────────┘

   Never uploaded:                  ~/.observal/lockfile.json (local only)
                                    ~/.observal/.file_hash_cache.json
                                    ~/.observal/.last_uploaded_layer
```
