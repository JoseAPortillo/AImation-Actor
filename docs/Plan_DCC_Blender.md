# Blender Integration Specification — AImation Actor

| Field | Value |
|---|---|
| **Document Type** | DCC Integration Spec |
| **Target DCC** | Blender 4.0+ |
| **Version** | 0.1 |
| **Date** | 2026-08-28 |
| **Depends On** | SDD v0.1 §5.2, §17; Sub-Agent Directives §4.4; Maya Spec v0.1 (parity reference) |
| **Owner** | `dcc-integrator` sub-agent |
| **Status** | Draft (Pending Core v0.3 + Maya Plugin v0.3 validation) |

---

## 1. Overview

This document defines the technical specification for the AImation Actor Blender add-on. It mirrors the Maya Integration Spec where applicable to ensure cross-DCC parity, while adapting to Blender's Python API (`bpy`), data model, and extension system.

The add-on is a **lightweight client** communicating with the external AI Core via HTTP/WebSocket. It performs NO AI processing locally. Responsibilities: UI presentation, viewport/pose capture, shadow rig creation, animation baking, and session management.

> ⚠️ **Note:** This spec is drafted early to enable parallel development planning. Implementation begins only after Maya plugin v0.3 validates the core integration patterns. Sections marked `[TBD]` require validation against Blender 4.x+ API stability.

---

## 2. Architecture & Module Structure

### 2.1 Add-on Directory Layout

```text
aimation_actor_blender/
├── __init__.py              # bl_info, register/unregister
├── core/
│   ├── session.py           # Session registration, heartbeat, token mgmt
│   ├── api_client.py        # HTTP/WS client to AI Core (asyncio)
│   └── config.py            # Add-on preferences, Core URL, paths
├── ui/
│   ├── panels.py            # Sidebar panels (VIEW3D_PT_*)
│   ├── operators.py         # All bpy.types.Operator classes
│   ├── node_launcher.py     # "Open AImation Flow" operator
│   └── widgets.py           # Custom UI layouts, property groups
├── capture/
│   ├── pose_capture.py      # Capture selected pose bones / objects
│   ├── keyframe_sampler.py  # Extract fcurve keyframes
│   └── viewport_capture.py  # Viewport screenshot/overlay [TBD]
├── rig/
│   ├── shadow_rig_builder.py # Create/manage shadow armature
│   ├── baker.py             # Animation baking with keyframe preservation
│   └── retarget_applier.py  # Apply neutral motion to target armature
├── utils/
│   ├── collection_mgr.py    # Collection isolation utilities
│   ├── undo_decorator.py    # Undo step wrappers
│   ├── logger.py            # Sanitized logging (SpecSecDev compliant)
│   └── compat.py            # Blender version compatibility shims
└── resources/
    ├── icons/               # Custom icons (icon_load.py)
    └── presets/             # Bundled retarget YAML presets
```

### 2.2 Dependency Rules (Blender-Specific)

| Module | Allowed Imports | Forbidden Imports |
|---|---|---|
| `core/` | `bpy`, stdlib, `aiohttp/websockets` | `numpy`, `torch`, `ui/`, `rig/` |
| `ui/` | `bpy`, `gpu`/`blf` (drawing only), `core/` | `rig/`, `capture/` directly (use operators) |
| `capture/` | `bpy`, `mathutils`, domain entities (via JSON) | `ui/`, `rig/`, external ML libs |
| `rig/` | `bpy`, `mathutils`, `core/` (result fetch) | `ui/`, `capture/`, external ML libs |
| `utils/` | `bpy`, stdlib only | Everything else |

> ⚠️ **CRITICAL:** No heavy dependencies (`numpy`, `torch`, `opencv`) allowed. All math uses `mathutils` or stdlib. Neutral motion arrives as JSON; applied via `bpy.data.actions` / `keyframe_insert`.  
> ⚠️ **Blender Extensions:** If distributing via Blender Extensions platform, MUST comply with GPL compatibility. Core communication via HTTP is acceptable; bundling proprietary binaries is NOT. Plan for split distribution if needed.

