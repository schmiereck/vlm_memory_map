import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ----------------------------------------------------------------------
# Value objects
# ----------------------------------------------------------------------

@dataclass
class Pose:
    """Robot pose: 2D position + heading."""
    x:   float
    y:   float
    yaw: float   # radians, z-axis rotation

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Pose":
        return Pose(x=data["x"], y=data["y"], yaw=data["yaw"])


@dataclass
class TraceEntry:
    """One recorded step in the robot's movement history."""
    x:         float
    y:         float
    yaw:       float            # radians
    timestamp: str              # ISO-8601
    action:    Optional[str]    # e.g. "forward", "turn_left", "stop"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "TraceEntry":
        return TraceEntry(
            x        =data["x"],
            y        =data["y"],
            yaw      =data["yaw"],
            timestamp=data["timestamp"],
            action   =data.get("action"),
        )

    def __repr__(self) -> str:
        return (
            f"TraceEntry(x={self.x:.2f}, y={self.y:.2f}, "
            f"yaw={self.yaw:.2f}, action={self.action!r}, "
            f"ts={self.timestamp})"
        )


# ----------------------------------------------------------------------
# Manager
# ----------------------------------------------------------------------

class PositionManager:
    """
    Tracks the robot's current pose and its full movement history (trace).

    Typical usage:
        pm = PositionManager()
        pm.load()
        pm.move_to(x=0.3, y=0.0, yaw=0.1, action="forward")
        img = coord_mgr.get_map_image(..., trace=pm.get_trace_points())
        pm.save()
    """

    def __init__(self, file_path: str = "position.json"):
        self._file_path = Path(file_path)
        self._pose:  Pose             = Pose(0.0, 0.0, 0.0)
        self._trace: list[TraceEntry] = []

    # ------------------------------------------------------------------
    # Current pose
    # ------------------------------------------------------------------

    @property
    def pose(self) -> Pose:
        """The robot's current position and heading."""
        return self._pose

    def set_pose(
        self,
        x:      float,
        y:      float,
        yaw:    float,
        action: Optional[str] = None,
        record: bool = True,
    ) -> None:
        """
        Set the robot's pose directly (e.g. after an external correction).

        Args:
            x, y:   World position in meters.
            yaw:    Heading in radians.
            action: Optional label for this pose change.
            record: Whether to append the new pose to the trace (default True).
        """
        self._pose = Pose(x=x, y=y, yaw=yaw)
        if record:
            self._append_trace(action)

    def move_to(
        self,
        x:      float,
        y:      float,
        yaw:    float,
        action: Optional[str] = None,
    ) -> None:
        """
        Update pose and always record a trace entry.
        Convenience wrapper around set_pose(record=True).
        """
        self.set_pose(x=x, y=y, yaw=yaw, action=action, record=True)

    # ------------------------------------------------------------------
    # Trace
    # ------------------------------------------------------------------

    @property
    def trace(self) -> list[TraceEntry]:
        """Full movement history, oldest first."""
        return list(self._trace)

    def get_trace_points(
        self,
        last_n: Optional[int] = None,
    ) -> list[TraceEntry]:
        """
        Return trace entries for map rendering.

        Args:
            last_n: If given, return only the most recent N entries.
        """
        entries = self._trace
        if last_n is not None:
            entries = entries[-last_n:]
        return list(entries)

    def clear_trace(self) -> None:
        """Remove all trace history."""
        self._trace.clear()

    def trim_trace(self, keep_last: int) -> None:
        """Keep only the most recent N trace entries."""
        self._trace = self._trace[-keep_last:]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_trace(self, action: Optional[str]) -> None:
        self._trace.append(TraceEntry(
            x        =self._pose.x,
            y        =self._pose.y,
            yaw      =self._pose.yaw,
            timestamp=datetime.now(timezone.utc).isoformat(),
            action   =action,
        ))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist current pose and full trace to the JSON file."""
        data = {
            "pose":  self._pose.to_dict(),
            "trace": [entry.to_dict() for entry in self._trace],
        }
        self._file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load(self) -> None:
        """Load pose and trace from the JSON file (overwrites current state)."""
        if not self._file_path.exists():
            return
        data = json.loads(self._file_path.read_text())
        self._pose  = Pose.from_dict(data["pose"])
        self._trace = [TraceEntry.from_dict(e) for e in data.get("trace", [])]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Number of trace entries."""
        return len(self._trace)

    def __repr__(self) -> str:
        return (
            f"PositionManager(pose={self._pose}, "
            f"trace_len={len(self._trace)}, "
            f"file='{self._file_path}')"
        )


# ----------------------------------------------------------------------
# Quick demo
# ----------------------------------------------------------------------
if __name__ == "__main__":
    pm = PositionManager("position.json")

    pm.move_to(0.0,  0.0,  0.0,  action="start")
    pm.move_to(0.3,  0.0,  0.0,  action="forward")
    pm.move_to(0.6,  0.0,  0.0,  action="forward")
    pm.move_to(0.6,  0.0,  0.52, action="turn_left")
    pm.move_to(0.6,  0.3,  0.52, action="forward")
    pm.move_to(0.6,  0.6,  0.52, action="forward")

    print(f"Current pose: {pm.pose}")
    print(f"Trace length: {len(pm)}")
    print("\nLast 3 trace entries:")
    for entry in pm.get_trace_points(last_n=3):
        print(f"  {entry}")

    pm.save()
    print(f"\nSaved to {pm._file_path}")

    pm2 = PositionManager("position.json")
    pm2.load()
    print(f"Reloaded: {pm2}")

    pm2.trim_trace(keep_last=100)
    print(f"After trim: {len(pm2)} trace entries")
