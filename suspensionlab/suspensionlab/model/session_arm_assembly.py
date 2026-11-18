"""Явная сеансовая ссылка на сохранённый снимок, без изменений форматов проекта."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .entities import Project
from .kim_format import KimFormatError, compare_lower_arm_source, read_document
from .scheme_arm_assembly import validate_scheme_arm_assembly


@dataclass(frozen=True, slots=True)
class SessionArmAssembly:
    """Один сохранённый документ и конкретный объект проекта текущего сеанса.

    Совпадение контрольных точек не доказывает принадлежность или пригодность.
    Ссылка не сериализуется, исходный путь и файл никогда не изменяются.
    """
    project: Project
    path: Path
    saved_document: dict[str, Any]

    @classmethod
    def from_saved(cls, project: Project, path: Path, saved_document: dict[str, Any]) -> SessionArmAssembly:
        validate_scheme_arm_assembly(saved_document)
        absolute = path.absolute()
        if read_document(absolute, 'assembly') != saved_document:
            raise KimFormatError('saved assembly changed or unavailable')
        return cls(project, absolute, deepcopy(saved_document))

    def source_matches(self, project: Project) -> bool:
        if project is not self.project:
            return False
        return all(compare_lower_arm_source(part, project) for part in self.saved_document['parts'][:2])

    def load_verified(self, project: Project) -> dict[str, Any]:
        """Нельзя незаметно открыть подменённый или изменённый снаружи файл."""
        if project is not self.project:
            raise KimFormatError('project replaced')
        document = read_document(self.path, 'assembly')
        if document != self.saved_document:
            raise KimFormatError('assembly changed outside the session')
        return document
