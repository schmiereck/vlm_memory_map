import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ----------------------------------------------------------------------
# Value objects
# ----------------------------------------------------------------------

@dataclass
class Vec3:
    """3D vector where y and z are optional (None = not set)."""
    x: float
    y: Optional[float] = None
    z: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Vec3":
        return Vec3(x=data["x"], y=data.get("y"), z=data.get("z"))


@dataclass
class ObjectCoordinate:
    id:       str
    position: Vec3
    size:     Optional[Vec3] = None
    rotation: Optional[Vec3] = None   # z = yaw in radians
    area:     Optional[str]  = None   # e.g. "Wohnzimmer", "Garten"

    def to_dict(self) -> dict:
        return {
            "id":       self.id,
            "position": self.position.to_dict(),
            "size":     self.size.to_dict()     if self.size     else None,
            "rotation": self.rotation.to_dict() if self.rotation else None,
            "area":     self.area,
        }

    @staticmethod
    def from_dict(data: dict) -> "ObjectCoordinate":
        return ObjectCoordinate(
            id      =data["id"],
            position=Vec3.from_dict(data["position"]),
            size    =Vec3.from_dict(data["size"])     if data.get("size")     else None,
            rotation=Vec3.from_dict(data["rotation"]) if data.get("rotation") else None,
            area    =data.get("area"),
        )

    def __repr__(self) -> str:
        return (
            f"{self.id}[{self.area}]: pos={self.position} "
            f"size={self.size} rot={self.rotation}"
        )


@dataclass
class TracePoint:
    """Minimal pose snapshot for map rendering."""
    x:   float
    y:   float
    yaw: float


# ----------------------------------------------------------------------
# Manager
# ----------------------------------------------------------------------