---

## 3. Session Management

### 3.1 Session Lifecycle

```text
Add-on Enable → Auto-register session → Async heartbeat (5s) → 
Core ACK → Session Active → [Work] → 
Add-on Disable / Timeout → Deregister
```

### 3.2 Registration Payload

```python
{
    "session_id": "uuid-v4",  # Generated per Blender session
    "dcc_type": "blender",
    "dcc_version": "4.2.0",  # bpy.app.version_string
    "plugin_version": "0.3.1",
    "registered_at": "ISO8601",
    "capabilities": ["shadow_rig", "bake", "viewport_capture", "keyframe_capture"],
    "scene_name": "shot_010_anim.blend",  # Sanitized basename only
    "token": "<instance-token>",  # Read from secure local file / env var
}
```

### 3.3 Token Handling (SpecSecDev)

- Token NEVER stored in `.blend` file, user preferences, or text datablocks.
- Token read at startup from: `%APPDATA%/AImationActor/token.txt` (Win) / `~/.config/AImationActor/token` (Linux/Mac).
- If missing/invalid → UI shows "Connect to AImation Flow" panel. Never auto-generate.
- Token passed in `Authorization: Bearer <token>` header on ALL requests.
- On 401/403 → invalidate session, prompt re-auth. Never retry with same token.
- Token cleared from memory on add-on disable / Blender exit.

### 3.4 Heartbeat & Reconnection

- Heartbeat interval: 5 seconds (asyncio task, non-blocking).
- Missed 3 heartbeats → mark stale, attempt reconnect.
- Exponential backoff: 1s → 2s → 4s → 8s → max 30s.
- Reconnect success → re-register SAME session_id.
- Permanent failure (>5 min) → UI offline indicator, queue pending jobs.
- Heartbeat task cancelled cleanly on add-on disable.

---

## 4. Viewport Data Capture

### 4.1 Pose Capture

Captures world/local transforms of selected pose bones or objects at current frame.

```python
def capture_selected_poses(context: bpy.types.Context) -> dict[str, TransformData]:
    """
    Returns: {"bone_or_obj_name": {"translation": [x,y,z], "rotation_quat": [w,x,y,z], "scale": [x,y,z]}}
    Uses: bone.matrix_world / obj.matrix_world for accuracy.
    Respects: Bone layers, collections, linked libraries.
    Skips: Hidden/muted bones, locked transforms (with warning).
    Mode-aware: Pose mode → bones; Object mode → objects.
    """
```

**Constraints:**
- Pose mode: captures `PoseBone.matrix_basis` (local) or `.matrix_world` (world) based on user pref.
- Object mode: captures object transform.
- Rotation ALWAYS quaternion.
- Scale captured but optional (default [1,1,1]).
- Serialized to Neutral Motion JSON before sending.
- Large selections (>200 bones) trigger confirmation dialog.

### 4.2 Keyframe Sampler

Extracts keyframes from selected objects/bones within frame range.

```python
def sample_keyframes(
    context: bpy.types.Context,
    targets: list[bpy.types.ID],
    start_frame: int,
    end_frame: int,
    preserve_keyposes: bool = True,
) -> list[KeyframeData]:
    """
    Returns list of {frame, weight, poses}.
    If preserve_keyposes=True, marks sampled frames with weight=1.0.
    Uses: fcurve.keyframe_points for accurate detection.
    Handles: Actions, NLA strips, drivers (evaluated values).
    """
```

**Constraints:**
- Respects NLA stacking (samples evaluated result, not just base action).
- Handles muted/soloed NLA tracks correctly.
- Frame range validated: start <= end, within scene frame range.
- Drivers evaluated at sample time (not baked).
- Large ranges (>1000 frames) → confirmation dialog.

