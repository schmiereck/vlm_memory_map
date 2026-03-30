import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Relation:
    object_a: str
    relation: str
    object_b: str
    area:     Optional[str] = None   # e.g. "Wohnzimmer", "Garten"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Relation":
        return Relation(
            object_a=data["object_a"],
            relation=data["relation"],
            object_b=data["object_b"],
            area    =data.get("area"),
        )

    def __repr__(self) -> str:
        area_str = f" [{self.area}]" if self.area else ""
        return f"{self.object_a}: {self.relation}: {self.object_b}{area_str}"


class RelationManager:
    """Manages descriptive spatial relations between named objects."""

    def __init__(self, file_path: str = "relations.json"):
        self._file_path = Path(file_path)
        self._relations: list[Relation] = []

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, relation: Relation) -> None:
        """Add a relation. Allows multiple relations between the same pair."""
        self._relations.append(relation)

    def get_all(
        self,
        object_a: Optional[str] = None,
        object_b: Optional[str] = None,
        area:     Optional[str] = None,
    ) -> list[Relation]:
        """
        Return relations, optionally filtered.

        Args:
            object_a: Filter by subject object id.
            object_b: Filter by target object id.
            area:     Filter by area name.

        Examples:
            manager.get_all()
            manager.get_all(object_a="W1")
            manager.get_all(object_b="W2")
            manager.get_all("W1", "W2")
            manager.get_all(area="Wohnzimmer")
        """
        result = self._relations
        if object_a is not None:
            result = [r for r in result if r.object_a == object_a]
        if object_b is not None:
            result = [r for r in result if r.object_b == object_b]
        if area is not None:
            result = [r for r in result if r.area == area]
        return result

    def update(
        self,
        object_a:     str,
        object_b:     str,
        new_relation: str,
        area:         Optional[str] = None,
    ) -> int:
        """
        Update relation description for all entries between A and B.
        Optionally also update area. Returns number of updated entries.
        """
        matches = [
            r for r in self._relations
            if r.object_a == object_a and r.object_b == object_b
        ]
        for r in matches:
            r.relation = new_relation
            if area is not None:
                r.area = area
        return len(matches)

    def delete(
        self,
        object_a: str,
        object_b: str,
        relation: Optional[str] = None,
    ) -> int:
        """
        Delete relations between A and B.
        If relation is given, only entries with that exact relation are removed.
        Returns number of deleted entries.
        """
        before = len(self._relations)
        self._relations = [
            r for r in self._relations
            if not (
                r.object_a == object_a
                and r.object_b == object_b
                and (relation is None or r.relation == relation)
            )
        ]
        return before - len(self._relations)

    def areas(self) -> list[str]:
        """Return sorted list of all known area names."""
        return sorted({r.area for r in self._relations if r.area})

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        data = [r.to_dict() for r in self._relations]
        self._file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load(self) -> None:
        if not self._file_path.exists():
            return
        data = json.loads(self._file_path.read_text())
        self._relations = [Relation.from_dict(e) for e in data]

    def __len__(self) -> int:
        return len(self._relations)

    def __repr__(self) -> str:
        return f"RelationManager({len(self._relations)} relations, file='{self._file_path}')"
