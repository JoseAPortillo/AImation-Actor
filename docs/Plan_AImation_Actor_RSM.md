# Executive Summary — AImation Actor

## Product

**AImation Actor** is an AI tool for 3D character animation, aimed at generating realistic body motion from:

- Reference video.
- Manual blocking inside the DCC.
- Existing rough animation.

Its goal is to accelerate blocking, in-betweening, and animation cleanup, always preserving the animator's artistic control.

---

## Initial Scope

- Humanoid character.
- Full body.
- No face or fingers in the MVP.
- Realistic style.
- Static camera for video.
- Local processing.
- Minimum GPU: 10 GB VRAM.
- Target rigs: custom.

---

## Platforms

| DCC | Priority |
|---|---|
| Maya | Main priority |
| Blender | Second phase |

---

## Architecture

The tool uses a hybrid architecture composed of three components:

| Component | Technology | Function |
|---|---|---|
| AI Core | Python / FastAPI / PyTorch | Heavy processing, video, pose, cleanup, and generation |
| AImation Flow | Tauri + React Flow | Visual node editor, ComfyUI style |
| DCC Plugins | Maya / Blender | Blocking capture, shadow rig, baking, and integration with the animator |

---

## Main Philosophy

> AI lives outside the DCC.  
> The user experience lives inside the DCC or in the companion app AImation Flow.

The tool does not replace the animator. It acts as an assistant to generate, interpolate, clean up, and enrich animation.

---

## Main Flow

```text
Video / Blocking / Rough Animation
        ↓
AI Core
        ↓
Neutral Motion JSON
        ↓
Shadow Rig in Maya or Blender
        ↓
Animator reviews, edits, and bakes
```

---

## Node Editor

AImation Flow will be a full node graph editor based on:

- Tauri.
- React.
- React Flow.
- TypeScript.

It will allow:

- Simple mode for animators.
- Advanced mode for TDs.
- Preconfigured presets.
- Custom graphs.
- Node-based execution.
- Preview and debugging.
- Saving pipelines in `.aimgraph`.

---

## Main Nodes

| Category | Examples |
|---|---|
| Input | VideoSource, BlockingInput, PoseImport |
| AI | Pose2DDetector, Pose3DLifter, InBetweenGenerator |
| Cleanup | SmoothMotion, FootLock, RootStabilizer |
| Output | RetargetMap, ShadowRigBuilder, ExportBVH, SendToMaya |
| Logic | FrameRange, Preview, Cache, Debug |

---

## MVP Roadmap

| Phase | Objective | Deliverable |
|---|---|---|
| 0 | Definition | Neutral skeleton, JSON format, node catalog |
| 1 | Video-to-motion | CLI capable of generating animation from video |
| 2 | Core API | Local FastAPI service and neutral format |
| 3 | AImation Flow | Tauri app with basic React Flow editor |
| 4 | Maya Plugin | Shadow rig, baking, and core integration |
| 5 | Blocking-to-motion | In-between generation from key poses |
| 6 | Full node graph | Complete editor with all nodes |
| 7 | Blender Plugin | Secondary integration |

---

## Key Decisions

- Maya is developed before Blender.
- The MVP does not include face or fingers.
- The MVP uses a static camera.
- Processing is local.
- Target rigs are custom.
- The node editor is built with Tauri + React Flow.
- The main internal format will be neutral JSON.
- Communication between components will use HTTP/WebSocket.

---

## Main Risks

| Risk | Mitigation |
|---|---|
| Foot sliding | Foot contact detection + IK lock |
| Ambiguity from video | Static camera, simple videos, and manual correction |
| Resource consumption | External core + lightweight Tauri |
| Complex rigs | YAML/JSON presets and configurable retargeting |
| Loss of artistic control | Preserve key poses and non-destructive workflow |

---

## MVP Success Criteria

- Generate recognizable body animation from video.
- Create a baked shadow rig in Maya.
- Capture key poses from the viewport.
- Generate in-betweens while respecting key poses.
- Reduce foot sliding.
- Maintain a non-destructive workflow.
- Provide a functional node editor in Tauri + React Flow.

---

## Conclusion

**AImation Actor** should start as a focused tool, with:

1. Maya as the main DCC.
2. External AI Core.
3. Tauri + React Flow node editor.
4. Non-destructive shadow rig.
5. Realistic body animation.
6. Artistic control preserved.

The product foundation is clear:

> Generate useful, editable, and non-destructive animation for animators, using AI as an assistant and a node graph as the pipeline.