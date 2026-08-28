# Maya Integration Specification — AImation Actor

| Field | Value |
|---|---|
| **Document Type** | DCC Integration Spec |
| **Target DCC** | Autodesk Maya 2024+ |
| **Version** | 0.1 |
| **Date** | 2026-08-28 |
| **Depends On** | SDD v0.1 §5.2, §16; Sub-Agent Directives §4.4 |
| **Owner** | `dcc-integrator` sub-agent |

---

## 1. Overview

This document defines the complete technical specification for the AImation Actor Maya plugin. It serves as the authoritative reference for implementation, testing, and security review of all Maya-specific functionality.

The plugin is a **lightweight client** that communicates with the external AI Core via HTTP/WebSocket. It performs NO AI processing locally. Its responsibilities are limited to: UI presentation, viewport data capture, shadow rig creation, animation baking, and session management.

---

## 2. Architecture & Module Structure

### 2.1 Plugin Directory Layout

```text
aimation_actor_maya/
├── __init__.py              # Plugin entry point, registration
├── core/
│   ├── session.py           # Session registration, heartbeat, token mgmt
│   ├── api_client.py        # HTTP/WS client to AI Core
│   └── config.py            # Plugin settings, Core URL, preferences
├── ui/
│   ├── main_panel.py        # Main dockable panel (PySide2)
│   ├── node_launcher.py     # "Open AImation Flow" button logic
│   └── widgets/             # Reusable UI components
├── capture/
│   ├── pose_capture.py      # Capture selected controls/joints transforms
│   ├── keyframe_sampler.py  # Extract keyframes from timeline
│   └── viewport_capture.py  # Viewport screenshot/overlay (future)
├── rig/
│   ├── shadow_rig_builder.py # Create/manage shadow rig
│   ├── baker.py             # Animation baking with keyframe preservation
│   └── retarget_applier.py  # Apply neutral motion to target rig
├── utils/
│   ├── namespace_mgr.py     # Namespace isolation utilities
│   ├── undo_decorator.py    # Undo chunk wrappers
│   └── logger.py            # Sanitized logging (SpecSecDev compliant)
└── resources/
    ├── icons/               # UI icons
    └── presets/             # Bundled retarget YAML presets
```

### 2.2 Dependency Rules (Maya-Specific)

| Module | Allowed Imports | Forbidden Imports |
|---|---|---|
| `core/` | `maya.cmds`, `maya.api.OpenMaya`, stdlib, `requests/websockets` | `numpy`, `torch`, `ui/`, `rig/` |
| `ui/` | `maya.cmds`, `PySide2`, `core/` | `rig/`, `capture/` directly (use signals/callbacks) |
| `capture/` | `maya.cmds`, `maya.api.OpenMaya`, `domain` entities (via JSON) | `ui/`, `rig/`, external ML libs |
| `rig/` | `maya.cmds`, `maya.api.OpenMaya`, `core/` (for result fetch) | `ui/`, `capture/`, external ML libs |
| `utils/` | `maya.cmds`, stdlib only | Everything else |

> ⚠️ **CRITICAL:** No heavy dependencies (`numpy`, `torch`, `opencv`) are allowed anywhere in the plugin. All math uses Maya API or stdlib. Neutral motion data arrives as JSON and is applied via `cmds.setAttr` / OpenMaya.

---

## 3. Session Management

### 3.1 Session Lifecycle

```text
Plugin Load → Auto-register session → Heartbeat loop (5s) → 
Core ACK → Session Active → [Work] → 
Plugin Unload / Timeout → Deregister
```

### 3.2 Registration Payload

```python
{
    "session_id": "uuid-v4",  # Generated per Maya session
    "dcc_type": "maya",
    "dcc_version": "2025.0",  # cmds.about(version=True)
    "plugin_version": "0.3.1",
    "registered_at": "ISO8601",
    "capabilities": ["shadow_rig", "bake", "viewport_capture", "keyframe_capture"],
    "scene_name": "shot_010_anim.ma",  # Sanitized basename only
    "token": "<instance-token>",  # Read from secure local file / env var
}
```