---

## 5. Shadow Rig System

### 5.1 Naming & Collection Convention

All shadow rig elements live in dedicated collection:

```text
Collection: "AI_ShadowRig"
  ├── Armature: "ai_shadow_armature"
  │     ├── Bone: "Hips"
  │     ├── Bone: "Spine"
  │     └── ...
  └── Empty: "ai_shadow_metadata"   # Custom properties store traceability
```

### 5.2 Shadow Rig Builder

```python
class ShadowRigBuilder:
    def create(
        self, neutral_motion: NeutralMotion, target_armature: str | None = None
    ) -> bpy.types.Object:
        """
        Creates shadow armature matching neutral skeleton hierarchy.
        Applies animation from neutral_motion as new Action.
        Attaches metadata empty with custom props.
        Returns: armature object

        NON-DESTRUCTIVE: New collection, no links to existing rigs.
        REVERSIBLE: delete_shadow_rig() fully cleans up.
        """

    def delete(self, armature_obj: bpy.types.Object) -> None:
        """Complete cleanup: armature, action, metadata empty, collection."""

    def transfer_to_controls(
        self, shadow_armature: bpy.types.Object, control_map: dict[str, str]
    ) -> None:
        """Copies animation via Copy Transforms constraints + bake."""
```

### 5.3 Metadata Storage

Custom properties on metadata empty:

| Property | Type | Description |
|---|---|---|
| `graph_hash` | STRING | SHA256 of generating .aimgraph |
| `source_type` | STRING | "video" / "blocking" / "rough" |
| `model_version` | STRING | AI model version used |
| `confidence_avg` | FLOAT | Average tracking confidence |
| `created_at` | STRING | ISO8601 timestamp |
| `keypose_frames` | INT_ARRAY | Frames marked as preserved keyposes |
| `core_session_id` | STRING | Session that generated this |

### 5.4 Non-Destructive Guarantees

- ✅ Shadow rig exists ONLY in "AI_ShadowRig" collection.
- ✅ No parent/constraint links to existing rigs unless explicit transfer.
- ✅ Delete removes armature, action, empty, AND collection (if empty).
- ✅ Undo supported: entire creation wrapped in single undo step.
- ✅ Multiple shadow rigs coexist (unique suffix: "AI_ShadowRig_001").
- ✅ Linked/appended scenes: shadow rig stays local, never modifies linked data.

---

## 6. Animation Baking

### 6.1 Bake Operation

```python
def bake_animation(
    context: bpy.types.Context,
    targets: list[bpy.types.ID],
    frame_range: tuple[int, int],
    preserve_keyposes: bool = True,
    smart_euler_filter: bool = True,
    visual_keying: bool = True,
) -> BakeResult:
    """
    Bakes animation to target bones/objects.
    If preserve_keyposes=True, original keys at those frames KEPT.
    Smart euler filter post-bake (bpy.ops.graph.clean_handles equivalent).
    Visual keying ensures world-space accuracy.
    Wrapped in undo step.
    """
```

### 6.2 Keyframe Preservation Logic

When `preserve_keyposes=True`:
1. Identify keypose frames from metadata.
2. Pre-bake: store original FCurve values at those frames.
3. Bake normally across full range (`bpy.ops.nla.bake`).
4. Post-bake: restore original values at keypose frames.
5. Smooth tangents at restored keys to avoid discontinuities.

### 6.3 Safety Checks Before Bake

- ⚠️ Confirm if targets have existing animation (warn + backup option).
- ⚠️ Validate frame range within scene limits.
- ⚠️ Check for locked/driven attributes (skip with warning log).
- ⚠️ Verify shadow rig metadata exists and valid.
- ❌ Abort if token/session invalid.
- ❌ Abort if target is linked library data (read-only).

---

## 7. User Interface

### 7.1 Panel Layout

Sidebar panel in 3D Viewport (`VIEW3D_PT_AImationActor`). Sections:

