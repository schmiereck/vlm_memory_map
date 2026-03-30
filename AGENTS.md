# AGENTS.md — Hexapod Spatial Memory System

This file describes the idea, concept, and architecture of the hexapod spatial
memory system for use by coding agents (Claude Code, Copilot, etc.) during
further development.

---

## Idea

A six-legged walking robot (hexapod) is controlled by a Vision-Language Model
(VLM — currently Gemini, with Llama 4 Scout via Groq as fallback).
The robot has no classical SLAM. Instead, the VLM acts simultaneously as
**sensor interpreter**, **cartographer**, and **navigator**.

The core idea: give the VLM a persistent, structured spatial memory so that it
can plan beyond its current field of view, recognize previously visited places,
and correct its own drift — all via natural language and structured JSON output.

---

## Concept

Every control cycle the VLM receives:

1. **A combined image** — camera frame (top) + top-down map (bottom).
   The map is always robot-centric: the robot points upward, north is relative.
2. **A JSON state block** — all known objects, their coordinates, spatial
   relations, the robot's current pose, and operator hints.
3. **The system prompt** — rules, output schema, object ID conventions.

The VLM responds with a single JSON block that contains:
- A **movement command** (`forward`, `backward`, `turn_left`, `turn_right`, `stop`)
- **Memory updates** — new objects, coordinates, relations
- **Corrections** — if the camera image contradicts the stored map

The application layer parses this response, updates the memory, renders a new
map image, and sends the next request.

This creates a closed perception–memory–action loop driven entirely by the VLM.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        VLM (Gemini / Groq)               │
│              system_prompt.py  +  user turn              │
└────────────────────────┬────────────────────────────────┘
                         │ JSON response
                         ▼
┌─────────────────────────────────────────────────────────┐
│                      MapService                          │
│   process_vlm_response()     get_state()                 │
└──────┬──────────┬──────────────┬────────────────┬───────┘
       │          │              │                │
       ▼          ▼              ▼                ▼
ObjectManager  RelationManager  CoordinateManager  PositionManager
objects.json   relations.json   coordinates.json   position.json
                                      │
                                      ▼
                               get_map_image()
                               (PIL rendering)

┌─────────────────────────────────────────────────────────┐
│                    UserTurnBuilder                        │
│   build(camera_image) → [image_part, json_part]          │
└──────────────────────────┬──────────────────────────────┘
                           │
                    HintManager
                    hints.json
```

### File Overview

| File | Class | Responsibility |
|---|---|---|
| `object_manager.py` | `ObjectManager` | Named objects with description and area |
| `relation_manager.py` | `RelationManager` | Spatial relations between objects |
| `coordinate_manager.py` | `CoordinateManager` | 2D/3D positions, sizes, rotations + map rendering |
| `position_manager.py` | `PositionManager` | Robot pose + movement trace |
| `map_service.py` | `MapService` | Facade: owns all four managers, VLM interface |
| `hint_manager.py` | `HintManager` | Operator hints (permanent / session / one_time) |
| `user_turn_builder.py` | `UserTurnBuilder` | Assembles image + JSON for each VLM call |
| `system_prompt.py` | `SYSTEM_PROMPT` | VLM instructions, rules, output schema |

---

## Data Model

### Object
```json
{"id": "T1", "description": "large oak dining table", "area": "living room"}
```
IDs use fixed prefixes: `T`=Table, `C`=Chair, `W`=Wall, `D`=Door, `Wi`=Window,
`Sh`=Shelf, `Cb`=Cabinet, `P`=Plant, `B`=Box, `St`=Stairs, `Ob`=Other.

### Coordinate
```json
{
  "id": "T1",
  "position": {"x": 1.5, "y": 2.0},
  "size":     {"x": 1.2, "y": 0.8, "z": null},
  "rotation": {"x": null, "y": null, "z": 0.3},
  "area": "living room"
}
```
All coordinates in metres, angles in radians. `null` means "not set" — not zero.

### Relation
```json
{"object_a": "T1", "relation": "stands in front of", "object_b": "W1", "area": "living room"}
```

### Robot Pose (PositionManager)
```json
{"x": 0.3, "y": 0.1, "yaw": 0.15}
```
Origin (0, 0) is the robot's start position. `yaw=0` = North, positive = CCW.

### Hint
```json
{
  "permanent": ["Avoid carpets — robot slips"],
  "session":   ["Find the way to the kitchen"],
  "one_time":  ["Table T1 was just moved 20 cm to the right"]
}
```

---

## VLM Control Loop

```python
svc     = MapService(data_dir="data/")
hints   = HintManager("data/hints.json")
builder = UserTurnBuilder(svc, hints)

svc.load_all()
hints.load()

while running:
    frame    = camera.capture()                      # PIL Image
    turn     = builder.build(camera_image=frame)     # image + JSON parts
    response = vlm.generate(SYSTEM_PROMPT, turn)     # VLM call
    result   = json.loads(response.text)

    summary  = svc.process_vlm_response(result)      # update memory
    robot.execute(result["action"])                   # move robot
    svc.save_all()                                    # persist
