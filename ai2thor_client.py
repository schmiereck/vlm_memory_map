"""
ai2thor_client.py
=================
AI2-THOR virtual environment integration.

Camera input and robot movement share a single AI2-THOR Controller via
AI2ThorBridge.  The two thin wrapper classes implement the existing
CameraClient / RobotClient interfaces so no other file needs to know
about AI2-THOR.

Install:
    pip install ai2thor

Usage:
    python main.py --gui --thor
    python main.py --gui --thor --scene FloorPlan10

Coordinate mapping (AI2-THOR → our world frame):
    our_x = thor_pos.x − start_pos.x   (East)
    our_y = thor_pos.z − start_pos.z   (North)
    our_yaw = −radians(thor_rotation_y) (CW degrees → CCW radians)
"""

import math
from typing import Optional

try:
    from ai2thor.controller import Controller
    AI2THOR_AVAILABLE = True
    AI2THOR_IMPORT_ERROR: Optional[str] = None
except Exception as _ai2thor_exc:
    AI2THOR_AVAILABLE = False
    AI2THOR_IMPORT_ERROR = str(_ai2thor_exc)

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from camera_client import CameraClient
from robot_client  import RobotClient


# ----------------------------------------------------------------------
# Shared controller bridge
# ----------------------------------------------------------------------

class AI2ThorBridge:
    """
    Owns the AI2-THOR Controller (Unity subprocess).
    Shared between AI2ThorCameraClient and AI2ThorRobotClient.

    open() must be called once before capture() or step().
    close() stops the Unity process.
    """

    DEFAULT_MOVE_M  = 0.25   # metres — used when VLM omits distance_m
    DEFAULT_ROT_DEG = 45.0   # degrees — used when VLM omits angle_deg

    def __init__(
        self,
        scene:                 str            = "FloorPlan201",
        image_size:            int            = 640,
        local_executable_path: Optional[str]  = None,
        start_back_m:          float          = 0.0,
        start_rotate_left_deg: float          = 0.0,
    ):
        self._scene                  = scene
        self._image_size             = image_size
        self._local_executable_path  = local_executable_path
        self._start_back_m           = start_back_m
        self._start_rotate_left_deg  = start_rotate_left_deg
        self._ctrl:       Optional["Controller"] = None
        self._start_pos:  Optional[dict]         = None
        self._start_rot_y: float                 = 0.0

    def open(self) -> bool:
        if not AI2THOR_AVAILABLE:
            print(f"[AI2-THOR] ERROR: ai2thor could not be imported: {AI2THOR_IMPORT_ERROR}")
            print( "           Installed? Run: python -c \"from ai2thor.controller import Controller\"")
            return False
        if not PIL_AVAILABLE:
            print("[AI2-THOR] ERROR: Pillow not installed — run: pip install Pillow")
            return False
        try:
            print(f"[AI2-THOR] Starting Unity controller (scene={self._scene}) …")
            kwargs: dict = dict(
                scene=self._scene,
                width=self._image_size,
                height=self._image_size,
                fieldOfView=60,
                snapToGrid=False,       # kein Gitter-Snapping
                gridSize=0.05,
                cameraY=0.25,           # camera height in world coords (v4.x+)
                agentCameraY=0.25,      # same parameter, older API name (v2/v3)
                renderDepthImage=False,
                renderInstanceSegmentation=False,
            )
            if self._local_executable_path:
                kwargs["local_executable_path"] = self._local_executable_path
                print(f"[AI2-THOR] Using local binary: {self._local_executable_path}")
            self._ctrl = Controller(**kwargs)
            # Explicit Initialize step — some versions ignore cameraY in __init__
            self._ctrl.step(
                "Initialize",
                gridSize=0.05,
                fieldOfView=60,
                snapToGrid=False,
                cameraY=0.25,
                renderDepthImage=False,
                renderInstanceSegmentation=False,
            )
            agent = self._ctrl.last_event.metadata["agent"]
            pos   = agent["position"]
            rot_y = agent["rotation"]["y"]

            # Apply start offset: move back and/or rotate left
            if self._start_back_m != 0.0 or self._start_rotate_left_deg != 0.0:
                rot_rad = math.radians(rot_y)
                new_x   = pos["x"] - self._start_back_m * math.sin(rot_rad)
                new_z   = pos["z"] - self._start_back_m * math.cos(rot_rad)
                new_rot = rot_y - self._start_rotate_left_deg  # CW → left = subtract
                event   = self._ctrl.step(
                    "TeleportFull",
                    x=new_x, y=pos["y"], z=new_z,
                    rotation={"x": 0, "y": new_rot, "z": 0},
                    horizon=0,
                    standing=True,
                )
                if not event.metadata.get("lastActionSuccess", False):
                    print("[AI2-THOR] WARNING: Start teleport blocked — using default spawn.")
                agent = self._ctrl.last_event.metadata["agent"]

            self._start_pos   = dict(agent["position"])
            self._start_rot_y = agent["rotation"]["y"]
            cam_y = self._ctrl.last_event.metadata.get("cameraPosition", {}).get("y", "?")
            print(f"[AI2-THOR] Ready. Start pos: "
                  f"x={self._start_pos['x']:.2f}  z={self._start_pos['z']:.2f}  "
                  f"rot_y={self._start_rot_y:.1f}°  camera_y={cam_y}")
            return True
        except Exception as exc:
            msg = str(exc)
            if "no build exists" in msg:
                print(
                    "[AI2-THOR] ERROR: No pre-built binary for this ai2thor version on Windows.\n"
                    "\n"
                    "  Option A — try an older version:\n"
                    "    pip install \"ai2thor==3.3.4\"\n"
                    "\n"
                    "  Option B — use a local binary:\n"
                    "    1. Download thor-windows-local.zip from\n"
                    "       https://github.com/allenai/ai2thor/releases\n"
                    "    2. Unzip to e.g. C:\\ai2thor\\\n"
                    "    3. Run:  python main.py --thor --thor-path C:\\ai2thor\\thor-windows-local.exe\n"
                )
            else:
                print(f"[AI2-THOR] ERROR starting controller: {exc}")
            return False

    def close(self) -> None:
        if self._ctrl is not None:
            try:
                self._ctrl.stop()
            except Exception:
                pass
            self._ctrl = None

    # ------------------------------------------------------------------
    # Frame access
    # ------------------------------------------------------------------

    def get_frame(self) -> Optional["Image.Image"]:
        if self._ctrl is None:
            return None
        return Image.fromarray(self._ctrl.last_event.frame)

    # ------------------------------------------------------------------
    # Action execution
    # ------------------------------------------------------------------

    def step(self, action: str, **kwargs) -> bool:
        """Execute one AI2-THOR action. Returns True if not blocked."""
        if self._ctrl is None:
            return False
        event = self._ctrl.step(action, **kwargs)
        return bool(event.metadata.get("lastActionSuccess", False))

    # ------------------------------------------------------------------
    # Pose (ground truth from simulator)
    # ------------------------------------------------------------------

    def get_pose(self) -> tuple[float, float, float]:
        """
        Return current agent pose in our world coordinate frame:
            x   — East offset from start position (metres)
            y   — North offset from start position (metres)
            yaw — counter-clockwise from initial heading (radians)

        Our coordinate system defines:
            origin  = teleported start position
            North   = initial facing direction of the agent
            yaw = 0 = facing North, positive = CCW (left)

        AI2-THOR uses clockwise degrees and absolute world coordinates,
        so we rotate the displacement vector by the initial heading and
        compute yaw relative to start_rot_y.

        Forward direction in AI2-THOR at angle θ: (sin θ, cos θ) in (x, z).
        Rotation to our frame:
            our_x = dx·cos θ − dz·sin θ   (East)
            our_y = dx·sin θ + dz·cos θ   (North / forward)
            yaw   = −radians(rot_y − start_rot_y)
        """
        if self._ctrl is None or self._start_pos is None:
            return (0.0, 0.0, 0.0)
        agent    = self._ctrl.last_event.metadata["agent"]
        pos      = agent["position"]
        rot_y    = agent["rotation"]["y"]

        dx       = pos["x"] - self._start_pos["x"]
        dz       = pos["z"] - self._start_pos["z"]
        init_rad = math.radians(self._start_rot_y)

        our_x = dx * math.cos(init_rad) - dz * math.sin(init_rad)
        our_y = dx * math.sin(init_rad) + dz * math.cos(init_rad)
        yaw   = -math.radians(rot_y - self._start_rot_y)

        return (our_x, our_y, yaw)


