"""Skill metadata registry for local pipeline skills."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List


def list_skill_metadata(root: Path | None = None) -> List[Dict[str, str]]:
    """Read SKILL.md frontmatter without requiring a YAML dependency."""
    root = root or Path(__file__).resolve().parent
    out: List[Dict[str, str]] = []
    for skill_md in sorted(root.glob('*/SKILL.md')):
        out.append(_read_frontmatter(skill_md))
    return out


def list_skill_names(root: Path | None = None) -> List[str]:
    return [
        meta['name']
        for meta in list_skill_metadata(root)
        if meta.get('name')
    ]


def get_skill_metadata(name: str, root: Path | None = None) -> Dict[str, str]:
    for meta in list_skill_metadata(root):
        if meta.get('name') == name:
            return meta
    return {'name': name, 'missing': 'true'}


def get_skill_instructions(name: str, root: Path | None = None) -> str:
    """Return the non-frontmatter body for a skill."""
    root = root or Path(__file__).resolve().parent
    path = root / name / 'SKILL.md'
    if not path.exists():
        return ''
    text = path.read_text(encoding='utf-8')
    if not text.startswith('---'):
        return text.strip()
    end = text.find('---', 3)
    if end < 0:
        return text.strip()
    return text[end + 3:].strip()


def validate_skill_references(
    references: Iterable[str],
    root: Path | None = None,
) -> List[str]:
    available = set(list_skill_names(root))
    return sorted({name for name in references if name not in available})


def agent_skill_manifest(
    agent_skills: Dict[str, List[str]],
    root: Path | None = None,
) -> Dict[str, List[Dict[str, str]]]:
    """Return frontmatter metadata grouped by agent."""
    return {
        agent: [get_skill_metadata(name, root) for name in skills]
        for agent, skills in agent_skills.items()
    }


def _read_frontmatter(path: Path) -> Dict[str, str]:
    text = path.read_text(encoding='utf-8')
    meta: Dict[str, str] = {'path': str(path)}
    if not text.startswith('---'):
        return meta
    end = text.find('---', 3)
    if end < 0:
        return meta
    for line in text[3:end].splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        meta[key.strip()] = value.strip().strip('"')
    return meta