### 3.3 Token Handling (SpecSecDev)

- Token is NEVER stored in Maya optionsVar, scriptNode, or scene file.
- Token is read at startup from: `%APPDATA%/AImationActor/token.txt` (Windows) or `~/.config/AImationActor/token` (Linux/Mac).
- If token missing/invalid → UI shows "Connect to AImation Flow" prompt. Never auto-generate.
- Token is passed in `Authorization: Bearer <token>` header on ALL requests.
- On 401/403 → invalidate session, prompt re-auth. Never retry with same token.

### 3.4 Heartbeat & Reconnection

- Heartbeat interval: 5 seconds.
- Missed 3 heartbeats → mark session stale, attempt reconnect.
- Reconnect uses exponential backoff: 1s → 2s → 4s → 8s → max 30s.
- On reconnect success → re-register with SAME session_id (Core resumes state).
- On permanent failure (>5 min) → UI shows offline indicator, queue pending jobs.

---

## 4. Viewport Data Capture

### 4.1 Pose Capture

Captures world-space transforms of selected controls/joints at current frame.

```python
def capture_selected_poses() -> dict[str, TransformData]:
    """
    Returns: {"control_name": {"translation": [x,y,z], "rotation_quat": [w,x,y,z], "scale": [x,y,z]}}
    Uses: OpenMaya.MFnTransform for accuracy (not cmds.xform)
    Respects: Selection sets, namespaces, referenced rigs
    Skips: Hidden nodes, locked attributes (with warning)
    """
```

**Constraints:**
- Only captures DAG nodes with `transform` type.
- Rotation ALWAYS exported as quaternion (no Euler ambiguity).
- Scale captured but optional (default [1,1,1] if uniform).
- Captured data serialized to Neutral Motion JSON format before sending.

### 4.2 Keyframe Sampler

Extracts keyframes from selected objects within frame range.

```python
def sample_keyframes(
    objects: list[str], start_frame: int, end_frame: int, preserve_keyposes: bool = True
) -> list[KeyframeData]:
    """
    Returns list of {frame, weight, poses} for blocking-to-motion.
    If preserve_keyposes=True, marks sampled frames with weight=1.0.
    Uses: MAnimControl.findKeys() for accurate key detection.
    """
```

**Constraints:**
- Respects animation layers (samples from base + enabled layers).
- Handles both keyed and constrained attributes.
- Frame range validated: start <= end, within playback range.
- Large ranges (>1000 frames) trigger confirmation dialog.

---

## 5. Shadow Rig System

### 5.1 Naming & Namespace Convention

All shadow rig elements live under namespace `ai_shadow`:

```text
ai_shadow:root
ai_shadow:Hips
ai_shadow:Spine
...
ai_shadow:metadata_node   # Stores graph_hash, source, confidence
```

### 5.2 Shadow Rig Builder

```python
class ShadowRigBuilder:
    def create(self, neutral_motion: NeutralMotion, target_rig: str | None = None) -> str:
        """
        Creates shadow rig joints matching neutral skeleton hierarchy.
        Applies animation from neutral_motion frames.
        Attaches metadata node with traceability info.
        Returns: root joint name

        NON-DESTRUCTIVE: Does not modify existing scene hierarchy.
        REVERSIBLE: delete_shadow_rig() fully cleans up.
        """

    def delete(self, root_joint: str) -> None:
        """Complete cleanup: joints, constraints, metadata, namespace."""

    def transfer_to_controls(self, shadow_root: str, control_map: dict[str, str]) -> None:
        """Copies animation from shadow joints to target controls via constraint bake."""
```

### 5.3 Metadata Node

Custom network node storing:

