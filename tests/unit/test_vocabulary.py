"""The vocabulary rules of docs/glossary.md, enforced.

The core is domain-neutral (CLAUDE.md): education words belong to presets, and we say
"anonymous", never "blind". Only the preset files may name them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "previewit"

# Files that define preset content: education words are their job.
PRESET_FILES = {"domain/tenancy.py", "domain/rubrics.py"}

FORBIDDEN = {
    "course": r"\bcourses?\b",
    "student": r"\bstudents?\b",
    "teacher": r"\bteachers?\b",
    "assignment": r"\bassignments?\b",  # Education's word for a Call; reviewers are *allocated*
    "blind": r"\bblind\w*|_blind\b",  # say anonymous
}


def _core_files() -> list[Path]:
    files: list[Path] = []
    for folder in ("domain", "application", "plugins"):
        files += sorted((SRC / folder).rglob("*.py"))
    files += sorted((SRC / "adapters" / "web" / "templates").rglob("*.html"))
    return [f for f in files if f.relative_to(SRC).as_posix() not in PRESET_FILES]


@pytest.mark.parametrize("word", sorted(FORBIDDEN))
def test_core_does_not_use_preset_or_banned_words(word: str) -> None:
    pattern = re.compile(FORBIDDEN[word], re.IGNORECASE)
    hits = [
        f"{f.relative_to(SRC)}:{n}: {line.strip()}"
        for f in _core_files()
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not hits, f"'{word}' is banned outside presets (docs/glossary.md):\n" + "\n".join(hits)


def test_glossary_exists_and_is_linked_from_claude_md() -> None:
    root = SRC.parents[1]
    assert (root / "docs" / "glossary.md").is_file()
    assert "docs/glossary.md" in (root / "CLAUDE.md").read_text(encoding="utf-8")