| Section | Controls | Notes |
|---|---|---|
| **Connection Status** | Indicator icon, session ID, "Reconnect" button | Green/yellow/red status icons |
| **Source** | Video file browser, frame range, preset dropdown | File selector filtered: mp4/mov/avi |
| **Generate** | "From Video", "From Blocking", "Regenerate Range" ops | Disabled when offline |
| **Cleanup** | Smooth slider (0-1), Foot Lock toggle, Root Stabilize | Props sent to Core |
| **Output** | "Create Shadow Rig", "Bake to Controls", "Export BVH" | Context-sensitive |
| **Advanced** | "Open AImation Flow", "Show Logs", "Preferences" | Launches Tauri app |

### 7.2 Operators & Modal Execution

All long-running operations use modal operators with progress cursor:

```python
class AIM_OT_generate_from_video(bpy.types.Operator):
    bl_idname = "aim.generate_from_video"
    bl_label = "Generate from Video"
    
    def modal(self, context, event):
        # Non-blocking async execution
        # Progress bar via wm.progress_begin/update/end
        # Cancel check via event.type == 'ESC'
        pass
```

- Network calls run in separate thread / asyncio.
- Results posted back via `bpy.app.timers.register` (main thread safe).
- Progress reported via `wm.progress_*` API.
- ESC key cancels operation gracefully.

### 7.3 Preferences Panel

Located in Edit → Preferences → Add-ons → AImation Actor:

| Setting | Type | Default | Notes |
|---|---|---|---|
| Core URL | STRING | http://127.0.0.1:8765 | Validated on save |
| Auto-connect | BOOL | True | Register session on enable |
| Capture Space | ENUM | WORLD / LOCAL | WORLD default |
| Show Debug Logs | BOOL | False | Enables verbose sanitized logs |
| Tauri App Path | FILE_PATH | (auto-detect) | Manual override if needed |

---

## 8. Security Controls (SpecSecDev for Blender)

### 8.1 Threat Model Entries

| Asset | Threat | Control | Verification |
|---|---|---|---|
| Session Token | Extraction from .blend/prefs | Never in blend/prefs/text blocks. Memory cleared on disable. | Grep + memory inspection |
| Received Animation | Malicious attribute injection | Whitelist allowed data paths. Validate types/ranges. | Fuzz test malformed JSON |
| Video Path | Path traversal | Canonicalize + prefix validate. No `..`/symlinks. | Path fuzzing suite |
| Shadow Collection | Name collision/hijack | Unique suffix. Validate pre-create. | Collision stress test |
| Bake Operation | Data loss | Backup prompt. Undo step. Keyframe preservation. | UAT + undo verification |
| Logs | Scene/content leakage | Sanitize all names/paths. No pose values. | Log audit script |
| Blend File Save | Accidental token persistence | Hook into save_pre to strip sensitive props. | Save/load cycle test |

### 8.2 Mandatory Pre-Merge Checklist (Blender Add-on)

- [ ] No heavy dependencies (numpy/torch/cv2)?
- [ ] Token never touches .blend, prefs, or text blocks?
- [ ] All data path assignments validated (no arbitrary setattr)?
- [ ] Shadow rig creation/deletion fully reversible + undoable?
- [ ] Keyframe preservation tested with NLA/drivers edge cases?
- [ ] Modal operators non-blocking + cancellable?
- [ ] Logs sanitized (no paths/poses/video content)?
- [ ] Tested on Blender 4.0 + 4.2 LTS minimum?
- [ ] Session reconnection handles timeout gracefully?
- [ ] Save-pre hook prevents token persistence?
- [ ] GPL compliance verified (if Extensions distribution)?
- [ ] Security-auditor sign-off obtained?

---

## 9. Testing Strategy

### 9.1 Test Categories

