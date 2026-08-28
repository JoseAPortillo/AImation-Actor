# Plan: AImation Actor
## AI Tool for 3D Character Animation in Maya and Blender

| Field | Value |
|---|---|
| **Product Name** | **AImation Actor** |
| Family | AImation (ComfyUI philosophy, node-based) |
| Version | 0.2 |
| Date | August 28, 2026 |
| Status | Initial draft for technical and product validation |
| Target Platforms | **Maya (priority) and Blender (second phase)** |
| Initial Focus | Realistic full-body animation |
| **Node Editor UI Stack** | **Tauri + React Flow** |
| **Node Architecture** | **Full node graph** |

---

## 1. Executive Summary

This document defines the initial plan for developing **AImation Actor**, a tool within the AImation family focused on 3D character animation, compatible with **Maya** (priority DCC) and **Blender** (second phase), that uses AI models to generate animation from:

1. Reference video.
2. Video with rough animation.
3. Blocking generated directly within the 3D environment.

The tool must be capable of generating:

- An approximate 3D skeleton.
- A **shadow rig** with AI-generated animation.
- Interpolated animation between key poses.
- Motion enrichment while preserving the animator's intent.

The first version will focus on **realistic full-body animation**, without detailed face or fingers. Later, the AI model can be swapped or extended to support other animation styles.

**Product Philosophy:** AImation Actor inherits the AImation philosophy of working through a **full node graph**, implemented with **Tauri + React Flow**. This allows users to compose visual animation generation pipelines (ComfyUI style), with a simple mode for animators and an advanced mode for Technical Artists.

The primary recommendation is to build a **hybrid architecture**:

> **An external AI core/engine + Tauri desktop application (AImation Flow) + lightweight plugins inside Maya and Blender.**

This will allow sharing AI logic across both programs, reduce code duplication, facilitate model updates, and maintain a good user experience within each DCC.

---

## 2. Product Vision

Create an animation assistance tool that enables animators and studios to:

- Start from a video reference and obtain a 3D animation base.
- Leverage manual blocking to automatically generate in-betweens.
- Enrich rough animations with more natural motion.
- Maintain artistic control over key poses, timing, and style.
- Work within Maya and Blender without breaking the existing production pipeline.
- **Compose custom pipelines through a modern node editor (React Flow).**

The tool **should not be seen as a replacement for the animator**, but as an assistant that accelerates:

- Blocking.
- In-betweening.
- Motion cleanup.
- Base animation generation from video.
- Rapid shot iteration.

---

## 3. Objectives

### 3.1 Primary Objectives

1. Generate 3D body animation from video.
2. Generate interpolated animation from manual blocking.
3. Create a temporary shadow rig inside the DCC.
4. Function as a tool compatible with Maya (first) and Blender (later).
5. Maintain a non-destructive workflow for the animator.
6. Allow preservation of user-defined key poses.
7. Reduce repetitive in-betweening and basic cleanup tasks.
8. **Provide a full node graph editor based on Tauri + React Flow.**

### 3.2 Secondary Objectives

1. Support different animation styles in future versions.
2. Incorporate swappable AI models (as swappable nodes).
3. Allow partial regeneration by frame ranges.
4. Integrate presets for custom rigs (priority) and common rigs (future).
5. Export animation in standard formats.
6. Prepare the architecture for facial or finger animation in the future.
7. **Share node graphs between users (pipeline marketplace).**

---

## 4. Initial Scope

### 4.1 Included in the First Version

- Humanoid character animation.
- Basic full body (no hands or face).
- Initial realistic style.
- Input from video (static camera).
- Input from manual blocking.
- Shadow rig generation.
- Animation baking.
- **Priority integration with Maya.**
- Basic integration with Blender in the second phase.
- Key pose preservation.
- Basic motion cleanup.
- Basic foot contact detection.
- Internal neutral animation format.
- **Full node graph editor (Tauri + React Flow) with simple and advanced modes.**
- Simple export to BVH and/or JSON.
- Basic interface within the DCC.
- **Hardware requirement:** GPU with at least 10 GB VRAM, local processing.

### 4.2 Out of Initial Scope

- Full facial animation.
- Detailed fingers.
- Multiple simultaneous characters.
- Multi-person video.
- Moving camera reconstruction (to be added post-MVP).
- Non-humanoid characters (future).
- Advanced cartoon style.
- Specific anime style.
- Cloth or hair simulation.
- Complex physics.
- Universal retargeting for any rig.
- Full studio pipeline integration.
- Public cloud version.
- Real-time collaborative editing.
- Node editor embedded inside the DCC viewport (the standalone Tauri app or webview will be used instead).

---

## 5. Target Users

### 5.1 3D Animator

Needs to:

- Accelerate blocking.
- Generate in-betweens.
- Maintain pose control.
- Iterate quickly.
- Avoid dependency on complex external tools.
- **Use the simple mode of the editor (pre-configured presets).**

### 5.2 Technical Artist / TD

Needs to:

- Configure custom rig presets.
- Map skeletons via nodes.
- Debug retargeting errors.
- **Build custom pipelines with the full node graph.**
- Integrate the tool into the pipeline.
- **Create and share node graphs with the team.**

### 5.3 Small or Independent Studio

Needs to:

- Reduce animation time.
- Use video as direct reference.
- Produce animation with fewer resources.
- Maintain acceptable quality.

---

## 6. Main Use Cases

### 6.1 Use Case 1: Video Reference → 3D Animation

The animator imports or selects a reference video. The tool:

1. Extracts frames.
2. Detects the character.
3. Estimates 2D poses.
4. Generates approximate 3D poses.
5. Cleans up the motion.
6. Creates an animated shadow rig in Maya or Blender.

**Result:** usable rough animation as a base, general body motion, approximate root motion, and possibility for manual correction.

### 6.2 Use Case 2: Manual Blocking → In-betweening

The animator creates key poses inside the DCC. The tool:

1. Captures the selected poses.
2. Identifies keyframes.
3. Generates intermediate animation.
4. Respects the main poses.
5. Applies smoothing and contacts.
6. Returns editable animation.

**Result:** more complete animation from blocking, less manual in-betweening work, and preservation of artistic intent.

### 6.3 Use Case 3: Rough Animation → Enriched Animation

The animator has a rough animation with detailed poses, possibly with stepped animation curves (though this does not affect the tool). The tool:

1. Analyzes existing keys.
2. Detects important poses.
3. Generates transitions.
4. Adds natural variation.
5. Applies cleanup and foot locking.

**Result:** smoother animation, less sliding, more natural motion, and a base for manual refinement.

### 6.4 Use Case 4: Hybrid Workflow (Future)

```text
Video → generates base animation
         ↓
Animator corrects poses
         ↓
AI regenerates specific segments
         ↓
Artistic control is maintained
```

### 6.5 Use Case 5: Custom Pipeline from the Node Editor

The TD opens the **AImation Flow** app (Tauri) and builds a custom graph:

