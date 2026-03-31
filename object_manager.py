import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Color palette — assigned rolling to new objects for visual distinction
# ---------------------------------------------------------------------------

OBJECT_COLORS: dict[str, tuple[int, int, int]] = {
    # Warm
    "RED":        (220,  50,  50),
    "ORANGE":     (230, 130,  30),
    "YELLOW":     (220, 200,   0),
    "GOLD":       (180, 140,   0),
    "BROWN":      (140,  80,  30),
    "CORAL":      (240, 120, 100),
    # Cool
    "BLUE":       ( 40,  80, 220),
    "NAVY":       ( 20,  40, 140),
    "CYAN":       (  0, 190, 210),
    "TEAL":       (  0, 140, 140),
    "SKY":        ( 80, 160, 230),
    "STEEL":      ( 90, 120, 160),
    # Green / Yellow-Green
    "GREEN":      ( 40, 180,  60),
    "DARK_GREEN": ( 20, 110,  40),
    "LIME":       (140, 210,   0),
    "OLIVE":      (120, 130,  20),
    # Purple / Pink / Neutral
    "PURPLE":     (140,  50, 200),
    "VIOLET":     ( 90,  60, 180),
    "MAGENTA":    (210,  40, 160),
    "PINK":       (230, 130, 180),
    "MAROON":     (130,  20,  60),
}

_COLOR_CYCLE: list[str] = list(OBJECT_COLORS.keys())


@dataclass
class MapObject:
    id:          str
    description: str
    area:        Optional[str] = None   # e.g. "Wohnzimmer", "Garten"
    color:       Optional[str] = None   # color name from OBJECT_COLORS

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "description": self.description,
            "area":        self.area,
            "color":       self.color,
        }

    @staticmethod
    def from_dict(data: dict) -> "MapObject":
        return MapObject(
            id         =data["id"],
            description=data["description"],
            area       =data.get("area"),
            color      =data.get("color"),
        )


class ObjectManager:
    """Manages named objects in the robot's spatial memory."""

    def __init__(self, file_path: str = "objects.json"):
        self._file_path  = Path(file_path)
        self._objects:     dict[str, MapObject] = {}
        self._color_index: int = 0

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, obj: MapObject) -> None:
        """Add or overwrite an object entry. New objects get a rolling color."""
        if obj.color is None and obj.id not in self._objects:
            obj.color = _COLOR_CYCLE[self._color_index % len(_COLOR_CYCLE)]
            self._color_index += 1
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
        # Assign colors to objects that were saved without one
        for obj in self._objects.values():
            if obj.color is None:
                obj.color = _COLOR_CYCLE[self._color_index % len(_COLOR_CYCLE)]
                self._color_index += 1

    def __len__(self) -> int:
        return len(self._objects)

    def __repr__(self) -> str:
        return f"ObjectManager({len(self._objects)} objects, file='{self._file_path}')"
