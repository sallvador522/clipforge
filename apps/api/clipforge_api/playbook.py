"""Loader for the runtime Professional Editing Playbook (Milestone 6B-PREP).

The playbook is a versioned Markdown asset for future Muse Spark system
instructions. Loading it performs no network or model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PLAYBOOK_PATH = Path(__file__).resolve().parent / "prompts" / "professional_editing_director.md"

REQUIRED_SECTIONS: tuple[str, ...] = (
    "Role",
    "Editing Philosophy",
    "Cinematographic Principles",
    "Decision-Making",
    "Quality Standards",
    "Editing Operations",
    "User Communication",
    "Clarification",
    "Tool Boundaries",
    "Verification",
    "Output Contract",
    "Safety",
)


class PlaybookError(ValueError):
    pass


@dataclass(frozen=True)
class Playbook:
    path: Path
    version: str
    text: str
    sections: tuple[str, ...]

    def section(self, name: str) -> str:
        """Return the body of one section (without its heading)."""
        pattern = re.compile(rf"^##\s+{re.escape(name)}\s*$", re.MULTILINE)
        match = pattern.search(self.text)
        if not match:
            raise PlaybookError(f"Section {name!r} not found.")
        rest = self.text[match.end():]
        next_heading = re.search(r"^##\s+", rest, re.MULTILINE)
        return (rest[: next_heading.start()] if next_heading else rest).strip()


def _parse_sections(text: str) -> tuple[str, ...]:
    return tuple(match.group(1).strip() for match in re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE))


def load_playbook(path: str | Path | None = None) -> Playbook:
    target = Path(path) if path is not None else PLAYBOOK_PATH
    if not target.is_file():
        raise PlaybookError(f"Professional editing playbook not found: {target}")
    text = target.read_text(encoding="utf-8").strip()
    if not text:
        raise PlaybookError("Professional editing playbook is empty.")

    version_match = re.search(r"^Version:\s*(\S+)\s*$", text, re.MULTILINE)
    if not version_match:
        raise PlaybookError("Playbook must declare 'Version: <x.y>'.")

    sections = _parse_sections(text)
    missing = [section for section in REQUIRED_SECTIONS if section not in sections]
    if missing:
        raise PlaybookError(f"Playbook is missing required sections: {missing}")

    for section in REQUIRED_SECTIONS:
        if not _section_body(text, section):
            raise PlaybookError(f"Playbook section {section!r} is empty.")

    if "capability registry" not in text.lower():
        raise PlaybookError("Playbook must defer to the capability registry.")

    return Playbook(path=target, version=version_match.group(1), text=text, sections=sections)


def _section_body(text: str, name: str) -> str:
    match = re.search(rf"^##\s+{re.escape(name)}\s*$", text, re.MULTILINE)
    if not match:
        return ""
    rest = text[match.end():]
    next_heading = re.search(r"^##\s+", rest, re.MULTILINE)
    return (rest[: next_heading.start()] if next_heading else rest).strip()


@lru_cache(maxsize=1)
def default_playbook() -> Playbook:
    return load_playbook(PLAYBOOK_PATH)