1. Selects a `VideoSource` node with a file.
2. Connects to `Pose2DDetector` (chooses MediaPipe).
3. Connects to `Pose3DLifter` (chooses MotionBERT).
4. Adds a `CustomCleanup` node (proprietary filters).
5. Adds a `RetargetMap` node with the studio's YAML preset.
6. Saves the graph as preset "studio_pipeline_v1".
7. Executes the graph and sends the result to the Maya plugin.

**Result:** reusable pipeline for the entire team, with adjustable parameters at each node.

---

## 7. Architecture Decision

### 7.1 Option A: External Tool

A standalone application that processes video and exports files to Maya/Blender.

**Advantages:**

- Lower dependency on internal DCC APIs.
- Easier to handle heavy AI models.
- Centralized updates.

**Disadvantages:**

- Poorer user experience.
- Less integration with selection, keyframes, rigs, and viewport.
- Less natural workflow for animators.
- Harder to capture blocking done inside the DCC.

### 7.2 Option B: Tool Embedded in Each DCC

Full plugins with AI inside Blender and Maya.

**Advantages:**

- Better integration.
- Direct access to controls, keyframes, and viewport.
- Smoother experience.

**Disadvantages:**

- Duplicated code.
- Complex dependencies inside the DCC.
- Compatibility risks.
- Harder to update.
- Higher load on Maya/Blender.
- **Implementing a node editor inside the DCC is very complex.**

### 7.3 Recommended Architecture: Hybrid + Standalone Tauri App

> **External AI Core (Python) + Node Editor (Tauri + React Flow) + Lightweight Plugins in Maya and Blender.**

```text
┌─────────────────────────────────────────────────────────┐
│           AImation Flow (Tauri + React Flow)            │
│                                                         │
│   ┌─────────────────────────────────────────────────┐  │
│   │       Visual Node Editor (React Flow)           │  │
│   │   ┌─────┐   ┌─────┐   ┌─────┐   ┌─────────┐   │  │
│   │   │Video├──►│Pose ├─► │Lift ├─► │Retarget │   │  │
│   │   │Source│  │ 2D  │  │ 3D  │  │ (YAML)  │   │  │
│   │   └─────┘   └─────┘  └─────┘  └─────────┘   │  │
│   └─────────────────────────────────────────────────┘  │
│                      │ HTTP/IPC                          │
└──────────────────────┼──────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────┐
│              AImation Actor Core (Python)                │
│  FastAPI + PyTorch + OpenCV + ffmpeg + AI Models         │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTP REST
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│  Maya Plugin │ │  Blender │ │   CLI/HTTP   │
│  (cmds/PyMEL)│ │  Plugin  │ │   Clients    │
└──────────────┘ └──────────┘ └──────────────┘
```

**Advantages of the Hybrid + Tauri Architecture:**

- **Single AI engine** for Maya, Blender, and the standalone editor.
- **DCC-independent node editor**: does not depend on Maya's Qt or Blender's UI.
- **Modern and consistent UI** thanks to React Flow.
- **Native performance** with Tauri (Rust backend, web frontend).
- **Lightweight installer** (~10-20 MB vs ~200 MB for Electron).
- **Allows working without opening Maya/Blender** (batch, pre-production).
- **Lightweight DCC plugins**: only send/receive data to/from the core.
- **Easy editor updates** without touching the plugins.
- **Cross-platform compatibility**: Windows, macOS, Linux.
- **Scalability**: node/plugin marketplace can be added.

---

## 8. Node Philosophy: Tauri + React Flow + Full Node Graph

AImation Actor inherits the AImation philosophy based on a complete **full node graph**, implemented with **Tauri** (desktop framework) and **React Flow** (React node library).

### 8.1 Why Tauri + React Flow?

| Technology | Role | Advantages |
|---|---|---|
| **Tauri** | Desktop framework (Rust + Webview) | Lightweight binary, secure, native system access, lower consumption than Electron |
| **React Flow** | Node editor (React) | Modern API, highly customizable, large community, custom node types |
| **React + TypeScript** | Complete frontend | Typing, reusable components, hot reload during development |
| **Rust (Tauri backend)** | Native desktop logic | Fast IPC, file access, Python core process management |

### 8.2 Two Interface Modes

#### Simple Mode (for Animators)

- Panel with predefined presets.
- Load video, choose character, generate.
- Capture key poses, generate in-betweens.
- No need to understand nodes.
- Accessible both from the DCC plugin and the Tauri app.

#### Advanced / Node Mode (for TDs and Advanced Users)

- Visual node editor ComfyUI-style (React Flow).
- Combine, reorder, and customize pipeline steps.
- Create and share custom presets.
- Adjust advanced parameters for each model.
- Debug results step by step (see output of each node).
- Save, load, and export graphs.
- Internal shared graph marketplace.

### 8.3 Available Node Types

Each node has:
- **Inputs**: data it receives (poses, video, frames).
- **Outputs**: data it produces.
- **Parameters**: node UI configuration.
- **Preview**: result preview (optional).

#### Input Nodes (Source)

| Node | Description | Inputs | Outputs |
|---|---|---|---|
| **VideoSource** | Loads reference video | path | frames + metadata |
| **ViewportCapture** | Captures from DCC viewport | - (from plugin) | frames |
| **BlockingInput** | Receives poses from DCC | - (from plugin) | neutral keyposes |
| **PoseImport** | Imports existing BVH/FBX/JSON | path | neutral poses |
| **WebcamSource** | Live webcam capture | device_id | frame stream |

#### AI Nodes (Processing)

| Node | Description | Key Parameters |
|---|---|---|
| **Pose2DDetector** | 2D Keypoints | model (MediaPipe/ViTPose/RTMPose), confidence |
| **Pose3DLifter** | 2D→3D Lifting | model (VideoPose3D/MotionBERT), temporal_window |
| **BodyFitter** | Fit to SMPL-like | iterations, constraints |
| **BodyTracker** | Temporal tracking | smoothing, occlusion_handling |
| **StyleModel** | Apply style | style_preset (realistic/cartoon/etc) |
| **InBetweenGenerator** | Generate in-betweens | preserve_keyposes, method |
| **MotionEnhancer** | Generative AI enrichment | intensity, seed |

#### Cleanup Nodes

| Node | Description |
|---|---|
| **SmoothMotion** | Temporal smoothing (Savitzky-Golay, moving average) |
| **FootContactDetector** | Detects foot contacts |
| **FootLock** | Locks feet to ground during contact |
| **RootStabilizer** | Stabilizes root motion |
| **JitterFilter** | Filters (Kalman, one-euro) |
| **ArcBuilder** | Smooths motion arcs |
| **SpacingRefiner** | Adjusts spacing between frames |
| **KeyReducer** | Reduces redundant keyframes |

#### Rigging / Output Nodes