| Category | Scope | Tools | Coverage Target |
|---|---|---|---|
| Unit | Utils, serializers, validators | pytest + fake-bpy-module | 90% |
| Integration | Session flow, capture→bake pipeline | pytest + blender-headless | 70% |
| UI | Panel/operator interactions | pytest + bpy.utils.testing | 60% |
| Security | Token, input validation, sanitization | Custom fuzzers + manual audit | 100% checklist |
| Compatibility | Blender 4.0, 4.2 LTS, 4.3+ | CI matrix | Pass/Fail |

### 9.2 Golden Files

- Reference .blend files with expected shadow rigs.
- Expected bake outputs for standard test motions.
- Regenerated ONLY via approved CI script. Manual regen forbidden.

### 9.3 Headless Testing

All integration tests run via `blender --background --python test_runner.py`. No GUI required. Viewport capture tests skipped headless (xfail with ticket).

---

## 10. Deployment & Installation

### 10.1 Installation Methods

| Method | Command / Steps | Notes |
|---|---|---|
| Blender Extensions (future) | Install via Extensions panel | Requires GPL review + split binary plan |
| ZIP Install | Edit → Preferences → Add-ons → Install | Standard .zip with bl_info |
| Manual | Copy to scripts/addons/ | For dev/studio deploy |
| Studio Deploy | SCCM/Munki + token provisioning | Air-gapped friendly |

### 10.2 bl_info Compliance

```python
bl_info = {
    "name": "AImation Actor",
    "author": "AImation Team",
    "version": (0, 3, 1),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > AImation Actor",
    "description": "AI-assisted character animation via node graph",
    "category": "Animation",
    "support": "COMMUNITY",  # Change to OFFICIAL if adopted
}
```

### 10.3 First-Time Setup

On first enable, if no token:
1. Show setup dialog in Preferences.
2. Prompt to launch AImation Flow (or set path).
3. Auto-detect running Core via localhost scan.
4. Secure handshake for token.
5. Save token to OS secure location.
6. Register session.

---

## 11. Parity Matrix vs Maya Spec

| Feature | Maya Spec | Blender Spec | Notes |
|---|---|---|---|
| Session mgmt | ✅ | ✅ | Identical protocol |
| Token storage | OS file | OS file | Same path convention |
| Pose capture | OpenMaya | mathutils + matrix_world | Equivalent accuracy |
| Shadow rig | Namespace | Collection | Different isolation mechanism |
| Metadata | Network node | Custom props on Empty | Same schema |
| Bake | cmds.bakeResults | nla.bake + visual keying | Blender requires visual keying for accuracy |
| Undo | Single chunk | Single undo step | Equivalent |
| UI framework | PySide2 | bpy UI API | Different paradigms, same layout |
| Async | QThread | asyncio + timers | Blender-native async |
| Extensions/GPL | N/A | Must comply | Blender-specific constraint |
| NLA support | Anim layers | NLA strips | Blender more complex; test thoroughly |

---

## 12. Known Limitations & Future Work

### 12.1 Current Limitations (v0.3)

- Viewport capture (image overlay) not implemented [TBD].
- NLA blending during bake not yet supported (flattens to single action).
- No real-time preview streaming (batch results only).
- Geometry Nodes / shape key animation not supported.
- Linked library overrides: limited support (local override required).

### 12.2 Planned for v0.4+

- Real-time WebSocket preview to viewport (GPU drawing).
- Native NLA track support for non-destructive layering.
- Shape key / geometry nodes animation pipeline.
- Viewport ghost overlay of source video.
- Blender Extensions platform release (post-GPL review).

---

## 13. Approvals

| Role | Name | Date | Signature |
|---|---|---|---|
| dcc-integrator | | | |
| security-auditor | | | |
| core-architect | | | |
| QA Engineer | | | |

> ⚠️ This spec is DRAFT until Maya plugin v0.3 validates core integration patterns. Security-auditor sign-off required before implementation begins. Changes require re-approval.