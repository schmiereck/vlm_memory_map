import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class MapObject:
    id:          str
    description: str
    area:        Optional[str] = None   # e.g. "Wohnzimmer", "Garten"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "MapObject":
        return MapObject(
            id         =data["id"],
            description=data["description"],
            area       =data.get("area"),
        )


class ObjectManager:
    """Manages named objects in the robot's spatial memory."""

    def __init__(self, file_path: str = "objects.json"):
        self._file_path = Path(file_path)
        self._objects: dict[str, MapObject] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, obj: MapObject) -> None:
        """Add or overwrite an object entry."""
        self._objects[obj.id] = obj

    def get(self, obj_id: str) -> Optional[MapObject]:
        return self._objects.get(obj_id)

    def get_all(
        self,
        filter_fn=None,
        area: Optional[str] = None,
    ) -> list[MapObject]:
        """
        Return objects, optionally filtered by area and/or predicate.

        Examples:
            manager.get_all()
            manager.get_all(area="Wohnzimmer")
            manager.get_all(filter_fn=lambda o: "Tisch" in o.description)
        """
        objects = list(self._objects.values())
        if area is not None:
            objects = [o for o in objects if o.area == area]
        if filter_fn is not None:
            objects = [o for o in objects if filter_fn(o)]
        return objects

    def update(
        self,
        obj_id:      str,
        description: Optional[str] = None,
        area:        Optional[str] = None,
    ) -> bool:
        obj = self._objects.get(obj_id)
        if obj is None:
            return False
        if description is not None:
            obj.description = description
        if area is not None:
            obj.area = area
        return True

    def delete(self, obj_id: str) -> bool:
        if obj_id not in self._objects:
            return False
        del self._objects[obj_id]
        return True

    def areas(self) -> list[str]:
        """Return sorted list of all known area names."""
        return sorted({o.area for o in self._objects.values() if o.area})

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        data = [obj.to_dict() for obj in self._objects.values()]
        self._file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load(self) -> None:
        if not self._file_path.exists():
            return
        data = json.loads(self._file_path.read_text())
        self._objects = {e["id"]: MapObject.from_dict(e) for e in data}

    def __len__(self) -> int:
        return len(self._objects)

    def __repr__(self) -> str:
        return f"ObjectManager({len(self._objects)} objects, file='{self._file_path}')"
