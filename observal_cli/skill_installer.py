# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Install and synchronize the bundled Observal skills."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

from rich import print as rprint

_SKILL_DIRS = (
    "observal",
    "observal-agents",
    "observal-registry",
    "observal-ops",
    "observal-admin",
    "observal-advanced",
)
_SKILLS_BASE = Path(__file__).parent / "skills"


def _hash_value(digest: object, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _directory_hash(root: Path) -> str | None:
    """Return a deterministic SHA-256 hash for a complete directory tree."""
    if not root.is_dir() or root.is_symlink():
        return None

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        _hash_value(digest, path.relative_to(root).as_posix().encode())
        if path.is_symlink():
            _hash_value(digest, b"link")
            _hash_value(digest, os.readlink(path).encode())
        elif path.is_dir():
            _hash_value(digest, b"directory")
        elif path.is_file():
            _hash_value(digest, b"file")
            _hash_value(digest, str(stat.S_IMODE(path.stat().st_mode)).encode())
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
        else:
            raise OSError(f"Unsupported file type in bundled skill: {path}")
    return digest.hexdigest()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _replace_directory(source: Path, target: Path) -> None:
    """Replace a managed directory as one rollback-safe filesystem operation."""
    target.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f".{target.name}.sync-", dir=target.parent))
    staged = work_dir / "new"
    backup = work_dir / "old"
    had_target = target.exists() or target.is_symlink()

    try:
        shutil.copytree(source, staged)
        if had_target:
            target.rename(backup)
        try:
            staged.rename(target)
        except OSError:
            if had_target and backup.exists():
                backup.rename(target)
            raise
        _remove_path(backup)
    finally:
        _remove_path(work_dir)


def _sync_skill_directory(source_dir: Path, skill_file: Path) -> bool:
    """Hash-check one managed skill and replace its entire directory on drift."""
    if skill_file.name != "SKILL.md":
        raise OSError(f"Bundled skills require a directory ending in SKILL.md: {skill_file}")
    target_dir = skill_file.parent
    if _directory_hash(source_dir) == _directory_hash(target_dir):
        return False
    _replace_directory(source_dir, target_dir)
    return True


def _remove_antigravity_legacy_files(source_dir: Path, skill_file: Path) -> None:
    """Remove the former flat-file layout after Antigravity moves to skill directories."""
    skills_root = skill_file.parent.parent
    _remove_path(skills_root / f"{source_dir.name}.md")
    for source in source_dir.rglob("*"):
        if source.is_file() and source.name != "SKILL.md":
            _remove_path(skills_root / source.relative_to(source_dir))
    references = skills_root / "references"
    if references.is_dir() and not any(references.iterdir()):
        references.rmdir()


def _bundled_sources() -> dict[str, Path]:
    sources = {name: _SKILLS_BASE / name for name in _SKILL_DIRS}
    missing = [str(path / "SKILL.md") for path in sources.values() if not (path / "SKILL.md").is_file()]
    if missing:
        raise FileNotFoundError(f"Bundled Observal skills are incomplete: {', '.join(missing)}")
    return sources


def _user_harness_dir(user_path: str) -> Path:
    target = Path(user_path.replace("{name}", "observal").replace("~", str(Path.home())))
    return next((parent.parent for parent in target.parents if parent.name == "skills"), target.parent)


def sync_observal_skills(*, install_missing: bool = False) -> list[str]:
    """Synchronize installed skill bundles for every detected harness."""
    from observal_shared.harness_registry import HARNESS_REGISTRY

    sources = _bundled_sources()
    detected: list[str] = []
    for harness, spec in HARNESS_REGISTRY.items():
        user_path = (spec.get("skills") or {}).get("user")
        if not user_path:
            continue
        config_dir = Path.home() / spec.get("config_dir", "")
        if not config_dir.exists() and not _user_harness_dir(user_path).exists():
            continue
        targets = {name: Path(user_path.replace("{name}", name).replace("~", str(Path.home()))) for name in sources}
        has_bundle = any(
            skill_file.parent.exists() or skill_file.parent.is_symlink() for skill_file in targets.values()
        )
        if harness == "antigravity":
            has_bundle = has_bundle or any(
                (skill_file.parent.parent / f"{name}.md").is_file() for name, skill_file in targets.items()
            )
        if not install_missing and not has_bundle:
            continue
        for name, source_dir in sources.items():
            skill_file = targets[name]
            _sync_skill_directory(source_dir, skill_file)
            if harness == "antigravity":
                _remove_antigravity_legacy_files(source_dir, skill_file)
        detected.append(spec["display_name"])
    return detected


def install_observal_skill() -> None:
    """Install current bundled skills to every detected harness."""
    import json as _json

    installed = sync_observal_skills(install_missing=True)

    # Kiro-specific: ensure the active agent has skill resources wired up.
    _kiro_skill_resource = "skill://~/.kiro/skills/*/SKILL.md"
    kiro_settings = Path.home() / ".kiro" / "settings" / "cli.json"
    if kiro_settings.exists():
        try:
            settings_data = _json.loads(kiro_settings.read_text())
            active_agent = settings_data.get("chat.defaultAgent", "")
            if active_agent:
                agent_profile = Path.home() / ".kiro" / "agents" / f"{active_agent}.json"
                if agent_profile.exists():
                    agent_data = _json.loads(agent_profile.read_text())
                    resources = agent_data.get("resources", [])
                    if _kiro_skill_resource not in resources:
                        resources.append(_kiro_skill_resource)
                        agent_data["resources"] = resources
                        agent_profile.write_text(_json.dumps(agent_data, indent=2) + "\n")
        except (OSError, _json.JSONDecodeError):
            pass

    if installed:
        rprint(f"\n[green]✓ Observal skills synchronized for:[/green] {', '.join(installed)}")
        rprint('[dim]  LLMs can now use Observal commands directly (for example, "create a PR agent for kiro")[/dim]')