| Node | Description |
|---|---|
| **NeutralSkeleton** | Defines neutral skeleton |
| **RetargetMap** | Loads YAML/JSON mapping |
| **ShadowRigBuilder** | Configures shadow rig |
| **ControlTransfer** | Transfers animation to final controls |
| **BakeAnimation** | Bakes to keyframes |
| **ExportBVH / ExportFBX / ExportJSON** | Exporters |
| **SendToMaya / SendToBlender** | Sends result to active DCC |

#### Logic Nodes

| Node | Description |
|---|---|
| **FrameRange** | Defines frame range to process |
| **ConditionalBranch** | If/else based on condition |
| **Merge** | Combines two pose streams |
| **Preview** | Shows result preview (image or mini 3D animation) |
| **Cache** | Caches subgraph result |
| **Debug** | Inspects data at any point |

### 8.4 Included Node Presets (Templates)

Although the tool allows a full node graph, pre-configured presets are included:

#### Preset 1: Video to Motion

```text
VideoSource → FrameRange → Pose2DDetector → Pose3DLifter
  → SmoothMotion → FootContactDetector → FootLock
  → NeutralSkeleton → RetargetMap → ShadowRigBuilder
  → SendToMaya
```

#### Preset 2: Blocking to Motion

```text
BlockingInput → InBetweenGenerator → MotionEnhancer
  → FootLock → RetargetMap → ShadowRigBuilder
  → BakeAnimation → SendToMaya
```

#### Preset 3: Rough to Refined

```text
PoseImport → KeyReducer → SmoothMotion
  → InBetweenGenerator → ArcBuilder → FootContactDetector
  → ShadowRigBuilder → Preview / SendToMaya
```

### 8.5 Node Editor Features

#### Core Functionalities

- **Drag & drop** nodes from palette.
- **Typed connections**: incompatible outputs/inputs cannot be connected.
- **Graph validation** before execution.
- **Step-by-step execution**: execute only up to a specific node.
- **Inline preview**: see each node's result (image, keypoints, mini 3D animation).
- **Dynamic parameters**: custom UI per node type.
- **Node grouping** into subgraphs.
- **Copy/paste** nodes and connections.
- Full **undo/redo**.
- **Save/load graphs** in `.aimgraph` format (JSON).
- **Export preset** for sharing.

#### Advanced Functionalities

- **Live reload**: graph changes reflect without re-executing everything.
- **Incremental execution**: only re-execute nodes affected by changes.
- **Profiling**: see execution time per node.
- **Per-node logs**: see output, warnings, errors.
- **Global variables**: parameters shared between nodes.
- **Macros**: convert a subgraph into a custom node.
- **Graph versioning**: change history.

#### UX/UI

- Dark theme (ComfyUI/Blender style).
- Customizable keyboard shortcuts.
- Quick node search.
- Tooltips on all nodes and parameters.
- Side panel with selected node properties.
- Bottom panel with logs and results.
- Graph mini-map.

### 8.6 Integration Between Tauri App and DCCs

The Tauri app (**AImation Flow**) communicates with DCC plugins via:

1. **AI Core (Python)** as intermediary.
2. The DCC plugin registers its session with the core (`POST /sessions/register`).
3. The Tauri app queries active sessions and allows sending results to any of them.
4. The plugin receives the result and creates the shadow rig.

**Typical flow:**

```text
1. User opens Maya (plugin auto-registers session)
2. User opens AImation Flow (Tauri)
3. Creates/edits a node graph
4. Executes the graph
5. Selects "Send to Maya (active session)"
6. Maya receives the result and creates the shadow rig
```

### 8.7 Editor File Formats

| Extension | Description |
|---|---|
| `.aimgraph` | Complete graph (nodes, connections, parameters) |
| `.aimnode` | Exportable custom node |
| `.aimpreset` | Simple preset (reusable subgraph) |

Example `.aimgraph` structure:

```json
{
  "version": "0.1",
  "name": "My Studio Pipeline",
  "author": "TD_Name",
  "nodes": [
    {
      "id": "n1",
      "type": "VideoSource",
      "position": [100, 200],
      "params": { "path": "C:/refs/walk.mp4" }
    },
    {
      "id": "n2",
      "type": "Pose2DDetector",
      "position": [300, 200],
      "params": { "model": "mediapipe", "confidence": 0.8 }
    }
  ],
  "edges": [
    { "source": "n1", "sourceHandle": "frames", "target": "n2", "targetHandle": "frames" }
  ],
  "viewport": { "x": 0, "y": 0, "zoom": 1 }
}
```

---

## 9. Proposed Technical Architecture

### 9.1 Component A: AI Core (Python)

Responsible for heavy processing.

**Suggested stack:**

- Python 3.10 or 3.11.
- PyTorch or ONNX Runtime (for GPUs with 10 GB+ VRAM).
- OpenCV.
- ffmpeg.
- NumPy / SciPy.
- FastAPI for local service.
- Pydantic for data validation.
- Celery / RQ (optional) for job queue.
- CLI for testing and batch.

**Functions:**

- Receive video.
- Receive blocking.
- **Execute complete node graphs.**
- Estimate motion.
- Generate in-betweens.
- Clean up animation.
- Detect contacts.
- Convert to neutral format.
- Export BVH, JSON, or FBX.
- Manage DCC plugin sessions.

### 9.2 Component B: AImation Flow (Tauri + React Flow)

Desktop application for the node editor.

**Stack:**

| Layer | Technology | Function |
|---|---|---|
| **Frontend** | React 18 + TypeScript + Vite | Reactive UI, typing, hot reload |
| **Node Editor** | React Flow | Visual graph, drag & drop |
| **Styles** | Tailwind CSS + shadcn/ui | Modern, consistent UI |
| **Framework** | Tauri 2.x | Packaging, IPC, native access |
| **Native Backend** | Rust (Tauri commands) | File management, processes, IPC with Python core |
| **Core Communication** | HTTP REST + WebSocket (for live updates) | Graph submission, result reception |
| **Global State** | Zustand or Redux Toolkit | Graph state, sessions, preferences |
| **Persistence** | SQLite / Local JSON | History, presets, preferences |

**Functions:**

- Full node graph visual editor.
- Active DCC session management.
- Graph execution and debugging.
- Preset and graph saving.
- Internal shared graph marketplace (future).
- Result preview.
- Global configuration (core path, GPU, etc.).
- Automatic updates (Tauri updater).

### 9.3 Component C: Local Service (Core API)

The core exposes a local API.

```text
http://127.0.0.1:8765
```

**Suggested initial endpoints:**

| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Service status |
| POST | /jobs/video-to-motion | Generate animation from video |
| POST | /jobs/blocking-to-motion | Generate animation from blocking |
| **POST** | **/jobs/graph/execute** | **Execute a complete node graph** |
| GET | /jobs/{job_id} | Job status |
| GET | /jobs/{job_id}/result | Job result |
| GET | /jobs/{job_id}/logs | Per-node logs |
| POST | /sessions/register | Register DCC plugin session |
| POST | /sessions/{id}/push_result | Send result to DCC |
| GET | /sessions | List active sessions |
| GET | /presets/skeletons | Available skeleton presets |
| GET | /presets/styles | Available animation styles |
| GET | /presets/node_graphs | Node pipeline presets |
| **GET** | **/nodes/types** | **Catalog of available nodes with their schemas** |