class CoordinateManager:
    """
    Manages 2D/3D positions, sizes and rotations of environment objects.
    Robot pose is handled by PositionManager and passed in as parameters.
    """

    def __init__(self, file_path: str = "coordinates.json"):
        self._file_path = Path(file_path)
        self._objects: dict[str, ObjectCoordinate] = {}

    # ------------------------------------------------------------------
    # Object CRUD
    # ------------------------------------------------------------------

    def add(self, obj: ObjectCoordinate) -> None:
        self._objects[obj.id] = obj

    def get(self, obj_id: str) -> Optional[ObjectCoordinate]:
        return self._objects.get(obj_id)

    def get_all(
        self,
        obj_id: Optional[str] = None,
        area:   Optional[str] = None,
    ) -> list[ObjectCoordinate]:
        """
        Return objects, optionally filtered by id prefix and/or area.

        Examples:
            manager.get_all()
            manager.get_all("T")
            manager.get_all(area="Wohnzimmer")
            manager.get_all("T", area="Wohnzimmer")
        """
        objects = list(self._objects.values())
        if obj_id is not None:
            objects = [o for o in objects if o.id.startswith(obj_id)]
        if area is not None:
            objects = [o for o in objects if o.area == area]
        return objects

    def update(
        self,
        obj_id:   str,
        position: Optional[Vec3] = None,
        size:     Optional[Vec3] = None,
        rotation: Optional[Vec3] = None,
        area:     Optional[str]  = None,
    ) -> bool:
        obj = self._objects.get(obj_id)
        if obj is None:
            return False
        if position is not None:
            obj.position = position
        if size is not None:
            obj.size = size
        if rotation is not None:
            obj.rotation = rotation
        if area is not None:
            obj.area = area
        return True

    def delete(self, obj_id: str) -> bool:
        if obj_id not in self._objects:
            return False
        del self._objects[obj_id]
        return True

    def rotate_all(self, delta_yaw: float) -> None:
        """
        Rotate all object positions around the world origin by delta_yaw radians.
        Used for global map correction when the robot's heading estimate drifted.
        """
        cos_a = math.cos(delta_yaw)
        sin_a = math.sin(delta_yaw)
        for obj in self._objects.values():
            x = obj.position.x
            y = obj.position.y or 0.0
            obj.position.x = x * cos_a - y * sin_a
            obj.position.y = x * sin_a + y * cos_a
            if obj.rotation and obj.rotation.z is not None:
                obj.rotation.z += delta_yaw

    def areas(self) -> list[str]:
        return sorted({o.area for o in self._objects.values() if o.area})

    # ------------------------------------------------------------------
    # Map rendering
    # ------------------------------------------------------------------

    def get_map_image(
        self,
        robot_x:     float = 0.0,
        robot_y:     float = 0.0,
        robot_yaw:   float = 0.0,
        view_size_x: float = 5.0,
        view_size_y: float = 5.0,
        pixel_size:  int   = 600,
        trace:       Optional[list[TracePoint]] = None,
        area:        Optional[str] = None,
    ) -> "Image.Image":
        """
        Render a top-down map image. Robot is always centered, pointing up.

        Args:
            robot_x/y:    Robot world position in meters.
            robot_yaw:    Robot heading in radians.
            view_size_x:  Visible width in world meters.
            view_size_y:  Visible height in world meters.
            pixel_size:   Output image size in pixels (square).
            trace:        Optional movement trace to draw.
            area:         If given, render only objects in that area.
        """
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow not installed — run: pip install Pillow")

        scale_x = pixel_size / view_size_x
        scale_y = pixel_size / view_size_y

        def world_to_pixel(wx: float, wy: float) -> tuple[int, int]:
            dx = wx - robot_x
            dy = wy - robot_y
            cos_h = math.cos(-robot_yaw)
            sin_h = math.sin(-robot_yaw)
            rx =  dx * cos_h - dy * sin_h
            ry =  dx * sin_h + dy * cos_h
            px = int(pixel_size / 2 + rx * scale_x)
            py = int(pixel_size / 2 - ry * scale_y)
            return px, py

        img  = Image.new("RGB", (pixel_size, pixel_size), color=(240, 240, 240))
        draw = ImageDraw.Draw(img)

        self._draw_grid(draw, robot_x, robot_y, view_size_x, view_size_y, world_to_pixel)

        # Trace
        if trace and len(trace) > 1:
            pts = [world_to_pixel(tp.x, tp.y) for tp in trace]
            draw.line(pts, fill=(180, 100, 100), width=2)
            for pt in pts:
                r = 3
                draw.ellipse([pt[0]-r, pt[1]-r, pt[0]+r, pt[1]+r], fill=(160, 80, 80))

        # Objects
        visible = self.get_all(area=area)
        for obj in visible:
            px, py = world_to_pixel(obj.position.x, obj.position.y or 0.0)
            yaw = obj.rotation.z if (obj.rotation and obj.rotation.z is not None) else 0.0
            rot = yaw - robot_yaw
            if obj.size and obj.size.x is not None:
                sx = int(obj.size.x * scale_x)
                sy = int((obj.size.y if obj.size.y is not None else obj.size.x) * scale_y)
                self._draw_rotated_rect(draw, px, py, sx, sy, rot,
                                        outline=(60, 120, 200), fill=(180, 210, 255))
            else:
                r = 6
                draw.ellipse([px-r, py-r, px+r, py+r],
                             fill=(60, 120, 200), outline=(20, 60, 140))
            draw.text((px + 8, py - 10), obj.id, fill=(20, 20, 120))

        # View cone (camera field of view, ~60 deg half-angle, ~2 m range)
        rpx, rpy = world_to_pixel(robot_x, robot_y)
        self._draw_view_cone(img, rpx, rpy, pixel_size, scale_x)

        # Robot (drawn on top of cone)
        draw = ImageDraw.Draw(img)  # refresh draw handle after paste
        self._draw_robot(draw, rpx, rpy, pixel_size)

        return img

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _draw_grid(draw, cx, cy, view_size_x, view_size_y, world_to_pixel):
        step    = 1.0
        x_start = math.floor(cx - view_size_x)
        x_end   = math.ceil (cx + view_size_x)
        y_start = math.floor(cy - view_size_y)
        y_end   = math.ceil (cy + view_size_y)
        color   = (200, 200, 200)
        for xi in range(x_start, x_end + 1):
            draw.line([world_to_pixel(xi, y_start), world_to_pixel(xi, y_end)],
                      fill=color, width=1)
        for yi in range(y_start, y_end + 1):
            draw.line([world_to_pixel(x_start, yi), world_to_pixel(x_end, yi)],
                      fill=color, width=1)

    @staticmethod
    def _draw_rotated_rect(draw, cx, cy, w, h, angle_rad, outline, fill):
        corners = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
        cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
        rotated = [
            (cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a)
            for dx, dy in corners
        ]
        draw.polygon(rotated, fill=fill, outline=outline)

    @staticmethod
    def _draw_view_cone(img: "Image.Image", rx: int, ry: int, pixel_size: int, scale_x: float):
        """Draw a semi-transparent light-blue view cone in front of the robot.

        The robot always points upward in the robot-centric map, so the cone
        fans out upward from the robot position.
        Half-angle ~55 degrees, range ~2.5 m world units.
        """
        cone_range_px = int(2.5 * scale_x)
        half_deg = 55
        steps = 20
        points = [(rx, ry)]
        for i in range(steps + 1):
            angle_rad = math.radians(-half_deg + (2 * half_deg * i / steps))
            px = rx + cone_range_px * math.sin(angle_rad)
            py = ry - cone_range_px * math.cos(angle_rad)
            points.append((px, py))

        cone_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        cone_draw  = ImageDraw.Draw(cone_layer)
        cone_draw.polygon(points, fill=(100, 200, 255, 55), outline=(60, 160, 220, 140))
        merged = Image.alpha_composite(img.convert("RGBA"), cone_layer)
        img.paste(merged.convert("RGB"))

    @staticmethod
    def _draw_robot(draw, rx, ry, pixel_size):
        s = max(10, pixel_size // 40)
        draw.polygon(
            [(rx, ry - s), (rx - s, ry + s), (rx + s, ry + s)],
            fill=(220, 60, 60), outline=(120, 20, 20),
        )

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
        self._objects = {e["id"]: ObjectCoordinate.from_dict(e) for e in data}

    def __len__(self) -> int:
        return len(self._objects)

    def __repr__(self) -> str:
        return f"CoordinateManager({len(self._objects)} objects, file='{self._file_path}')"
