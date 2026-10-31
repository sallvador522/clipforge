"""Skill inventory and runtime playbook tests (Milestone 6B-PREP)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clipforge_api.playbook import (
    REQUIRED_SECTIONS,
    PlaybookError,
    default_playbook,
    load_playbook,
)

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIRS = [ROOT / ".opencode" / "skills", ROOT / ".agents" / "skills"]


def _frontmatter(skill_file: Path) -> dict[str, str]:
    text = skill_file.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{skill_file} has no YAML frontmatter"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def _skill_files() -> list[Path]:
    files: list[Path] = []
    for directory in SKILL_DIRS:
        if directory.is_dir():
            files.extend(sorted(directory.glob("*/SKILL.md")))
    return files


def test_skill_inventory_is_within_limit_and_includes_director():
    files = _skill_files()
    assert len(files) <= 10, f"Project skill limit exceeded: {len(files)}"
    names = {path.parent.name for path in files}
    assert "clipforge-editing-director" in names
    assert len(files) == 9


def test_every_skill_has_matching_name_and_description():
    for path in _skill_files():
        fields = _frontmatter(path)
        assert fields.get("name") == path.parent.name, f"{path} name must match its directory"
        assert fields.get("description"), f"{path} needs a description"


def test_director_skill_covers_required_domains():
    text = (ROOT / ".opencode" / "skills" / "clipforge-editing-director" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for topic in (
        "Cinematography",
        "Professional Editing",
        "Subject and Background",
        "Colour",
        "Audio",
        "Social Formats",
    ):
        assert topic in text
    assert "not SAM" in text
    assert "Muse Image" in text
    assert "disabled" in text.lower()
    assert "capability registry" in text.lower()


def test_default_playbook_loads_with_all_sections():
    playbook = default_playbook()
    assert playbook.version in ("1.0", "1.1")
    assert all(section in playbook.sections for section in REQUIRED_SECTIONS)
    for section in REQUIRED_SECTIONS:
        assert playbook.section(section), f"{section} is empty"


def test_playbook_defers_to_capability_registry_and_labels_limits():
    text = default_playbook().text.lower()
    assert "capability registry" in text
    assert "not sam" in text
    assert "muse image" in text
    assert "disabled" in text
    assert "never plan them" in text or "never plan" in text
    assert "timeline.trim" in text
    assert "three" in text or "3" in text


def test_playbook_rejects_missing_section(tmp_path):
    text = default_playbook().text
    broken = re.sub(r"^## Verification\s*$", "## Removed Section", text, flags=re.MULTILINE)
    path = tmp_path / "broken.md"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(PlaybookError):
        load_playbook(path)


def test_playbook_rejects_missing_file(tmp_path):
    with pytest.raises(PlaybookError):
        load_playbook(tmp_path / "missing.md")


def test_playbook_is_not_a_runtime_model_call():
    # The loader is pure filesystem/Pydantic-free; importing/calling it must not
    # require credentials or any HTTP client.
    import inspect

    from clipforge_api import playbook as playbook_module

    source = inspect.getsource(playbook_module)
    assert "httpx" not in source
    assert "requests" not in source
    assert "api_key" not in source.lower()