**Example payload for executing a graph:**

```json
{
  "graph": {
    "nodes": [
      {"id": "n1", "type": "VideoSource", "params": {"path": "ref.mp4"}},
      {"id": "n2", "type": "Pose2DDetector", "params": {"model": "mediapipe"}}
    ],
    "edges": [
      {"source": "n1", "sourceHandle": "frames", "target": "n2", "targetHandle": "frames"}
    ]
  },
  "target_session": "maya_session_001",
  "options": {
    "preview_only": false,
    "save_to_disk": true
  }
}
```

### 9.4 Component D: DCC Plugins

Lightweight plugins for **Maya (priority)** and Blender (second phase).

**Responsibilities:**

- Basic user interface (simple panel).
- Video selection.
- Control and keyframe capture.
- Job submission to the core (or to the node graph).
- Result reception.
- Shadow rig creation.
- Animation baking.
- Session registration with the core.

**Possible panel functions:**

- Generate from video (simple preset).
- Generate from blocking (simple preset).
- Capture selected pose.
- Create shadow rig.
- Bake to action / Bake animation.
- Preview as ghost.
- Apply to controls.
- Export motion.
- Regenerate segment.
- **Open AImation Flow (launches the Tauri app).**
- **Show active session status.**

### 9.5 Component E: Neutral Animation Format

Proprietary JSON format that serves as a bridge between the core, the Tauri app, and the plugins.

**Must contain:**

- Metadata (fps, units, up axis, source, duration, style).
- Skeleton hierarchy (bones, Root, parents, rest position).
- Per-frame transforms (translation, rotation, scale).
- Foot contacts.
- Preserved key poses.
- Per-frame tracking confidence.
- AI model version used.
- **Hash of the node graph that generated it (traceability).**

---

## 10. Neutral Animation Format: Detailed Structure

```json
{
  "meta": {
    "version": "0.2",
    "fps": 24,
    "units": "cm",
    "up_axis": "Y",
    "source_type": "video",
    "duration_frames": 120,
    "style": "realistic_v1",
    "model_version": "motioncore_v0.1",
    "graph_hash": "abc123def456"
  },
  "skeleton": {
    "bones": [
      {
        "name": "Hips",
        "parent": null,
        "rest_position": [0, 100, 0],
        "rest_rotation": [0, 0, 0, 1]
      },
      {
        "name": "Spine",
        "parent": "Hips",
        "rest_position": [0, 10, 0],
        "rest_rotation": [0, 0, 0, 1]
      }
    ]
  },
  "frames": [
    {
      "frame": 1,
      "time": 0.0,
      "transforms": {
        "Hips": {
          "translation": [0, 100, 0],
          "rotation_quaternion": [1, 0, 0, 0],
          "scale": [1, 1, 1]
        }
      }
    }
  ],
  "contacts": {
    "left_foot": [
      {"frame": 10, "contact": true},
      {"frame": 11, "contact": true}
    ],
    "right_foot": []
  },
  "keyposes": [
    {"frame": 1, "weight": 1.0},
    {"frame": 40, "weight": 1.0},
    {"frame": 80, "weight": 1.0}
  ],
  "tracking": {
    "confidence_per_frame": [0.92, 0.91, 0.88, 0.90]
  }
}
```

### Export Formats

| Format | Recommended Use | Priority |
|---|---|---|
| Neutral JSON | Internal format, metadata, debugging | High |
| `.aimgraph` | Node graph | High |
| BVH | Simple humanoid animation exchange | Medium |
| FBX | Professional pipeline | Medium/high later |
| USD | Modern pipeline, future | Low initial |

---

## 11. Detailed Functional Flows

### 11.1 Video-to-Motion Flow (Simple Mode)

```text
1. User selects video in Maya panel
2. Plugin sends simple preset to core
3. Core executes standard pipeline
4. Plugin receives result
5. Plugin creates shadow rig
6. Plugin bakes animation
7. User reviews and edits
```

### 11.2 Video-to-Motion Flow (Advanced Mode with Tauri)

```text
1. User opens AImation Flow (Tauri)
2. Loads graph "StudioPipeline.aimgraph"
3. Changes VideoSource to new file
4. Executes graph
5. Tauri sends graph to core via POST /jobs/graph/execute
6. Core executes each node in order
7. Core returns per-node results (optional streaming)
8. Core sends final result to active Maya session
9. Maya plugin creates shadow rig
10. User reviews, edits, or re-executes with changes
```

### 11.3 Blocking-to-Motion Flow

```text
1. User selects controls or joints in Maya
2. User marks key poses on timeline
3. Plugin captures poses at keyframes
4. Plugin converts to neutral representation
5. Plugin sends keyposes to core (or to BlockingInput node)
6. Core generates in-betweens
7. Core respects key poses
8. Core applies cleanup and foot lock
9. Core returns neutral animation
10. Plugin creates shadow rig or editable layer
11. User accepts, adjusts, or regenerates
```

### 11.4 Hybrid Flow (Future)

```text
1. Video generates base animation
2. Animator corrects poses inside the DCC
3. Animator marks corrected poses as keyposes
4. AI regenerates only affected segments
5. Full artistic control is maintained
6. Iterative process until desired result
```

---

## 12. AI Technical Pipeline

### 12.1 Video Preprocessing

**Tasks:**

- Validate video file.
- Extract frames.
- Detect FPS.
- Crop character area.
- Detect useful motion start/end.
- Resize if necessary.
- Generate video metadata.

**Possible tools:**

- ffmpeg for frame extraction.
- OpenCV for image processing.
- Bounding box detection to locate character.
- Simple tracking for temporal follow-up.

### 12.2 2D Pose Estimation

**Objective:** obtain body keypoints in each frame.

| Technology | Advantages | Risks | Recommendation |
|---|---|---|---|
| MediaPipe Pose | Fast, easy for prototype | Lower accuracy in complex cases | Fast MVP |
| MMPose / ViTPose | Higher potential quality | Heavier, more configuration | Professional version |
| RTMPose | Good speed/accuracy balance | Weight licenses to review | Intermediate alternative |
| OpenPose | Known ecosystem | Less modern in some cases | Alternative |

**MVP Recommendation:** start with a fast and stable system (MediaPipe or similar), then evaluate more accurate models if quality requires it.

### 12.3 3D Lifting (2D → 3D)

**Objective:** convert 2D keypoints into coherent 3D poses.

| Family | Description | Comment |
|---|---|---|
| Keypoint-based 3D Lifting | VideoPose3D, PoseFormer, MotionBERT | Clear pipeline, works with 2D |
| Body Model Fitting | SMPL, SMPL-X, HybrIK, HMR2-like, WHAM-like | More volumetrically robust |

**Important considerations:**