| Attribute | Type | Description |
|---|---|---|
| `graph_hash` | string | SHA256 of generating .aimgraph |
| `source_type` | enum | video / blocking / rough |
| `model_version` | string | AI model version used |
| `confidence_avg` | float | Average tracking confidence |
| `created_at` | string | ISO8601 timestamp |
| `keypose_frames` | int[] | Frames marked as preserved keyposes |
| `core_session_id` | string | Session that generated this |

### 5.4 Non-Destructive Guarantees

- ✅ Shadow rig exists ONLY under `ai_shadow:` namespace.
- ✅ No connections to existing rig unless explicit transfer requested.
- ✅ Delete operation removes ALL traces (verified via `ls` post-delete).
- ✅ Undo supported: entire creation wrapped in single undo chunk.
- ✅ Multiple shadow rigs coexist (unique namespace suffix: `ai_shadow_001:`).

---

## 6. Animation Baking

### 6.1 Bake Operation

```python
def bake_animation(
    targets: list[str],
    frame_range: tuple[int, int],
    preserve_keyposes: bool = True,
    smart_euler_filter: bool = True,
    sample_rate: float = 1.0,
) -> BakeResult:
    """
    Bakes animation to target controls/joints.
    If preserve_keyposes=True, original keys at those frames are KEPT (not overwritten).
    Smart euler filter applied post-bake to prevent gimbal flips.
    Wrapped in undo chunk.
    """
```

### 6.2 Keyframe Preservation Logic

When `preserve_keyposes=True`:
1. Identify frames marked as keyposes in metadata.
2. Pre-bake: store original values at those frames.
3. Bake normally across full range.
4. Post-bake: restore original values at keypose frames.
5. Blend adjacent keys to avoid discontinuities (tangent smoothing).

### 6.3 Safety Checks Before Bake

- ⚠️ Confirm if targets have existing animation (warn + option to backup).
- ⚠️ Validate frame range is within scene limits.
- ⚠️ Check for locked/plugged attributes (skip with warning log).
- ⚠️ Verify shadow rig metadata exists and is valid.
- ❌ Abort if token/session invalid (re-auth required).

---

## 7. User Interface

### 7.1 Panel Layout

Dockable panel registered via `workspaceControl`. Sections:

| Section | Controls | Notes |
|---|---|---|
| **Connection Status** | Indicator dot, session ID, "Reconnect" button | Green=active, Yellow=reconnecting, Red=offline |
| **Source** | Video file browser, frame range slider, preset dropdown | File dialog filtered: mp4/mov/avi |
| **Generate** | "From Video", "From Blocking", "Regenerate Range" buttons | Disabled when offline |
| **Cleanup** | Smooth slider (0-1), Foot Lock toggle, Root Stabilize toggle | Sends params to Core |
| **Output** | "Create Shadow Rig", "Bake to Controls", "Export BVH" | Context-sensitive enable/disable |
| **Advanced** | "Open AImation Flow" button, "Show Logs", "Preferences" | Launches Tauri app via subprocess |

### 7.2 UI Thread Safety

- ALL Maya API calls happen on main thread.
- Network requests run in QThread / asyncio worker.
- Results posted back via `maya.utils.executeInMainThreadWithResult`.
- Progress bar updated via timer callback (never blocking UI).
- Cancel button sets flag checked by worker loop.

### 7.3 Localization & Accessibility

- All labels support Maya's language switching (English default).
- Tooltips on every control explaining function + SpecSecDev note where relevant.
- Keyboard shortcuts registered via `hotkey` command.
- High-DPI aware (PySide2 scaling).

---

## 8. Security Controls (SpecSecDev for Maya)

### 8.1 Threat Model Entries

| Asset | Threat | Control | Verification |
|---|---|---|---|
| Session Token | Extraction from scene/memory | Never stored in scene/optionsVar. Memory cleared after use. | Grep codebase + memory dump test |
| Received Animation | Malicious attribute injection | Whitelist allowed attributes. Validate types/ranges before setAttr. | Fuzz test with malformed JSON |
| Video Path | Path traversal | Canonicalize + validate prefix. No `..` or symlinks. | Path fuzzing suite |
| Shadow Rig Namespace | Namespace collision/hijack | Unique suffix generation. Validate namespace doesn't exist pre-create. | Collision stress test |
| Bake Operation | Accidental data loss | Mandatory backup prompt. Undo chunk. Keyframe preservation. | User acceptance test + undo verification |
| Logs | Scene/content leakage | Sanitize all paths/names. No pose values logged. | Log audit script |

