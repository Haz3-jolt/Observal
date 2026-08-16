# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Hash-based synchronization coverage for bundled Observal skills."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from observal_cli import skill_installer
from observal_shared.harness_registry import HARNESS_REGISTRY


def _write_skill(root: Path, name: str = "example") -> Path:
    skill = root / name
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    (skill / "references" / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
    return skill


def test_directory_hash_detects_content_and_extra_file_drift(tmp_path: Path):
    source = _write_skill(tmp_path / "source")
    installed = tmp_path / "installed"
    shutil.copytree(source, installed)

    expected = skill_installer._directory_hash(source)
    assert expected is not None and len(expected) == 64
    assert skill_installer._directory_hash(installed) == expected

    (installed / "SKILL.md").write_text("changed", encoding="utf-8")
    assert skill_installer._directory_hash(installed) != expected

    shutil.copy2(source / "SKILL.md", installed / "SKILL.md")
    (installed / "extra.md").write_text("drift", encoding="utf-8")
    assert skill_installer._directory_hash(installed) != expected


def test_sync_replaces_entire_directory_only_when_hash_differs(tmp_path: Path):
    source = _write_skill(tmp_path / "source")
    target = tmp_path / "skills" / "example"
    skill_file = target / "SKILL.md"

    assert skill_installer._sync_skill_directory(source, skill_file) is True
    inode = target.stat().st_ino
    assert skill_installer._sync_skill_directory(source, skill_file) is False
    assert target.stat().st_ino == inode

    (target / "SKILL.md").write_text("user edit", encoding="utf-8")
    (target / "extra.md").write_text("stale", encoding="utf-8")

    assert skill_installer._sync_skill_directory(source, skill_file) is True
    assert not (target / "extra.md").exists()
    assert skill_installer._directory_hash(target) == skill_installer._directory_hash(source)


def test_every_detected_harness_syncs_all_skill_trees_and_migrates_antigravity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bundled = tmp_path / "bundled"
    for name in skill_installer._SKILL_DIRS:
        _write_skill(bundled, name)
    monkeypatch.setattr(skill_installer, "_SKILLS_BASE", bundled)
    monkeypatch.setenv("HOME", str(tmp_path))

    registry = {
        "pi": {
            "display_name": "Pi",
            "config_dir": ".pi",
            "skills": {"user": "~/.pi/agent/skills/{name}/SKILL.md"},
        },
        "antigravity": {
            "display_name": "Antigravity",
            "config_dir": ".agents",
            "skills": {"user": "~/.gemini/antigravity-cli/skills/{name}/SKILL.md"},
        },
    }
    import observal_shared.harness_registry as harness_registry

    monkeypatch.setattr(harness_registry, "HARNESS_REGISTRY", registry)
    (tmp_path / ".pi").mkdir()
    antigravity_skills = tmp_path / ".gemini/antigravity-cli/skills"
    (antigravity_skills / "references").mkdir(parents=True)
    for name in skill_installer._SKILL_DIRS:
        (antigravity_skills / f"{name}.md").write_text("legacy", encoding="utf-8")
        (antigravity_skills / "references" / f"{name}.md").write_text("legacy", encoding="utf-8")

    assert skill_installer.sync_observal_skills(install_missing=True) == ["Pi", "Antigravity"]

    for name in skill_installer._SKILL_DIRS:
        source = bundled / name
        pi_target = tmp_path / ".pi/agent/skills" / name
        antigravity_target = antigravity_skills / name
        assert skill_installer._directory_hash(pi_target) == skill_installer._directory_hash(source)
        assert skill_installer._directory_hash(antigravity_target) == skill_installer._directory_hash(source)
        assert not (antigravity_skills / f"{name}.md").exists()
    assert not (antigravity_skills / "references").exists()

    drift = tmp_path / ".pi/agent/skills/observal/extra.md"
    drift.write_text("stale", encoding="utf-8")
    skill_installer.sync_observal_skills()
    assert not drift.exists()


def test_startup_sync_does_not_install_into_an_unmanaged_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundled = tmp_path / "bundled"
    for name in skill_installer._SKILL_DIRS:
        _write_skill(bundled, name)
    monkeypatch.setattr(skill_installer, "_SKILLS_BASE", bundled)
    monkeypatch.setenv("HOME", str(tmp_path))

    import observal_shared.harness_registry as harness_registry

    monkeypatch.setattr(
        harness_registry,
        "HARNESS_REGISTRY",
        {
            "pi": {
                "display_name": "Pi",
                "config_dir": ".pi",
                "skills": {"user": "~/.pi/agent/skills/{name}/SKILL.md"},
            }
        },
    )
    (tmp_path / ".pi").mkdir()

    assert skill_installer.sync_observal_skills() == []
    assert not (tmp_path / ".pi/agent/skills").exists()


def test_startup_sync_failure_is_a_categorized_json_error(monkeypatch: pytest.MonkeyPatch):
    import observal_cli.main as main

    def deny_sync() -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(skill_installer, "sync_observal_skills", deny_sync)
    monkeypatch.setattr(main, "_migrate_legacy_mcp_configs", lambda: None)

    result = CliRunner().invoke(main.app, ["scan", "--output", "json"])

    assert result.exit_code == 4
    assert result.stdout == ""
    error = json.loads(result.stderr)["error"]
    assert error["category"] == "permission"
    assert error["operation"] == "Synchronize bundled skills"


def test_antigravity_uses_directory_skill_layout():
    assert HARNESS_REGISTRY["antigravity"]["skills"] == {
        "project": ".agents/skills/{name}/SKILL.md",
        "user": "~/.gemini/antigravity-cli/skills/{name}/SKILL.md",
    }