- A single 2D video has depth ambiguity.
- Temporal and anatomical priors are needed for stabilization.
- SMPL and related technologies have specific licenses that must be reviewed for commercial use.
- For the first version, keypoint-based lifting may be sufficient.
- Body model fitting offers greater robustness but higher complexity.

### 12.4 Temporal Cleanup

**Required tasks:**

- Temporal smoothing (moving average, Savitzky-Golay).
- Jitter filtering (Kalman filter, one-euro filter).
- Root motion stabilization.
- Foot contact detection (by velocity + height).
- Foot sliding reduction.
- Basic ground penetration correction.
- IK to lock feet when contact is detected.
- Root motion normalization.

**This is critical** for the animation to feel professional. Without cleanup, motion generated from video will have visible jitter, sliding feet, and unstable root.

### 12.5 In-between Generation and Enrichment

#### Approach A: Procedural/Classic (Recommended for MVP)

- Spline interpolation.
- Easing curves.
- Euler filters.
- Tangent smoothing.
- Arcs.
- Procedural overlap.
- IK/FK blending.
- Foot contact constraints.
- Procedural secondary motion.

**Advantages:** more control, more predictable, less legal risk, better for preserving animator intent.

**Disadvantages:** may feel less "alive", requires extensive tuning.

#### Approach B: Generative Motion Model (Later Phase)

- Motion diffusion models.
- Latent motion diffusion.
- Motion transformers.
- VQ-VAE + motion generation.
- Keypose-conditioned models.

**Advantages:** can generate more natural motion, can add micro-variations, can "imagine" realistic transitions.

**Disadvantages:** harder to control, may break key poses, requires training data and licenses, may introduce artifacts.

**Recommendation:**

> Start with procedural in-betweening + constraints. Then add a generative model as an optional "motion enhancer".

---

## 13. Motion Representation and Style

To allow changing animation style later, it is necessary to separate:

1. **Structural motion representation:** bones, transforms, timing, contacts.
2. **Style model:** realistic, cartoon, anime, stylized, heavy weight, light, etc.
3. **Retargeting rules:** how that motion applies to a specific rig.

**Style pipeline:**

```text
Input (blocking or video)
        ↓
Neutral Motion Representation
        ↓
Style Model / Motion Enhancer (swappable node)
        ↓
Neutral Styled Motion
        ↓
Retargeting (node with YAML)
        ↓
Shadow Rig in DCC
```

This will allow changing the style model without rebuilding the entire tool, simply by swapping a node in the graph.

---

## 14. Retargeting

### 14.1 Problem

The AI generates a generic skeleton, but each user will have:

- Custom rigs (custom, main MVP focus).
- Different proportions.
- Different bone names.
- Different axes.
- Proprietary constraints.
- Facial rigs (future).
- Controls with complex local spaces.

### 14.2 Solution: Internal Neutral Skeleton

Standard reference hierarchy:

```text
Root
├── Hips
│   ├── Spine
│   │   ├── Chest
│   │   │   ├── Neck
│   │   │   │   └── Head
│   │   │   ├── LeftShoulder
│   │   │   │   └── LeftArm
│   │   │   │       └── LeftForeArm
│   │   │   │           └── LeftHand
│   │   │   └── RightShoulder
│   │   │       └── RightArm
│   │   │           └── RightForeArm
│   │   │               └── RightHand
│   ├── LeftUpLeg
│   │   └── LeftLeg
│   │       └── LeftFoot
│   │           └── LeftToeBase
│   └── RightUpLeg
│       └── RightLeg
│           └── RightFoot
│               └── RightToeBase
```

### 14.3 Mapping Presets

**MVP:** presets for **custom** rigs will be prioritized, configurable by the user via YAML/JSON or through the **RetargetMap** node in the Tauri editor.

**Future (post-MVP):** presets for common rigs will be added:
- Mixamo-like.
- Rigify (Blender).
- Blender Human Meta-Rig.
- Maya HumanIK.

**Conceptual custom preset example:**

```yaml
preset: my_studio_rig
mapping:
  Hips: pelvis_ctrl
  Spine: spine_01_ctrl
  Chest: chest_ctrl
  LeftArm: l_arm_ctrl
  RightArm: r_arm_ctrl
  LeftUpLeg: l_thigh_ctrl
  RightUpLeg: r_thigh_ctrl
options:
  use_root_translation: true
  foot_ik: true
  scale_source_height: true
  preserve_keyframes: true
```

### 14.4 Required Data Per Bone

For each mapping:

- Name in neutral skeleton.
- Name in target rig.
- Rotation offset.
- Axis correction.
- Scale.
- Joint limits.
- Whether it uses IK or FK.
- Whether it has special contact.
- Whether it should preserve position or only rotation.

---

## 15. Shadow Rig

### 15.1 Concept

The shadow rig is a temporary/simple rig that allows:

- Visualizing AI-generated animation.
- Not touching the character's final rig.
- Comparing against original blocking.
- Accepting or rejecting the result.
- Transferring animation to final controls.
- Editing before baking.

### 15.2 Desired Features

- Non-destructive.
- Easy to delete.
- With associated metadata (AI model, version, source, confidence, contacts, preserved keyposes, **node graph used**).
- Capable of displaying simple skeleton, ghost/preview, contacts, and keyframes.
- Allow global offset, retime, segment replacement, and partial regeneration.

### 15.3 Implementation in Maya (Priority)

- Create dedicated namespace `ai_shadow`.
- Create temporary joints or controls.
- Bake animation curves.
- Optionally use animation layers.
- Allow copying animation to final rig controls.
- Store hash of the graph used for possible re-execution.

### 15.4 Implementation in Blender (Second Phase)

- Create dedicated collection `AI_ShadowRig`.
- Create temporary armature.
- Import animation as Action.
- Use constraints to preview over the final rig.
- Use NLA to blend with existing animation.
- Store metadata in custom properties.

---

## 16. Maya Integration (Priority DCC)

### 16.1 Technical Considerations

- Use `cmds`, `maya.api.OpenMaya`, and `PySide` for UI.
- Capture transforms of selected controls.
- Handle namespaces and references.
- Support custom rigs with complex constraints.
- Bake carefully using `bakeResults`.
- Use animation layers if non-destructive behavior is desired.
- Mind performance with heavy scenes.
- Maintain functional undo.
- **Launch Tauri app via subprocess if not already open.**

### 16.2 Plugin Functions

- Tool panel.
- Video selection.
- Selected controls capture.
- Existing keyframes capture.
- Job submission to core (simple mode).
- **Automatic session registration with the core.**
- **Result reception via WebSocket (live updates).**
- Shadow rig creation with namespace.
- Animation curve baking.
- Import as animation layer.
- Retarget to custom rigs via YAML/JSON.
- Animation export.
- **"Open AImation Flow" button (launches Tauri app).**
- **Active session indicator with the Tauri app.**

---

## 17. Blender Integration (Second Phase)

### 17.1 Technical Considerations

