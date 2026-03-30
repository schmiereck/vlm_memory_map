import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Hint:
    text:     str
    category: str   # "permanent" | "session" | "one_time"

    def to_dict(self) -> dict:
        return {"text": self.text, "category": self.category}

    @staticmethod
    def from_dict(data: dict) -> "Hint":
        return Hint(text=data["text"], category=data["category"])

    def __repr__(self) -> str:
        return f"[{self.category}] {self.text}"


class HintManager:
    """
    Manages operator hints in three categories:

    permanent   Always sent to the VLM. Describe invariants of the robot
                or environment ("Avoid carpets — robot slips").

    session     Describe the current goal or task. Replace when the task
                changes ("Find the way to the kitchen").

    one_time    Very recent observations or warnings. Sent every turn until
                manually deleted ("The table was just moved to the right").

    All hints must be deleted manually via delete() or clear_category().
    """

    CATEGORIES = ("permanent", "session", "one_time")

    def __init__(self, file_path: str = "hints.json"):
        self._file_path = Path(file_path)
        self._hints: list[Hint] = []

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------

    def add(self, text: str, category: str) -> Hint:
        """
        Add a new hint.

        Args:
            text:     The hint text sent to the VLM.
            category: One of "permanent", "session", "one_time".

        Returns:
            The created Hint object.
        """
        if category not in self.CATEGORIES:
            raise ValueError(
                f"Unknown category '{category}'. "
                f"Must be one of: {self.CATEGORIES}"
            )
        hint = Hint(text=text, category=category)
        self._hints.append(hint)
        return hint

    def add_permanent(self, text: str) -> Hint:
        return self.add(text, "permanent")

    def add_session(self, text: str) -> Hint:
        return self.add(text, "session")

    def add_one_time(self, text: str) -> Hint:
        return self.add(text, "one_time")

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------

    def get_all(self, category: Optional[str] = None) -> list[Hint]:
        """Return all hints, optionally filtered by category."""
        hints = self._hints
        if category is not None:
            hints = [h for h in hints if h.category == category]
        return list(hints)

    def as_dict(self) -> dict:
        """
        Return hints grouped by category — ready for the VLM state JSON.

        Example output:
            {
                "permanent": ["Avoid carpets"],
                "session":   ["Find the kitchen"],
                "one_time":  ["Table was moved"]
            }
        """
        return {
            cat: [h.text for h in self._hints if h.category == cat]
            for cat in self.CATEGORIES
        }

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, text: str, category: Optional[str] = None) -> int:
        """
        Delete hints matching the text (and optionally the category).
        Returns the number of deleted entries.
        """
        before = len(self._hints)
        self._hints = [
            h for h in self._hints
            if not (
                h.text == text
                and (category is None or h.category == category)
            )
        ]
        return before - len(self._hints)

    def delete_by_index(self, index: int) -> Optional[Hint]:
        """
        Delete a hint by its position in get_all() — useful for CLI tools.
        Returns the deleted hint or None if index is out of range.
        """
        if index < 0 or index >= len(self._hints):
            return None
        return self._hints.pop(index)

    def clear_category(self, category: str) -> int:
        """Remove all hints in a category. Returns number deleted."""
        before = len(self._hints)
        self._hints = [h for h in self._hints if h.category != category]
        return before - len(self._hints)

    def clear_all(self) -> None:
        """Remove all hints."""
        self._hints.clear()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        data = [h.to_dict() for h in self._hints]
        self._file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load(self) -> None:
        if not self._file_path.exists():
            return
        data = json.loads(self._file_path.read_text())
        self._hints = [Hint.from_dict(e) for e in data]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._hints)

    def __repr__(self) -> str:
        counts = {cat: len(self.get_all(cat)) for cat in self.CATEGORIES}
        return (
            f"HintManager("
            f"permanent={counts['permanent']}, "
            f"session={counts['session']}, "
            f"one_time={counts['one_time']}, "
            f"file='{self._file_path}')"
        )


# ----------------------------------------------------------------------
# Quick demo
# ----------------------------------------------------------------------
if __name__ == "__main__":
    mgr = HintManager("hints.json")

    mgr.add_permanent("Avoid carpets — robot slips")
    mgr.add_permanent("Maximum step height is 3 cm")
    mgr.add_session("Find the way to the kitchen")
    mgr.add_one_time("The table was just moved to the right")
    mgr.add_one_time("Door D1 is now open")

    print("All hints:")
    for h in mgr.get_all():
        print(f"  {h}")

    print("\nAs dict (for VLM):")
    print(json.dumps(mgr.as_dict(), indent=2, ensure_ascii=False))

    mgr.save()
    mgr2 = HintManager("hints.json")
    mgr2.load()
    print(f"\nReloaded: {mgr2}")

    mgr2.delete("Door D1 is now open")
    print(f"After deleting one-time hint: {mgr2}")
