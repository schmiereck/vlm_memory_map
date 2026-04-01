"""
robot_client.py
===============
Abstract base class for robot interfaces.

To add a new robot backend, subclass RobotClient and implement execute().
The main loop only ever calls execute(action_dict) — swap the implementation
without touching any other file.

Current implementations:
    ConsoleRobotClient   — prints commands to stdout (laptop testing)

Planned:
    Ros2RobotClient      — publishes to ROS2 topics (real hexapod)
"""

from abc import ABC, abstractmethod


class RobotClient(ABC):
    """Abstract robot interface. All backends must implement execute()."""

    @abstractmethod
    def execute(self, action: dict) -> str:
        """
        Execute a movement command.

        Args:
            action: The "action" dict from the VLM response, e.g.:
                    {
                        "type":        "forward",
                        "distance_m":  0.3,
                        "angle_deg":   0.0,
                        "reason":      "Path is clear"
                    }

        Returns:
            A human-readable confirmation string for display in the GUI log.
        """

    def get_pose(self) -> "Optional[tuple[float, float, float]]":
        """
        Optional: return current (x, y, yaw) in world coordinates.
        x/y in metres from start, yaw in CCW radians from North.
        Returns None to signal that dead reckoning should be used instead.
        Simulator-backed clients (e.g. AI2ThorRobotClient) override this.
        """
        return None

    def set_pose(self, x: float, y: float, yaw: float) -> None:
        """
        Optional: teleport/move the robot to a given world pose on startup.
        Used to restore the last saved position after a restart.
        Default implementation is a no-op (e.g. for physical robots).
        """

    def shutdown(self) -> None:
        """Optional cleanup hook called when the application exits."""


# ----------------------------------------------------------------------
# Console implementation (laptop testing)
# ----------------------------------------------------------------------

class ConsoleRobotClient(RobotClient):
    """
    Prints movement commands as clear text.
    Used during laptop testing — you push the laptop by hand.
    """

    # Conversion helpers
    _DESCRIPTIONS = {
        "forward":    "Move FORWARD  {distance_m:.0f} cm",
        "backward":   "Move BACKWARD {distance_m:.0f} cm",
        "turn_left":  "Turn LEFT     {angle_deg:.0f}°",
        "turn_right":  "Turn RIGHT    {angle_deg:.0f}°",
        "stop":       "STOP",
    }

    def execute(self, action: dict) -> str:
        action_type  = action.get("type", "stop")
        distance_m   = action.get("distance_m", 0.0)
        angle_deg    = action.get("angle_deg",  0.0)
        reason       = action.get("reason", "")

        template = self._DESCRIPTIONS.get(
            action_type,
            "Unknown action: {type}"
        )

        # Convert metres → centimetres for readability
        command = template.format(
            distance_m = distance_m * 100,
            angle_deg  = angle_deg,
            type       = action_type,
        )

        output = f"[ROBOT] {command}"
        if reason:
            output += f"\n        Reason: {reason}"

        print(output)
        return output