- Use `bpy` to create armatures, actions, and fcurves.
- Capture poses from `pose.bones`.
- Use `matrix_basis` or `matrix_world` as appropriate.
- Store actions in temporary library.
- Use collections for shadow rig.
- Use NLA for non-destructive previews.
- Be careful with local vs world transforms.
- Handle scene FPS.
- Respect units and scale.

### 17.2 Plugin Functions

- Tool panel in sidebar.
- Video selection.
- Custom skeleton preset configuration.
- Job submission to core.
- Progress visualization.
- Result import.
- Shadow rig creation.
- Action baking.
- Pose capture from pose mode.
- Control selection for blocking.
- In-between generation.
- Non-destructive preview.
- Animation export.
- **"Open AImation Flow" button.**

---

## 18. User Interface

### 18.1 Simple Panel in DCC: Sections

**Source:**

- Video file.
- Frame range.
- FPS.
- Character preset.
- Style preset.

**Generate:**

- Generate from video.
- Generate from blocking.
- Generate selected range.
- Regenerate segment.

**Cleanup:**

- Smooth amount.
- Foot lock.
- Contact preservation.
- Root stabilization.
- Keyframe reduction.

**Output:**

- Create shadow rig.
- Bake to controls.
- Export BVH.
- Export FBX.
- Save preset.

**Advanced:**

- Open AImation Flow (Tauri).
- Show active sessions.
- Recent graphs.

### 18.2 Node Editor (AImation Flow - Tauri)

**Layout:**

- **Left**: Node palette by category (Source, AI, Cleanup, Output, Logic).
- **Center**: Graph canvas (React Flow).
- **Right**: Properties panel for selected node.
- **Bottom**: Logs, result preview, profiling.
- **Top**: Toolbar with actions (New, Open, Save, Run, Stop, Debug, Settings).

**Floating Windows:**

- 3D Preview (Three.js or Babylon.js).
- 2D keypoints preview over video.
- Animation curves (mini F-Curve editor).
- Pose data table.

### 18.3 Viewport Helpers (Inside the DCC)

It would be useful to visualize:

- AI Skeleton.
- Foot contacts.
- Key poses.
- Generated ranges.
- Per-frame confidence.
- Video ghost overlay.
- Before/after comparison.
- **Link to the graph that generated the animation.**

---

## 19. Communication Between Components

### 19.1 Protocols

```text
┌─────────────────────┐    HTTP/WS     ┌─────────────────┐
│  AImation Flow      │ ─────────────► │  AI Core        │
│  (Tauri + React)    │                │  (Python/FastAPI│
└─────────────────────┘                └─────────────────┘
                                              │
                                              │ HTTP/WS
                                              ▼
                              ┌────────────────────────────────┐
                              │  Maya / Blender Plugins        │
                              └────────────────────────────────┘
```

| Communication | Protocol | Justification |
|---|---|---|
| Tauri ↔ Python Core | HTTP REST + WebSocket | Simple, streaming for live updates |
| DCC Plugin ↔ Python Core | HTTP REST + WebSocket | Same protocol, unification |
| Tauri ↔ DCC Plugin | Indirect through core | Does not couple the apps |
| Tauri ↔ System | Tauri IPC (Rust) | Files, processes, OS notifications |

### 19.2 Future Alternatives

| Protocol | Advantages | When to Use |
|---|---|---|
| Local HTTP REST | Simple, easy debug, standard | MVP and production |
| WebSocket | Live updates, streaming | Real-time progress, preview |
| gRPC | More efficient, streaming | If heavy live preview is needed |
| Local Socket | Less overhead | If maximum performance is sought |
| Shared Memory | Minimal latency | For real-time preview |
| Tauri Events | For intra-app communication | UI ↔ Rust backend |

**Recommendation:** start with HTTP REST + WebSocket. Consider gRPC if heavy streaming is needed.

---

## 20. MVP by Phases

### 20.1 Minimum MVP: General Criteria

- Single humanoid character.
- No face.
- No detailed fingers.
- No multiple characters.
- Basic realistic animation.
- Video with **static camera**.
- Character visible most of the time.
- Output: shadow rig with baked animation.
- **Initial integration: Maya first, Blender later.**
- **Basic Tauri + React Flow node editor (v1 with core nodes).**
- Internal format: Neutral JSON + optional BVH.
- In-between generation: procedural first.
- Local processing with 10 GB VRAM GPU.
- Target rigs: custom (configurable via YAML/JSON).

### 20.2 MVP Phase 1: Video → Skeleton Animation

**Objective:** given a video, generate basic body animation importable in Maya/Blender.

**Functions:**

- Import video.
- Extract frames.
- Detect 2D pose.
- Estimate 3D pose.
- Clean jitter.
- Export BVH/JSON.
- Import as simple skeleton.

**Success criteria:**

- General motion is recognizable.
- Correct timing.
- Reasonable root motion.
- Little drift.
- Importable in Maya and Blender.

### 20.3 MVP Phase 2: Core Service + Base Tauri App

**Objective:** have the core running and the Tauri app with a basic node editor.

**Functions:**

- Complete JSON schema.
- Local API (FastAPI).
- Job manager.
- Tauri app with:
  - React Flow editor with 5-6 basic nodes.
  - Graph save/load.
  - Execution and log visualization.
  - "Video to Motion" preset.

### 20.4 MVP Phase 3: Maya Plugin

**Objective:** user generates animation without leaving Maya.

**Functions:**

- Same core.
- Same neutral format.
- Maya plugin with panel.
- Shadow rig creation.
- Baking.
- Basic integration with selection and keyframes.
- **Session registration + Tauri app launching.**

### 20.5 MVP Phase 4: Blocking → In-betweening

**Objective:** animator creates key poses and the tool generates intermediate animation.

**Functions:**

- Select controls/joints.
- Capture pose at current frame.
- Mark key poses.
- Generate segment between poses.
- Preserve key poses.
- Apply smoothing.
- Bake.

**This flow is probably the most valuable for professional animators.**

### 20.6 MVP Phase 5: Full Node Graph

**Objective:** complete node editor with all planned nodes.

**Functions:**

- All Source, AI, Cleanup, Output, Logic nodes.
- Inline preview per node.
- Macros and subgraphs.
- Per-node profiling.
- Internal graph marketplace.

### 20.7 MVP Phase 6: Basic Blender Plugin

**Objective:** once validated in Maya, port functionality to Blender.

**Functions:**

- Simple panel.
- Select video.
- Launch generation.
- See progress.
- Import result.
- Create shadow rig.
- Bake action.
- Store metadata.
- **Integration with existing Tauri app.**

---

## 21. Detailed Roadmap

### Phase 0: Definition and Conceptual Validation (1-2 weeks)

**Tasks:**

- Define exact scope.
- Decide neutral skeleton.
- Decide formats.
- Choose technology stack (Tauri + React Flow confirmed).
- Define test cases.
- Select test videos (static camera, humanoid, full body).
- Review model licenses.

**Deliverables:**

