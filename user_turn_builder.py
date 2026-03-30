"""
UserTurnBuilder
===============
Assembles the user turn for each VLM call from:
  - MapService  (robot pose, objects, coordinates, relations, combined image)
  - HintManager (permanent / session / one-time hints)

Typical call:
    builder  = UserTurnBuilder(map_service, hint_manager)
    turn     = builder.build(camera_image=pil_image)
    response = gemini.generate_content(turn)
"""

import json
import base64
from io import BytesIO
from typing import Optional

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from map_service  import MapService
from hint_manager import HintManager


class UserTurnBuilder:
    """
    Builds the user-turn payload for each VLM request.

    The resulting turn contains:
      - A combined image (camera on top, map on bottom) as base64 PNG.
      - A JSON block with robot state, objects, coordinates, relations and hints.
    """

    def __init__(
        self,
        map_service:  MapService,
        hint_manager: HintManager,
    ) -> None:
        self._map     = map_service
        self._hints   = hint_manager

    # ------------------------------------------------------------------
    # Primary method
    # ------------------------------------------------------------------

    def build(
        self,
        camera_image:    Optional["Image.Image"] = None,
        area:            Optional[str]  = None,
        map_view_size_x: float = 5.0,
        map_view_size_y: float = 5.0,
        map_pixel_size:  int   = 512,
        trace_last_n:    Optional[int]  = 50,
        combined_width:  int   = 768,
        history:         Optional[list] = None,
    ) -> list[dict]:
        """
        Build and return the user-turn as a list of Gemini content parts.

        The list contains:
          1. An image part  (combined camera + map image, base64 PNG).
          2. A text part    (state JSON including hints and action history).

        Args:
            camera_image:    Current camera frame (PIL Image or None).
            area:            Restrict state to one area (None = all).
            map_view_size_x: Map viewport width in metres.
            map_view_size_y: Map viewport height in metres.
            map_pixel_size:  Map tile size in pixels.
            trace_last_n:    Number of trace steps to render (None = all).
            combined_width:  Width of the combined output image in pixels.
            history:         List of recent action dicts {"step", "action", "reason"}.
                             Oldest first. Injected as "history" into the state JSON.

        Returns:
            A list of content parts compatible with the Gemini API:
            [
                {"inline_data": {"mime_type": "image/png", "data": "<base64>"}},
                {"text": "<state JSON string>"}
            ]
        """
        # Get state from MapService
        state = self._map.get_state(
            camera_image   =camera_image,
            area           =area,
            map_view_size_x=map_view_size_x,
            map_view_size_y=map_view_size_y,
            map_pixel_size =map_pixel_size,
            trace_last_n   =trace_last_n,
            combined_width =combined_width,
        )

        # Build state dict for VLM (without the PIL image)
        state_dict = {
            "robot":       state["robot"],
            "objects":     state["objects"],
            "coordinates": state["coordinates"],
            "relations":   state["relations"],
            "hints":       self._hints.as_dict(),
            "history":     history or [],
        }

        parts: list[dict] = []

        # Image part
        combined_image = state.get("combined_image")
        if combined_image is not None and PIL_AVAILABLE:
            parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": self._image_to_base64(combined_image),
                }
            })
        elif not PIL_AVAILABLE:
            parts.append({
                "text": "[Image unavailable — Pillow not installed]"
            })
        else:
            parts.append({
                "text": "[No camera image provided — map only]"
            })

        # Text / JSON part
        parts.append({
            "text": json.dumps(state_dict, indent=2, ensure_ascii=False)
        })

        return parts

    # ------------------------------------------------------------------
    # Debug helper
    # ------------------------------------------------------------------

    def build_debug_text(
        self,
        camera_image: Optional["Image.Image"] = None,
        area:         Optional[str] = None,
    ) -> str:
        """
        Return the text part of the user turn as a readable string.
        Useful for logging and unit tests.
        """
        state = self._map.get_state(camera_image=camera_image, area=area)
        state_dict = {
            "robot":       state["robot"],
            "objects":     state["objects"],
            "coordinates": state["coordinates"],
            "relations":   state["relations"],
            "hints":       self._hints.as_dict(),
        }
        return json.dumps(state_dict, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _image_to_base64(image: "Image.Image") -> str:
        buf = BytesIO()
        image.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")


# ----------------------------------------------------------------------
# Quick demo (no actual VLM call)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from map_service  import MapService
    from hint_manager import HintManager
    from object_manager     import MapObject
    from coordinate_manager import ObjectCoordinate, Vec3
    from relation_manager   import Relation

    # Setup
    svc   = MapService(data_dir=".")
    hints = HintManager("hints.json")

    svc.objects.add(MapObject("T1", "large living room table", area="living room"))
    svc.coordinates.add(
        ObjectCoordinate("T1", Vec3(1.5, 2.0), size=Vec3(1.2, 0.8), area="living room")
    )
    svc.relations.add(Relation("T1", "stands in front of", "W1", area="living room"))
    svc.positions.move_to(0.3, 0.1, 0.15, action="forward")

    hints.add_permanent("Avoid carpets — robot slips")
    hints.add_session("Explore the living room")
    hints.add_one_time("Table T1 was just moved 20 cm to the right")

    builder = UserTurnBuilder(svc, hints)

    # Print debug text
    print("=== User turn text part ===")
    print(builder.build_debug_text())

    # Build full turn (no camera image in demo)
    turn = builder.build(camera_image=None, map_pixel_size=400)
    print(f"\n=== Turn parts: {len(turn)} ===")
    for i, part in enumerate(turn):
        if "inline_data" in part:
            b64_len = len(part["inline_data"]["data"])
            print(f"  Part {i}: image ({b64_len} base64 chars)")
        else:
            print(f"  Part {i}: text ({len(part['text'])} chars)")
