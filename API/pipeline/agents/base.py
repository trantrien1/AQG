"""BaseAgent — interface chung cho tất cả agents."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..skills.registry import (
    skills_for_agent,
    get_skill_instructions,
    get_skill_metadata,
    validate_skill_references,
)


class BaseAgent:
    """Interface chung. Mỗi agent có tên, nhận message, trả message."""

    def __init__(self, name: str, skills: Optional[List[str]] = None,
                 use_skills: bool = True):
        self.name = name
        self.use_skills = use_skills
        self.skills = list(skills) if skills is not None else skills_for_agent(
            name, use_skills=use_skills,
        )

    def skill_metadata(self) -> List[Dict[str, str]]:
        return [get_skill_metadata(name) for name in self.skills]

    def skill_instructions(self) -> str:
        chunks = []
        for name in self.skills:
            body = get_skill_instructions(name)
            if body:
                chunks.append(f'## Skill: {name}\n{body}')
        return '\n\n'.join(chunks).strip()

    def missing_skills(self) -> List[str]:
        return validate_skill_references(self.skills)

    def run(self, *args, **kwargs) -> Any:
        raise NotImplementedError(f'{self.name}.run() chưa được implement')

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(name={self.name!r})'