- Finalized product document.
- Requirements list.
- Defined custom target rigs.
- Selected test videos.
- MVP definition.
- Documented license decisions.
- **Initial node catalog.**

**Decisions already made:**

- **Body scope:** MVP body only. Hands/face in next version.
- **Camera:** static for MVP. Moving camera when scaling.
- **Character type:** always humanoid for MVP. Non-humanoids when scaling.
- **Target rigs:** custom (configurable via YAML/JSON).
- **Deployment:** local.
- **Minimum GPU:** 10 GB VRAM.
- **Node editor:** Tauri + React Flow (full node graph).

---

### Phase 1: Technical Prototype Video to Motion (3-6 weeks)

**Tasks:**

- Video pipeline with ffmpeg/OpenCV.
- 2D keypoint detection.
- 3D lifting.
- Skeleton normalization.
- BVH/JSON export.
- Testing with simple videos.

**Deliverable:**

```bash
aimation-actor generate-video --input ref.mp4 --output result.json
```

**Validation metrics:**

- Temporal stability.
- Approximate pose error.
- Perceived quality.
- Foot sliding.
- Processing time.

---

### Phase 2: Core Service + API + Node Catalog (3-4 weeks)

**Tasks:**

- Define complete JSON schema.
- Implement local API (FastAPI).
- Job manager.
- Preset configuration.
- Logging.
- BVH/JSON exporters.
- **Define node catalog (JSON schemas per type).**
- **Endpoint /nodes/types with schemas.**
- Project structure.
- Unit tests.

**Deliverable:**

```bash
aimation-actor generate-video --input ref.mp4 --output result.json
aimation-actor generate-blocking --input poses.json --output result.json
aimation-actor serve --port 8765
```

---

### Phase 3: Tauri App + Base React Flow Editor (4-6 weeks)

**Tasks:**

- **Tauri 2.x + React + TypeScript + Vite project setup.**
- **React Flow integration with custom node types.**
- **Basic node palette (5-6 core nodes).**
- **Canvas with drag & drop.**
- **Dynamic properties panel.**
- **Graph save/load (.aimgraph).**
- **HTTP connection with Python core.**
- **Graph execution.**
- **Logs and errors.**
- **Preferences (core path, port).**

**Deliverable:**

- **Installable AImation Flow v0.1 app.**
- **Capable of executing the "Video to Motion" preset and returning results.**

**Confirmed stack:**

| Layer | Recommended Version |
|---|---|
| Tauri | 2.x (stable) |
| React | 18.x |
| React Flow | 12.x |
| TypeScript | 5.x |
| Vite | 5.x |
| Tailwind | 3.x |
| shadcn/ui | latest |
| Zustand | 4.x |

---

### Phase 4: Maya Plugin + Tauri Integration (4-6 weeks)

**Tasks:**

- Maya panel (PySide / cmds).
- Selection capture.
- Keyframe capture.
- Temporary joints/controls creation.
- Curve baking.
- Namespace integration.
- Custom rig support (YAML/JSON).
- **Automatic session registration with core.**
- **"Open AImation Flow" button that launches the Tauri app.**
- **Result reception via WebSocket.**

**Deliverable:** Maya plugin with video-to-motion and blocking-to-motion flow, integrated with the Tauri app.

---

### Phase 5: Blocking Capture and In-between Generation (4-8 weeks)

**Tasks:**

- Capture transforms of selected controls.
- Represent keyposes in neutral format.
- **BlockingInput node in React Flow.**
- Procedural interpolation model.
- Foot lock.
- Contact constraints.
- Return to DCC.
- Non-destructive preview.
- Selective baking.

**Deliverable:** "select poses → generate animation" flow both from plugin and from Tauri.

---

### Phase 6: Full Node Graph (6-10 weeks)

**Tasks:**

- **Implement all planned nodes:**
  - All Source (VideoSource, ViewportCapture, BlockingInput, PoseImport, WebcamSource).
  - All AI (Pose2DDetector, Pose3DLifter, BodyFitter, BodyTracker, StyleModel, InBetweenGenerator, MotionEnhancer).
  - All Cleanup.
  - All Output.
  - All Logic (FrameRange, ConditionalBranch, Merge, Preview, Cache, Debug).
- **Inline preview per node (Three.js for 3D, canvas for 2D).**
- **Subgraphs and macros.**
- **Per-node profiling and timing.**
- **Incremental execution.**
- **Internal marketplace (local first, cloud future).**

**Deliverable:** complete node editor with all functional nodes.

---

### Phase 7: Basic Blender Plugin (3-5 weeks)

**Tasks:**

- Sidebar UI panel.
- HTTP connection to core.
- Video submission.
- JSON/BVH reception.
- Armature creation.
- Keyframe baking.
- Shadow rig collection.
- Connection preferences.
- **Integration with Tauri app.**

**Deliverable:** Blender add-on capable of generating animation from video, integrated with Tauri.

---

### Phase 8: Generative AI Enrichment (6-12 weeks)

**Tasks:**

- Integrate generative motion model.
- Condition by keyposes.
- Add style parameters.
- **Functional MotionEnhancer node.**
- Evaluate foot sliding.
- Maintain artistic control.
- A/B comparison with procedural interpolation.

**Deliverable:** `realistic_v1` model for enriched in-betweening.

---

### Phase 9: Polish, Presets, and Beta (4-8 weeks)

**Tasks:**

- Custom rig presets.
- Error handling.
- Progress bars.
- Logs.
- Documentation.
- Automated installation.
- Cross-platform testing.
- Validation with real animators.
- **Tauri updater (automatic updates).**

**Deliverable:** private beta.

---

## 22. Immediate Plan: First 10 Weeks

| Week | Main Activity | Deliverable |
|---|---|---|
| 1 | Define neutral skeleton, JSON format, select videos, review licenses, **define initial node catalog** | Definition document + node catalog |
| 2-3 | Prototype: video → 2D keypoints → basic 3D pose → BVH/JSON export | Basic functional CLI |
| 4 | Minimum core: CLI, config, basic cleanup, simple foot contact, **/nodes/types endpoint** | AImation Actor Core v0.1 |
| **5-6** | **Tauri + React Flow setup: base project, canvas, 5-6 core nodes, .aimgraph saving** | **AImation Flow v0.1 (editor MVP)** |
| 7-8 | **Minimum Maya plugin: panel, core submission, shadow rig creation, bake, Tauri launch** | **Maya Add-on v0.1** |
| 9-10 | Minimum blocking: capture 3 poses, generate interpolation, BlockingInput node in React Flow | End-to-end functional blocking flow |

---

## 23. Product Strategy

### Planned Versions

