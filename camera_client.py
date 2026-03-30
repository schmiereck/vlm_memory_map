"""
camera_client.py
================
Abstract base class for camera interfaces.

To add a new camera backend, subclass CameraClient and implement capture().
The main loop only ever calls capture() — swap without touching other files.

Current implementations:
    LaptopCameraClient   — OpenCV webcam (laptop testing)

Planned:
    PiCameraClient       — PiCamera2 on Raspberry Pi
    StaticImageClient    — reads a fixed file (unit testing)
"""

from abc import ABC, abstractmethod
from typing import Optional

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


class CameraClient(ABC):
    """Abstract camera interface. All backends must implement capture()."""

    @abstractmethod
    def capture(self) -> Optional["Image.Image"]:
        """
        Capture one frame.

        Returns:
            A PIL Image (RGB) or None if capture failed.
        """

    def open(self) -> bool:
        """
        Optional: open/initialise the camera.
        Returns True on success.
        Called once at startup.
        """
        return True

    def close(self) -> None:
        """Optional: release camera resources. Called on shutdown."""


# ----------------------------------------------------------------------
# Laptop / webcam implementation
# ----------------------------------------------------------------------

class LaptopCameraClient(CameraClient):
    """
    Captures frames from the default laptop webcam via OpenCV.

    Requires: pip install opencv-python Pillow
    """

    def __init__(self, device_index: int = 0, width: int = 640, height: int = 480):
        self._device_index = device_index
        self._width        = width
        self._height       = height
        self._cap          = None

    def open(self) -> bool:
        if not CV2_AVAILABLE:
            print("[Camera] ERROR: opencv-python not installed. Run: pip install opencv-python")
            return False
        if not PIL_AVAILABLE:
            print("[Camera] ERROR: Pillow not installed. Run: pip install Pillow")
            return False

        self._cap = cv2.VideoCapture(self._device_index)
        if not self._cap.isOpened():
            print(f"[Camera] ERROR: Cannot open camera device {self._device_index}")
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        print(f"[Camera] Opened device {self._device_index} "
              f"({self._width}x{self._height})")
        return True

    def capture(self) -> Optional["Image.Image"]:
        if self._cap is None or not self._cap.isOpened():
            print("[Camera] ERROR: Camera is not open.")
            return None

        ret, frame = self._cap.read()
        if not ret:
            print("[Camera] WARNING: Frame capture failed.")
            return None

        # OpenCV returns BGR — convert to RGB for PIL
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame_rgb)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            print("[Camera] Released.")


# ----------------------------------------------------------------------
# Static image implementation (for testing without a camera)
# ----------------------------------------------------------------------

class StaticImageClient(CameraClient):
    """
    Always returns the same image from disk.
    Useful for repeatable tests and CI environments.
    """

    def __init__(self, image_path: str):
        self._path  = image_path
        self._image: Optional["Image.Image"] = None

    def open(self) -> bool:
        if not PIL_AVAILABLE:
            print("[Camera] ERROR: Pillow not installed.")
            return False
        try:
            self._image = Image.open(self._path).convert("RGB")
            print(f"[Camera] Loaded static image: {self._path}")
            return True
        except Exception as e:
            print(f"[Camera] ERROR loading image: {e}")
            return False

    def capture(self) -> Optional["Image.Image"]:
        return self._image

    def close(self) -> None:
        self._image = None