```

---

## Coordinate System

```
         N (yaw = 0)
         ↑
         │
W ───────┼─────── E    (robot starts at origin)
         │
         ↓
         S

yaw positive = counter-clockwise (mathematical convention)
x positive   = East
y positive   = North
```

All object positions are in **world coordinates** — not relative to the robot.
The map rendering transforms world → robot-centric view on each frame.

---

## Map Rendering

`CoordinateManager.get_map_image()` produces a square PNG:

- Background: light grey grid (1 m cells)
- Objects: blue rectangles (with size/rotation) or blue dots
- Object labels: ID string next to each object
- Trace: red polyline of past robot positions
- Robot: red triangle, tip = heading = always pointing up

The `MapService.get_state()` calls `_build_combined_image()` to stack the
camera frame (top) and the map (bottom) into one image for the VLM.

---

## Corrections & Drift Handling

The VLM can issue three correction types:

| Type | Effect |
|---|---|
| `move_object` | Moves a single object to a new position |
| `rotate_map` | Rotates all object positions around the origin by `delta_yaw` |
| `set_robot_pose` | Hard-resets the robot's estimated pose |

Correction rules (enforced via system prompt):
- Discrepancies < 20 cm are ignored
- `rotate_map` only when multiple objects are systematically off
- Corrections are applied before the next map render

---

## Areas

Every object, coordinate, and relation carries an optional `area` string
(e.g. `"living room"`, `"kitchen"`, `"garden"`). This allows the system
to manage a whole building while only rendering/sending the relevant subset
to the VLM when needed.

`MapService.get_state(area="living room")` filters all three managers.

---

## Extension Points for Agents

When extending this system, focus on these areas:

### 1. VLM Client (`vlm_client.py` — not yet implemented)
Wrap the Gemini and Groq API calls. Should handle:
- Retry logic on malformed JSON responses (strip markdown, re-parse)
- Fallback from Gemini to Groq (Llama 4 Scout)
- Response validation against the expected schema

### 2. Robot Interface (`robot_client.py` — not yet implemented)
Translate `action` JSON to actual robot commands (ROS2 topics or serial).
Current action types: `forward`, `backward`, `turn_left`, `turn_right`, `stop`.
Fields: `distance_m`, `angle_deg`.

### 3. Camera Interface (`camera_client.py` — not yet implemented)
Capture frames as PIL Images. On the Raspberry Pi this will be a PiCamera2
wrapper; in simulation a static image or video file reader.

### 4. Main Loop (`main.py` — not yet implemented)
Tie everything together. Should include:
- Configurable loop frequency
- Graceful shutdown on KeyboardInterrupt with `save_all()`
- Logging of VLM responses and summaries
- CLI for adding/removing hints at runtime

### 5. Map Rendering Improvements
- Draw area boundaries as coloured regions
- Distinguish object confidence visually (solid vs. dashed outline)
- Add a compass rose and scale bar to the map image
- Configurable colour scheme

### 6. Coordinate Confidence (`coordinate_manager.py`)
Add an optional `confidence: float` field (0.0–1.0) to `ObjectCoordinate`.
Low-confidence objects render with a dashed outline and are weighted less
during correction decisions.

### 7. Schema Validation
Add a JSON Schema (or Pydantic model) for the VLM response to validate
before passing to `process_vlm_response()`. Reject and retry on validation
failure.

---

## Key Design Decisions

**Why not classical SLAM?**
The hexapod has no LiDAR or depth camera. The VLM is already doing image
interpretation — giving it the spatial memory directly avoids a second
processing stage and keeps the system simple.

**Why a pixel image instead of SVG or ASCII grid?**
VLMs are trained on raster images. A rendered PNG gives the VLM a natural
spatial representation it can reason about without coordinate arithmetic.

**Why separate ObjectManager and CoordinateManager?**
Objects (semantic descriptions) and coordinates (metric positions) have
independent update lifecycles. The VLM may name and describe an object
before its position is known, or update a position without changing its
description. Keeping them separate avoids partial-update complexity.

**Why all hints manual-delete only?**
One-time hints often describe physical changes in the environment. Auto-
deleting them after one turn risks losing information if the VLM response
was malformed and the update was never applied. Manual deletion keeps the
operator in control.

**Why English in the system prompt?**
Gemini and Llama are calibrated predominantly on English training data.
English prompts produce more reliable structured output than German prompts,
especially for strict JSON-only responses.

---

## Development Notes

- Python 3.10+. No external dependencies except `Pillow` (map rendering).
- All managers are in-memory with JSON file persistence. SQLite migration
  is straightforward if query complexity grows.
- `area` filtering is available on all three data managers and on
  `MapService.get_state()`.
- `PositionManager.trim_trace(keep_last=N)` should be called periodically
  to prevent unbounded file growth during long sessions.
- The system prompt is in `system_prompt.py` as a plain string constant.
  Import it as `from system_prompt import SYSTEM_PROMPT`.