| Version | Main Functionality |
|---|---|
| 0.1 | Video → rough animation. BVH/JSON output. CLI usage. Validate AI quality. |
| 0.2 | Local core with API + base Tauri app with minimal React Flow editor (5-6 nodes). |
| **0.3** | **Basic Maya plugin. Shadow rig. Video-to-motion inside Maya. Tauri integration.** |
| **0.4** | **Blocking capture in Maya. Procedural in-between generation. Keypose preservation. BlockingInput node.** |
| 0.5 | Basic Blender plugin. Custom retargeting. Tauri integration. |
| **0.6** | **Complete full node graph: all nodes, previews, subgraphs, profiling.** |
| 0.7 | Generative AI enrichment model. Improved realistic style. MotionEnhancer node. |
| 0.8 | Internal shared graph marketplace. |
| 1.0 | Stable tool. Maya and Blender. Character presets. Style management. Local processing. Complete documentation. Active Tauri updater. |

---

## 24. Suggested Team

For a first version, a minimum team could be:

| Role | Responsibility |
|---|---|
| Technical Artist / Tools Developer | Maya/Blender plugins, custom rigs, baking, retargeting |
| ML Engineer | Pose models, video pipeline, cleanup, motion generation |
| **Frontend Engineer (React/Tauri)** | **Node editor, Tauri UI, React Flow integration** |
| Animator TD / Animation Consultant | Quality validation, workflow definition, real problem detection |
| Product / Project Owner | Scope, priorities, user validation |

If there is only one person, the project is possible as a prototype, but it will be slower. Ideally, start very scoped.

---

## 25. Main Risks

### Risk 1: Insufficient Quality from Video

2D video has depth ambiguity.

**Mitigation:**

- Start with simple videos.
- Static camera.
- Visible body.
- Good lighting.
- Allow manual correction.
- Use video as base, not final result.

### Risk 2: Foot Sliding and Lack of Weight

One of the most visible problems in generated animation.

**Mitigation:**

- Foot contact detection.
- Foot IK.
- Ground constraints.
- Manual cleanup.
- "Fix foot contact" tools.

### Risk 3: Retargeting to Complex Custom Rigs

Every rig is different.

**Mitigation:**

- Start with simple skeletons.
- Editable presets (YAML/JSON).
- Configurable mapping via nodes.
- Initial support for common structures.
- Do not promise universal compatibility on day one.

### Risk 4: Model and Dataset Licenses

Many academic models lack clear commercial licenses.

**Mitigation:**

- Review licenses before integrating.
- Use permissive models when possible.
- Consider training proprietary models.
- Use licensed datasets.
- Avoid depending on problematic weights if the product will be commercial.

### Risk 5: Dependencies Inside Maya/Blender

Putting PyTorch/CUDA inside the DCC can be fragile.

**Mitigation:**

- External core.
- Lightweight plugins.
- Localhost communication.
- Separate installer for the AI engine.
- **Tauri as separate app.**

### Risk 6: Lack of Artistic Control

If the AI generates too much, the animator may feel they lose control.

**Mitigation:**

- Always preserve keyposes.
- Non-destructive editing.
- Shadow rig as preview.
- Range-based regeneration.
- Intensity parameters.
- "Cleanup only" mode.
- "In-between only" mode.

### Risk 7: Node Editor Complexity

A poorly designed node editor can intimidate non-technical animators.

**Mitigation:**

- Offer Simple mode by default in the DCC.
- Ready-to-use pre-configured presets.
- Clear documentation with examples.
- Tooltips on every node.
- Invalid connection validation.
- **Highly polished official templates (Video-to-Motion, Blocking-to-Motion).**

### Risk 8: Tauri ↔ DCC Integration

Coordinating the Tauri app with plugins can have UX friction.

**Mitigation:**

- **Automatic session registration in the core.**
- **WebSocket for real-time updates.**
- **Core acts as broker: never direct Tauri ↔ Plugin communication.**
- **Clear active session indicators.**
- **"Open AImation Flow" button from the DCC.**

### Risk 9: Node Editor Performance

With very large graphs or many previews, React Flow can slow down.

**Mitigation:**

- **Node virtualization (React Flow includes this by default).**
- **Lazy preview (only for selected node).**
- **Cache executed node results.**
- **Incremental execution (don't re-execute entire graph).**
- **Limit preview FPS.**

### Risk 10: Tauri Cross-Platform Compatibility

Tauri uses the OS's native Webview (Edge WebView2 on Windows, WebKit on macOS/Linux).

**Mitigation:**

- **Test on all 3 OSes from the start.**
- **WebView2 installer for Windows if not present.**
- **CSS fallback for unsupported features.**
- **Multi-platform CI/CD with GitHub Actions.**

---

## 26. Success Criteria for the First Version

A first version would be successful if it achieves:

1. Import a simple video and generate recognizable body animation.
2. **Create a shadow rig in Maya with baked animation.**
3. Allow capturing key poses from the viewport.
4. Generate in-betweens while maintaining key poses.
5. Notably reduce foot sliding.
6. Export/import in Maya and Blender without breaking hierarchies.
7. Maintain a non-destructive workflow.
8. Be usable by an animator without AI knowledge.
9. **Provide a functional full node graph editor in Tauri + React Flow.**
10. **Allow TDs to create, save, and share custom graphs (.aimgraph).**
11. **Seamless integration between the Tauri app and the Maya plugin (sessions, live updates).**

---

## 27. Final Architecture Decision

**Original question:** External tool that exports via port to different applications, or tool inside each program?

**Answer:**

> Neither purely. The recommendation is a hybrid architecture with three components:
> 1. External AI Engine (Python/FastAPI)
> 2. Standalone Node Editor (Tauri + React Flow)
> 3. Lightweight Plugins inside Maya and Blender

**Stage 1:** start with an external engine/CLI to validate AI quality, format, and retargeting.

**Stage 2:** build the Tauri app with basic React Flow editor (5-6 nodes).

**Stage 3:** build lightweight plugins inside Maya (priority) and Blender (second phase) with Tauri integration.

**Stage 4:** expand the node editor to full graph.

**Stage 5:** add more advanced AI models for style and enrichment.

**Guiding principle:**

> AI should live outside the DCC. The user experience should live inside the DCC (or in a companion app like AImation Flow).

---

## 28. Conclusion

The recommended architecture for **AImation Actor** is:

- **External AI Core** (Python/FastAPI) for heavy processing.
- **AImation Flow** (Tauri + React Flow) as standalone visual node editor.
- **Lightweight Plugins** in Maya (priority) and Blender (second phase) for in-DCC user experience.
- **Neutral Animation Format** to communicate core, Tauri, and plugins.
- **Non-destructive Shadow Rig** inside each DCC.
- **Editable Pipeline** by the animator at all times.
- **Full Node Graph** inheriting the AImation family philosophy.

The first version must focus on:

1. Realistic body animation (full body, no hands or face).
2. Video-to-motion as first flow.
3. Blocking-to-motion as second flow.
4. **Maya as first testing ground.**
5. **Tauri + React Flow node editor as AImation family differentiator.**
6. Procedural in-betweening first, generative AI later.
7. **Blender as second integration.**
8. Artistic control always preserved.
9. Custom rigs as primary target.
10. Local processing with 10 GB+ VRAM GPU.
11. **Full node graph as natural product evolution.**