# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VLM Memory Map is an autonomous hexapod robot control system where a Vision-Language Model (VLM) acts as sensor interpreter, cartographer, and navigator simultaneously. The robot builds a persistent spatial memory (JSON) while navigating, enabling it to plan beyond its current field of view.

**Target hardware:** Six-legged walking robot with a camera
**Primary VLM:** Groq's Llama 4 Scout via Groq API
**Language:** Python 3.10+

## Setup & Running

```bash
pip install -r requirements.txt
export GROQ_API_KEY="gsk_..."
```

| Command | Mode |
|---------|------|
| `python main.py --gui` | GUI (Tkinter) — recommended for development |
| `python main.py` | CLI / headless |
| `python main.py --image test.jpg` | Static image, no camera needed |

Each manager module has a standalone `__main__` demo:
```bash
python position_manager.py
python hint_manager.py
python map_service.py
```

VLM call logs are saved to `data/logs/<timestamp>/` (combined.png, request.json, response_raw.txt, response.json).

## Architecture

The system runs a closed perception-memory-action loop:
1. Capture camera frame
2. `UserTurnBuilder` assembles combined image (camera + top-down map) + JSON state
3. `VlmClient` calls Groq API; retries on malformed JSON
4. `MapService.process_vlm_response()` parses the response and updates the four data managers
5. Robot executes action via `RobotClient`
6. Map re-renders; loop repeats

### Component Map

```
HexapodApp (main.py)
└── MapService (map_service.py)  ← facade
    ├── ObjectManager            objects.json
    ├── CoordinateManager        coordinates.json  + map rendering
    ├── RelationManager          relations.json
    └── PositionManager          position.json (robot pose + trace)
VlmClient        ← Groq API wrapper
UserTurnBuilder  ← assembles VLM input each turn
HintManager      ← operator hints (permanent/session/one-time)
RobotClient      ← abstract; ConsoleRobotClient for dev
CameraClient     ← abstract; LaptopCameraClient / StaticImageClient
HexapodGui       ← optional Tkinter UI
```

### Coordinate System

- Origin (0, 0) = robot start position
- x+ = East, y+ = North; yaw 0 = North, positive = counter-clockwise
- Units: metres and radians
- **VLM provides robot-relative coordinates** (x = right, y = forward); `MapService` transforms them to world coordinates before storing
- `null` in JSON means "not set", not zero

### Object ID Prefixes

`T`=Table, `C`=Chair, `W`=Wall, `D`=Door, `Wi`=Window, `Sh`=Shelf, `Cb`=Cabinet, `P`=Plant, `B`=Box, `St`=Stairs, `Ob`=Other

### VLM Response Schema

```json
{
  "action": {"type": "forward|backward|turn_left|turn_right|stop", "distance_m": 0.3, "angle_deg": 45, "reason": "..."},
  "add_objects": [...],
  "add_coordinates": [...],
  "add_relations": [...],
  "corrections": [...]
}
```

## Key Design Decisions

- **No traditional SLAM:** The hexapod has no LiDAR; the VLM already interprets images, so structured spatial memory avoids a second processing stage.
- **Pixel map (PNG) not SVG/ASCII:** VLMs are calibrated on raster images.
- **ObjectManager and CoordinateManager are separate:** Semantic descriptions and metric positions have independent lifecycles.
- **English system prompt:** English produces more reliable structured JSON from Llama/Gemini.
- **One-time hints are manual-delete only:** Auto-deleting risks losing hints if a VLM response was malformed.

## Extension Points

- **Robot backend:** Swap `ConsoleRobotClient` for a `Ros2RobotClient`
- **Camera backend:** Swap `LaptopCameraClient` for `PiCameraClient` (Raspberry Pi)
- **VLM fallback:** Add Gemini or other providers in `vlm_client.py`
