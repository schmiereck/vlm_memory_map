"""
MapService
==========
Primary interface between the robot's spatial memory and the VLM.

VLM Response JSON schema
------------------------
{
  "robot_pose": {                          // optional
    "x": 0.3, "y": 0.1, "yaw": 0.15,
    "action": "forward"
  },
  "add_objects": [                         // optional
    {"id": "T1", "description": "großer Wohnzimmertisch", "area": "Wohnzimmer"}
  ],
  "add_coordinates": [                     // optional
    {
      "id": "T1",
      "position": {"x": 1.5, "y": 2.0},
      "size":     {"x": 1.2, "y": 0.8},   // y, z optional
      "rotation": {"x": null, "y": null, "z": 0.3},
      "area": "Wohnzimmer"
    }
  ],
  "add_relations": [                       // optional
    {"object_a": "T1", "relation": "steht an", "object_b": "W1", "area": "Wohnzimmer"}
  ],
  "corrections": [                         // optional
    {"type": "move_object",  "id": "T1", "position": {"x": 1.8, "y": 2.0}},
    {"type": "rotate_map",   "delta_yaw": 0.1},
    {"type": "set_robot_pose", "x": 0.0, "y": 0.0, "yaw": 0.0}
  ]
}

State JSON returned to VLM
---------------------------
{
  "robot": {"x": 0.3, "y": 0.1, "yaw": 0.15},
  "objects":   [{"id": "T1", "description": "...", "area": "Wohnzimmer"}, ...],
  "coordinates": [{"id": "T1", "position": {...}, "size": {...}, ...}, ...],
  "relations": [{"object_a": "T1", "relation": "steht an", "object_b": "W1"}, ...]
}
"""

import json
import math
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from object_manager     import ObjectManager,     MapObject, OBJECT_COLORS
from relation_manager   import RelationManager,   Relation
from coordinate_manager import CoordinateManager, ObjectCoordinate, Vec3, TracePoint
from position_manager   import PositionManager