### 8.2 Mandatory Pre-Merge Checklist (Maya Plugin)

- [ ] No heavy dependencies imported (numpy/torch/cv2)?
- [ ] Token never touches scene file or optionsVar?
- [ ] All setAttr calls validate input type/range?
- [ ] Shadow rig creation/deletion fully reversible + undoable?
- [ ] Keyframe preservation tested with edge cases?
- [ ] UI thread safety verified (no blocking calls)?
- [ ] Logs sanitized (no paths/poses/video content)?
- [ ] Tested on Maya 2024 + 2025 minimum?
- [ ] Session reconnection handles timeout gracefully?
- [ ] Security-auditor sign-off obtained?

---

## 9. Testing Strategy

### 9.1 Test Categories

| Category | Scope | Tools | Coverage Target |
|---|---|---|---|
| Unit | Utils, serializers, validators | pytest + maya-mock | 90% |
| Integration | Session flow, capture→bake pipeline | pytest + headless Maya | 70% |
| UI | Panel interactions, thread safety | pytest-qt + maya standalone | 60% |
| Security | Token handling, input validation, sanitization | Custom fuzzers + manual audit | 100% of checklist |
| Compatibility | Maya 2024, 2025, 2026 beta | CI matrix | Pass/Fail |

### 9.2 Golden Files

- Reference shadow rig scenes (.ma) for regression testing.
- Expected bake outputs for standard test motions.
- Regenerated ONLY via approved script in CI. Manual regeneration forbidden.

### 9.3 Headless Testing

All integration tests run in `mayapy` headless mode. No GUI required. Viewport capture tests skipped in headless (marked xfail with ticket).

---

## 10. Deployment & Installation

### 10.1 Installation Methods

| Method | Command | Notes |
|---|---|---|
| pip (recommended) | `pip install aimation-actor-maya` | Installs to site-packages, auto-registers |
| Manual | Copy to `MAYA_MODULE_PATH` + drag .mod file | For air-gapped studios |
| Studio Deploy | SCCM/Munki package | Includes token provisioning script |

### 10.2 Module File (.mod)

```text
+ aimation_actor_maya 0.3.1 /path/to/aimation_actor_maya
plug-ins: plug-ins
scripts: scripts
icons: resources/icons
```

### 10.3 First-Time Setup

On first load, if no token found:
1. Show setup wizard dialog.
2. Prompt user to launch AImation Flow (or provide path).
3. Auto-detect running Core instance via localhost scan.
4. Retrieve token via secure handshake.
5. Save token to OS-appropriate secure location.
6. Register session.

---

## 11. Known Limitations & Future Work

### 11.1 Current Limitations (v0.3)

- Viewport capture (image overlay) not implemented.
- Animation layer blending not yet supported (bakes to base layer only).
- HumanIK retarget requires manual mapping setup.
- No real-time preview streaming (batch results only).
- Undo limit: shadow rig creation is one undo step; individual joint edits are not separately undoable.

### 11.2 Planned for v0.4+

- Real-time WebSocket preview streaming to viewport.
- Native animation layer support for non-destructive blending.
- Auto-HumanIK mapping from neutral skeleton.
- Viewport ghost overlay of source video.
- Per-joint undo within shadow rig.

---

## 12. Approvals

| Role | Name | Date | Signature |
|---|---|---|---|
| dcc-integrator | | | |
| security-auditor | | | |
| core-architect | | | |
| QA Engineer | | | |

> ⚠️ This spec MUST be approved by security-auditor before any implementation begins. Changes require re-approval.