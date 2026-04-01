"""
main.py
=======
Main application loop for the hexapod spatial memory system.

Wires together:
    MapService        — spatial memory
    HintManager       — operator hints
    UserTurnBuilder   — assembles VLM input
    VlmClient         — Groq API call
    RobotClient       — movement output (Console or ROS2)
    CameraClient      — image capture (Laptop or PiCamera)
    GUI               — map display + controls (optional)

Usage (terminal, no GUI):
    python main.py

Usage (with GUI):
    python main.py --gui

Usage (static test image, no camera required):
    python main.py --image test.jpg
"""

import argparse
import base64
import datetime
import json
import math
import sys
import threading
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from map_service        import MapService
from hint_manager       import HintManager
from user_turn_builder  import UserTurnBuilder
from vlm_client         import VlmClient
from robot_client       import RobotClient, ConsoleRobotClient
from camera_client      import CameraClient, LaptopCameraClient, StaticImageClient


DATA_DIR = "data"


class HexapodApp:
    """
    Orchestrates all components. GUI-agnostic — the GUI calls
    trigger_step() and add_hint() and reads state via callbacks.
    """

    def __init__(
        self,
        robot:  RobotClient,
        camera: CameraClient,
        data_dir: str = DATA_DIR,
        on_log:    callable = print,
        on_update: callable = None,   # called after each step with new map image
    ):
        self._robot   = robot
        self._camera  = camera
        self._on_log  = on_log
        self._on_update = on_update or (lambda before, after, summary: None)
        self._lock    = threading.Lock()
        self._running = False

        # Core components
        base = Path(data_dir)
        base.mkdir(exist_ok=True)
        self._data_dir = base

        self._map     = MapService(data_dir=str(base))
        self._hints   = HintManager(str(base / "hints.json"))
        self._builder = UserTurnBuilder(self._map, self._hints)
        self._vlm     = VlmClient()
        self._history: list[dict] = []   # rolling list of last actions
        self._history_max = 5            # how many steps to keep

        self._map.load_all()
        self._hints.load()

    # ------------------------------------------------------------------
    # Public interface (called by GUI or CLI)
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Open camera. Returns True on success."""
        ok = self._camera.open()
        if ok:
            self._running = True
            # Sync starting pose from simulator so yaw=0 = initial heading
            pose_tuple = self._robot.get_pose()
            if pose_tuple is not None:
                x, y, yaw = pose_tuple
                self._map.positions.move_to(x, y, yaw, action="stop")
                self._map.positions.save()
            self._log("System ready. Press 'Next Step' to start.")
        else:
            self._log("ERROR: Could not open camera.")
        return ok

    def get_initial_image(self) -> Optional["Image.Image"]:
        """
        Return an initial display image on startup.
        - If a static test image is configured, return combined (camera + map).
        - Otherwise return only the map (camera area blank).
        """
        camera_image = None
        if isinstance(self._camera, StaticImageClient):
            camera_image = self._camera.capture()

        state = self._map.get_state(
            camera_image   =camera_image,
            map_pixel_size =512,
            combined_width =768,
        )
        return state.get("combined_image")

    def trigger_step(self) -> None:
        """
        Capture a frame, call the VLM, execute the action, update memory.
        Safe to call from the GUI thread — runs in a background thread.
        """
        if not self._running:
            self._log("System not started.")
            return
        threading.Thread(target=self._step, daemon=True).start()

    def add_hint(self, text: str, category: str) -> None:
        """Add an operator hint. category: permanent / session / one_time."""
        with self._lock:
            self._hints.add(text, category)
            self._hints.save()
        self._log(f"[Hint/{category}] {text}")

    def remove_hint(self, text: str, category: Optional[str] = None) -> None:
        """Remove a hint by text."""
        with self._lock:
            deleted = self._hints.delete(text, category)
            self._hints.save()
        self._log(f"Removed {deleted} hint(s): {text}")

    def rotate_pose(self, delta_deg: float) -> None:
        """
        Manually rotate the robot's stored yaw by delta_deg degrees.
        Positive = CCW (left), negative = CW (right).
        Updates the map display immediately — useful for correcting
        drift between the camera image and the rendered map.
        """
        with self._lock:
            pose = self._map.positions.pose
            new_yaw = pose.yaw + math.radians(delta_deg)
            self._map.positions.move_to(pose.x, pose.y, new_yaw, action="correction")
            self._map.positions.save()
            state = self._map.get_state(map_pixel_size=512, combined_width=768)
        self._log(f"Pose rotated {delta_deg:+.0f}° → yaw={math.degrees(new_yaw):.1f}°")
        self._on_update(None, state.get("combined_image"), {})

    def get_hints(self) -> dict:
        return self._hints.as_dict()

    def shutdown(self) -> None:
        self._running = False
        self._camera.close()
        self._robot.shutdown()
        with self._lock:
            self._map.save_all()
            self._hints.save()
        self._log("Shutdown complete.")

    # ------------------------------------------------------------------
    # Internal step
    # ------------------------------------------------------------------

    def _step(self) -> None:
        with self._lock:
            self._log("── Capturing frame …")
            frame = self._camera.capture()
            if frame is None:
                self._log("ERROR: Frame capture failed — skipping step.")
                return

            # Snapshot of map+camera BEFORE VLM response is applied
            state_before = self._map.get_state(
                camera_image   =frame,
                map_pixel_size =512,
                combined_width =768,
            )
            before_image = state_before.get("combined_image")

            self._log("── Building user turn …")
            turn = self._builder.build(
                camera_image   =frame,
                map_pixel_size =512,
                trace_last_n   =50,
                combined_width =768,
                history        =list(self._history),
            )

            self._log(f"── Calling VLM ({VlmClient.MODEL}) …")
            response, raw = self._vlm.call(turn)

            if not response:
                self._log(f"ERROR: VLM call failed.\n{raw}")
                return

            # Persist request + response to data/logs/<timestamp>/
            self._save_request_log(turn, raw, response)

            # Append action to rolling history
            action_entry = response.get("action", {})
            self._history.append({
                "step":   len(self._history) + 1,
                "action": action_entry.get("type", "unknown"),
                "distance_m": action_entry.get("distance_m", 0.0),
                "angle_deg":  action_entry.get("angle_deg", 0.0),
                "reason": action_entry.get("reason", ""),
            })
            if len(self._history) > self._history_max:
                self._history.pop(0)

            # Log raw response for debugging
            self._log(f"── VLM raw response:\n{raw[:600]}")

            # Execute movement
            action  = response.get("action", {"type": "stop", "reason": "No action"})
            confirm = self._robot.execute(action)
            self._log(confirm)

            # Strip VLM's unreliable robot_pose
            response.pop("robot_pose", None)

            # Update memory BEFORE dead reckoning — the VLM's robot-relative
            # coordinates describe objects as seen from the current (pre-move) pose.
            summary = self._map.process_vlm_response(response)
            self._log(
                f"── Memory update: "
                f"+{summary['objects_added']} objects, "
                f"+{summary['coordinates_added']} coords, "
                f"+{summary['relations_added']} relations, "
                f"{summary['corrections_applied']} corrections"
            )
            if summary["warnings"]:
                for w in summary["warnings"]:
                    self._log(f"   WARNING: {w}")

            # Now apply dead reckoning to advance the robot pose
            self._update_position_from_action(action)

            self._map.save_all()

            # Capture a fresh frame AFTER movement for the "current" panel
            after_frame = self._camera.capture() or frame

            # Notify GUI with before + after images
            state_after = self._map.get_state(
                camera_image   =after_frame,
                map_pixel_size =512,
                combined_width =768,
            )
            self._on_update(before_image, state_after.get("combined_image"), summary)


    def _update_position_from_action(self, action: dict) -> None:
        """
        Update robot pose after executing an action.

        Prefers ground-truth pose from the robot client (e.g. AI2-THOR simulator).
        Falls back to dead reckoning when no ground-truth is available.
        """
        import math
        action_type = action.get("type", "stop")

        # --- Ground-truth pose (simulator) --------------------------------
        pose_tuple = self._robot.get_pose()
        if pose_tuple is not None:
            x, y, yaw = pose_tuple
            self._map.positions.move_to(x, y, yaw, action=action_type)
            self._log(
                f"Pose (ground truth): x={x:.2f} y={y:.2f} "
                f"yaw={math.degrees(yaw):.1f}deg"
            )
            return

        # --- Dead reckoning fallback --------------------------------------
        pose       = self._map.positions.pose
        distance_m = action.get("distance_m", 0.0)
        angle_rad  = math.radians(action.get("angle_deg", 0.0))
        x   = pose.x
        y   = pose.y
        yaw = pose.yaw

        if action_type == "forward":
            x -= distance_m * math.sin(yaw)
            y += distance_m * math.cos(yaw)
        elif action_type == "backward":
            x += distance_m * math.sin(yaw)
            y -= distance_m * math.cos(yaw)
        elif action_type == "turn_left":
            yaw += angle_rad
        elif action_type == "turn_right":
            yaw -= angle_rad
        # stop → no change

        self._map.positions.move_to(x, y, yaw, action=action_type)
        self._log(
            f"Pose (dead reckoning): x={x:.2f} y={y:.2f} "
            f"yaw={math.degrees(yaw):.1f}deg"
        )

    def _save_request_log(self, turn: list[dict], raw_response: str, parsed_response: dict) -> None:
        """
        Persist one VLM request/response cycle to data/logs/<timestamp>/.

        Files written:
          combined.png   — the combined camera + map image sent to the VLM
          request.json   — the text/state JSON part of the user turn
          response_raw.txt — the raw text returned by the VLM
          response.json  — the parsed response dict
        """
        ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_dir = self._data_dir / "logs" / ts
        log_dir.mkdir(parents=True, exist_ok=True)

        # Save combined image
        for part in turn:
            if "inline_data" in part:
                img_bytes = base64.b64decode(part["inline_data"]["data"])
                (log_dir / "combined.png").write_bytes(img_bytes)
                break

        # Save request JSON text
        for part in turn:
            if "text" in part:
                try:
                    request_obj = json.loads(part["text"])
                    (log_dir / "request.json").write_text(
                        json.dumps(request_obj, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                except json.JSONDecodeError:
                    (log_dir / "request.json").write_text(part["text"], encoding="utf-8")
                break

        # Save raw response
        (log_dir / "response_raw.txt").write_text(raw_response, encoding="utf-8")

        # Save parsed response
        (log_dir / "response.json").write_text(
            json.dumps(parsed_response, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        self._log(f"── Request log saved: {log_dir}")

    def _log(self, message: str) -> None:
        self._on_log(message)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Hexapod Spatial Memory System")
    parser.add_argument("--gui",   action="store_true", help="Launch with GUI")
    parser.add_argument("--image", type=str, default=None,
                        help="Use static image instead of webcam (for testing)")
    parser.add_argument("--thor",  action="store_true",
                        help="Use AI2-THOR virtual environment instead of webcam")
    parser.add_argument("--scene", type=str, default="FloorPlan1",
                        help="AI2-THOR scene name (default: FloorPlan1)")
    parser.add_argument("--thor-path", type=str, default=None,
                        dest="thor_path",
                        help="Path to local AI2-THOR executable (workaround for Windows build issues)")
    parser.add_argument("--thor-back", type=float, default=0.0,
                        dest="thor_back",
                        help="Move start position back by N metres (default: 0)")
    parser.add_argument("--thor-rotate", type=float, default=0.0,
                        dest="thor_rotate",
                        help="Rotate start position left by N degrees (default: 0)")
    parser.add_argument("--data",  type=str, default=DATA_DIR,
                        help=f"Data directory (default: {DATA_DIR})")
    args = parser.parse_args()

    # Select camera + robot backend
    if args.thor:
        from ai2thor_client import AI2ThorBridge, AI2ThorCameraClient, AI2ThorRobotClient
        bridge = AI2ThorBridge(
            scene=args.scene,
            local_executable_path=args.thor_path,
            start_back_m=args.thor_back,
            start_rotate_left_deg=args.thor_rotate,
        )
        camera = AI2ThorCameraClient(bridge)
        robot  = AI2ThorRobotClient(bridge)
    elif args.image:
        camera = StaticImageClient(args.image)
        robot  = ConsoleRobotClient()
    else:
        camera = LaptopCameraClient(device_index=0)
        robot  = ConsoleRobotClient()

    app = HexapodApp(robot=robot, camera=camera, data_dir=args.data)

    if args.gui:
        # Import here so GUI is optional
        try:
            from gui import HexapodGui
        except ImportError as e:
            print(f"ERROR: Could not import GUI: {e}")
            sys.exit(1)
        HexapodGui(app).run()
    else:
        # Minimal CLI mode: manual trigger via Enter key
        print("=== Hexapod Spatial Memory — CLI mode ===")
        print("Commands:  [Enter] = next step   h <text> = add one-time hint   q = quit")

        if not app.start():
            sys.exit(1)

        try:
            while True:
                cmd = input("\n> ").strip()
                if cmd.lower() in ("q", "quit", "exit"):
                    break
                elif cmd.lower().startswith("h "):
                    app.add_hint(cmd[2:].strip(), "one_time")
                elif cmd == "":
                    app.trigger_step()
                    # Wait for the background thread to finish
                    import time; time.sleep(0.5)
                else:
                    print("Unknown command. Enter = step, h <text> = hint, q = quit")
        except KeyboardInterrupt:
            pass
        finally:
            app.shutdown()


if __name__ == "__main__":
    main()