class MapService:
    """
    Facade that owns all four managers and exposes two primary methods:

        process_vlm_response(json_dict)  — apply VLM updates to memory
        get_state(camera_image)          — return state dict + combined image
    """

    def __init__(self, data_dir: str = "."):
        base = Path(data_dir)
        self.objects     = ObjectManager    (str(base / "objects.json"))
        self.relations   = RelationManager  (str(base / "relations.json"))
        self.coordinates = CoordinateManager(str(base / "coordinates.json"))
        self.positions   = PositionManager  (str(base / "position.json"))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_all(self) -> None:
        self.objects.load()
        self.relations.load()
        self.coordinates.load()
        self.positions.load()

    def save_all(self) -> None:
        self.objects.save()
        self.relations.save()
        self.coordinates.save()
        self.positions.save()

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _robot_relative_to_world(self, pos: dict) -> dict:
        """
        Transform a robot-relative position {x, y} to world coordinates
        using the current robot pose.

        Robot-relative: x = right, y = forward.
        World: x = East, y = North, yaw = 0 means facing North.
        """
        rel_x = float(pos.get("x", 0.0))
        rel_y = float(pos.get("y", 0.0))
        pose  = self.positions.pose
        cos_yaw = math.cos(pose.yaw)
        sin_yaw = math.sin(pose.yaw)
        world_x = pose.x + rel_x * cos_yaw - rel_y * sin_yaw
        world_y = pose.y + rel_x * sin_yaw + rel_y * cos_yaw
        return {"x": round(world_x, 3), "y": round(world_y, 3)}

    # ------------------------------------------------------------------
    # Primary interface 1: process VLM response
    # ------------------------------------------------------------------

    def process_vlm_response(self, response: dict) -> dict:
        """
        Apply a VLM response dict to the spatial memory.

        Returns a summary dict with counts of applied changes and any
        warnings (e.g. unknown correction types).
        """
        summary = {
            "robot_pose_updated": False,
            "objects_added":      0,
            "coordinates_added":  0,
            "relations_added":    0,
            "corrections_applied": 0,
            "warnings":           [],
        }

        # 1. Robot pose
        pose_data = response.get("robot_pose")
        if pose_data:
            self.positions.move_to(
                x      =float(pose_data.get("x",   0.0)),
                y      =float(pose_data.get("y",   0.0)),
                yaw    =float(pose_data.get("yaw", 0.0)),
                action =pose_data.get("action"),
            )
            summary["robot_pose_updated"] = True

        # 2. New objects
        for entry in response.get("add_objects", []):
            self.objects.add(MapObject(
                id         =entry["id"],
                description=entry.get("description", ""),
                area       =entry.get("area"),
            ))
            summary["objects_added"] += 1

        # 3. New coordinates (VLM gives robot-relative, transform position to world)
        for entry in response.get("add_coordinates", []):
            pos  = entry.get("position", {})
            size = entry.get("size")
            rot  = entry.get("rotation") or {}
            world_pos = self._robot_relative_to_world(pos)
            # Sizes are kept in robot-relative frame (x=right, y=forward).
            # The stored rotation encodes the world orientation of the object:
            #   - If the VLM provides an explicit relative rotation, add it to
            #     the robot's current yaw to get the world rotation.
            #   - If no explicit rotation, store None (treated as world-aligned,
            #     yaw=0). The renderer uses rot = stored_yaw - robot_yaw, so
            #     world-aligned objects (yaw=0) correctly appear as diamonds
            #     at -robot_yaw when the robot has turned.
            rel_rot_z = rot.get("z")
            rotation = Vec3(x=None, y=None,
                            z=round(self.positions.pose.yaw + rel_rot_z, 4)) \
                       if rel_rot_z is not None else None
            self.coordinates.add(ObjectCoordinate(
                id      =entry["id"],
                position=Vec3.from_dict(world_pos),
                size    =Vec3.from_dict(size) if size else None,
                rotation=rotation,
                area    =entry.get("area"),
            ))
            summary["coordinates_added"] += 1

        # 4. New relations
        for entry in response.get("add_relations", []):
            self.relations.add(Relation(
                object_a=entry["object_a"],
                relation=entry["relation"],
                object_b=entry["object_b"],
                area    =entry.get("area"),
            ))
            summary["relations_added"] += 1

        # 5. Corrections
        for correction in response.get("corrections", []):
            ctype = correction.get("type")

            if ctype == "move_object":
                obj_id    = correction.get("id")
                pos       = correction.get("position", {})
                size      = correction.get("size")
                rot       = correction.get("rotation") or {}
                world_pos = self._robot_relative_to_world(pos)
                rel_rot_z = rot.get("z")
                rotation  = Vec3(x=None, y=None,
                                 z=round(self.positions.pose.yaw + rel_rot_z, 4)) \
                            if rel_rot_z is not None else None
                ok = self.coordinates.update(
                    obj_id,
                    position=Vec3.from_dict(world_pos),
                    size    =Vec3.from_dict(size) if size else None,
                    rotation=rotation,
                )
                if ok:
                    summary["corrections_applied"] += 1
                else:
                    summary["warnings"].append(
                        f"move_object: unknown id '{obj_id}'"
                    )

            elif ctype == "rotate_map":
                delta = float(correction.get("delta_yaw", 0.0))
                self.coordinates.rotate_all(delta)
                summary["corrections_applied"] += 1

            elif ctype == "set_robot_pose":
                self.positions.set_pose(
                    x     =float(correction.get("x",   0.0)),
                    y     =float(correction.get("y",   0.0)),
                    yaw   =float(correction.get("yaw", 0.0)),
                    action="correction",
                    record=True,
                )
                summary["corrections_applied"] += 1

            else:
                summary["warnings"].append(f"Unknown correction type: '{ctype}'")

        return summary

    # ------------------------------------------------------------------
    # Primary interface 2: get current state
    # ------------------------------------------------------------------

    def get_state(
        self,
        camera_image:    Optional["Image.Image"] = None,
        area:            Optional[str]  = None,
        map_view_size_x: float = 5.0,
        map_view_size_y: float = 5.0,
        map_pixel_size:  int   = 512,
        trace_last_n:    Optional[int]  = 50,
        combined_width:  int   = 768,
    ) -> dict:
        """
        Return the current spatial state for VLM input.

        Args:
            camera_image:    Current camera frame (PIL Image). If provided
                             together with Pillow, a combined image is built.
            area:            Optionally restrict objects/relations to one area.
            map_view_size_x: Map viewport width in meters.
            map_view_size_y: Map viewport height in meters.
            map_pixel_size:  Map tile pixel size (square).
            trace_last_n:    How many trace steps to render (None = all).
            combined_width:  Width of the combined output image in pixels.

        Returns dict with keys:
            "robot"        — current pose
            "objects"      — list of MapObject dicts
            "coordinates"  — list of ObjectCoordinate dicts
            "relations"    — list of Relation dicts
            "combined_image" — PIL Image or None
        """
        pose = self.positions.pose

        # Map-orientation hint: how far world axes are rotated from screen-top.
        # The map is robot-centred (robot always faces screen-top).
        # Positive angles = clockwise from screen-top.
        yaw_deg = math.degrees(pose.yaw) % 360

        # State dicts
        state = {
            "robot": {
                "x": pose.x,
                "y": pose.y,
                "yaw": pose.yaw,
                "map_orientation": {
                    "note": (
                        "Map is robot-centred: robot always faces screen-top. "
                        "A coordinate cross in the top-right corner shows the "
                        "current world-axis directions."
                    ),
                    "world_y_plus_cw_from_screen_top_deg": round(yaw_deg, 1),
                    "world_x_plus_cw_from_screen_top_deg": round((yaw_deg + 90) % 360, 1),
                },
            },
            "objects":     [o.to_dict() for o in self.objects.get_all(area=area)],
            "coordinates": [c.to_dict() for c in self.coordinates.get_all(area=area)],
            "relations":   [r.to_dict() for r in self.relations.get_all(area=area)],
            "combined_image": None,
        }

        # Combined image
        if PIL_AVAILABLE:
            trace_entries = self.positions.get_trace_points(last_n=trace_last_n)
            trace_points  = [TracePoint(e.x, e.y, e.yaw) for e in trace_entries]

            object_colors = {
                obj.id: OBJECT_COLORS[obj.color]
                for obj in self.objects.get_all(area=area)
                if obj.color and obj.color in OBJECT_COLORS
            }
            map_img = self.coordinates.get_map_image(
                robot_x      =pose.x,
                robot_y      =pose.y,
                robot_yaw    =pose.yaw,
                view_size_x  =map_view_size_x,
                view_size_y  =map_view_size_y,
                pixel_size   =map_pixel_size,
                trace        =trace_points,
                area         =area,
                object_colors=object_colors,
            )

            combined = self._build_combined_image(
                camera_image  =camera_image,
                map_image     =map_img,
                output_width  =combined_width,
            )
            state["combined_image"] = combined

        return state

    # ------------------------------------------------------------------
    # Combined image builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_combined_image(
        camera_image:  Optional["Image.Image"],
        map_image:     "Image.Image",
        output_width:  int = 768,
    ) -> "Image.Image":
        """
        Stack camera (top) and map (bottom) into one image.
        Both tiles are scaled to output_width; total height = 2 * tile_height.
        If no camera image is provided, only the map is returned scaled.
        """
        from PIL import Image as PILImage

        def scale_to_width(img: "Image.Image", w: int) -> "Image.Image":
            ratio = w / img.width
            new_h = int(img.height * ratio)
            return img.resize((w, new_h), PILImage.LANCZOS)

        map_scaled = scale_to_width(map_image, output_width)

        if camera_image is None:
            return map_scaled

        cam_scaled  = scale_to_width(camera_image, output_width)
        total_h     = cam_scaled.height + map_scaled.height
        combined    = PILImage.new("RGB", (output_width, total_h), color=(20, 20, 20))
        combined.paste(cam_scaled, (0, 0))
        combined.paste(map_scaled, (0, cam_scaled.height))
        return combined

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"MapService("
            f"objects={len(self.objects)}, "
            f"coords={len(self.coordinates)}, "
            f"relations={len(self.relations)}, "
            f"trace={len(self.positions)})"
        )