# ----------------------------------------------------------------------
# CameraClient wrapper
# ----------------------------------------------------------------------

class AI2ThorCameraClient(CameraClient):
    """Delivers RGB camera frames from the AI2-THOR simulation."""

    def __init__(self, bridge: AI2ThorBridge):
        self._bridge = bridge

    def open(self) -> bool:
        return self._bridge.open()

    def capture(self) -> Optional["Image.Image"]:
        return self._bridge.get_frame()

    def close(self) -> None:
        self._bridge.close()


# ----------------------------------------------------------------------
# RobotClient wrapper
# ----------------------------------------------------------------------

_ACTION_MAP: dict[str, Optional[str]] = {
    "forward":    "MoveAhead",
    "backward":   "MoveBack",
    "turn_left":  "RotateLeft",
    "turn_right": "RotateRight",
    "stop":       None,
}


class AI2ThorRobotClient(RobotClient):
    """
    Executes VLM movement commands inside the AI2-THOR simulation.

    Movement:  one MoveAhead/MoveBack step with moveMagnitude = distance_m.
    Rotation:  one RotateLeft/RotateRight step with degrees = angle_deg.
    Pose:      ground-truth from simulator — no dead reckoning needed.
    """

    def __init__(self, bridge: AI2ThorBridge):
        self._bridge = bridge

    def execute(self, action: dict) -> str:
        action_type = action.get("type", "stop")
        distance_m  = action.get("distance_m", self._bridge.DEFAULT_MOVE_M)
        angle_deg   = action.get("angle_deg",  self._bridge.DEFAULT_ROT_DEG)
        reason      = action.get("reason", "")

        thor_action = _ACTION_MAP.get(action_type)
        success     = True

        if thor_action is not None:
            if action_type in ("forward", "backward"):
                success = self._bridge.step(thor_action,
                                            moveMagnitude=float(distance_m))
            else:  # turn_left / turn_right
                success = self._bridge.step(thor_action,
                                            degrees=float(angle_deg))

        status = "OK" if success else "BLOCKED (collision?)"
        if action_type in ("forward", "backward"):
            detail = f"{distance_m * 100:.0f} cm"
        elif action_type in ("turn_left", "turn_right"):
            detail = f"{angle_deg:.0f}°"
        else:
            detail = ""
        msg = f"[AI2-THOR] {action_type.upper()}{' ' + detail if detail else ''} — {status}"
        if reason:
            msg += f"\n           Reason: {reason}"
        print(msg)
        return msg

    def get_pose(self) -> tuple[float, float, float]:
        """Ground-truth pose from the simulator (x, y, yaw)."""
        return self._bridge.get_pose()

    def shutdown(self) -> None:
        pass  # bridge.close() is called via AI2ThorCameraClient.close()