# ----------------------------------------------------------------------
# Quick demo
# ----------------------------------------------------------------------
if __name__ == "__main__":
    svc = MapService(data_dir=".")
    svc.load_all()

    # Simulate a VLM response
    vlm_response = {
        "robot_pose": {"x": 0.3, "y": 0.1, "yaw": 0.15, "action": "forward"},
        "add_objects": [
            {"id": "T1", "description": "großer Wohnzimmertisch", "area": "Wohnzimmer"},
            {"id": "W1", "description": "Wand mit Eingangstür",   "area": "Wohnzimmer"},
        ],
        "add_coordinates": [
            {"id": "T1", "position": {"x": 1.5, "y": 2.0},
             "size": {"x": 1.2, "y": 0.8}, "area": "Wohnzimmer"},
            {"id": "W1", "position": {"x": 0.0, "y": 4.0},
             "size": {"x": 5.0, "y": 0.2}, "area": "Wohnzimmer"},
        ],
        "add_relations": [
            {"object_a": "T1", "relation": "steht vor", "object_b": "W1",
             "area": "Wohnzimmer"},
        ],
        "corrections": [],
    }

    summary = svc.process_vlm_response(vlm_response)
    print("VLM response applied:", summary)

    # Get state for next VLM call
    state = svc.get_state(
        camera_image   =None,
        map_view_size_x=6.0,
        map_view_size_y=6.0,
        map_pixel_size =400,
        trace_last_n   =50,
    )

    print(f"\nState — robot: {state['robot']}")
    print(f"Objects:     {len(state['objects'])}")
    print(f"Coordinates: {len(state['coordinates'])}")
    print(f"Relations:   {len(state['relations'])}")

    if state["combined_image"]:
        state["combined_image"].save("combined_preview.png")
        print("Combined image saved to combined_preview.png")

    svc.save_all()
    print(f"\nAll data saved. Service: {svc}")
