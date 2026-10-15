# spec.md — AImation Actor (MVP working spec)

> SDD working spec: **only** numbered requirements with testable acceptance
> criteria. Nothing here restates the architecture, hierarchy, data model or FBX
> conventions — those live in [`AGENTS.md`](AGENTS.md) and
> [`docs/Plan_AImation_Actor_EN.md`](docs/Plan_AImation_Actor_EN.md). Where this
> file and the plan disagree on behavior, **the plan wins**.

Status: Draft · v0.3.2 · Scope: MVP only

## How to use (SDD)

- **Spec first, code second.** Any behavior/interface change updates this file in
  the *same change set* as the code.
- Every requirement has an ID and testable acceptance criteria; code must be
  traceable to one, and its tests reference that ID.
- Priority (MoSCoW): `Must` = MVP blocker · `Should` = gap acceptable ·
  `Could` = in-scope nice-to-have.
- **Status:** ✅ done · 🟡 partial · ⬜ open. Flip it in the same change that
  moves the requirement.
- Done = criteria pass (`pytest`, or *manual* when it needs Blender), docs in
  sync, `ruff`/`pytest` green. Open points go to §4, not guessed in code.

## 1. Scope

**In:** one reference video · manual key marking · per-frame pose extraction ·
skeleton-only sparse/stepped `.fbx` export · refine-and-reimport round trip ·
generative inbetweening · IK cleanup · final export.

**Out (MVP):** meshes/skinning · character retargeting · multi-actor · network ·
non-Windows · MDM/LAFAN1 engines · automatic key suggestion (see plan §7).

## 2. Functional requirements

### Capture — media, marking, extraction, preview

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| FR-CAP-01 | Must | ⬜ | Open a reference video (`.mp4`/`.mov`, H.264/ProRes). | Opens the file; corrupt input errors out and leaves the app usable. |
| FR-CAP-02 | Must | ⬜ | Video streams; never fully decoded into RAM. | No path reads all frames; peak RAM does not scale with clip length. |
| FR-CAP-03 | Must | ⬜ | Frame-accurate timeline (current/total frames; clip fps on state). | Position changes by ±1 per step; `fps` matches the clip (default 24). |
| FR-CAP-04 | Must | ⬜ | Shortcuts: `Space` play/pause, `←`/`→` ±1 frame, `K` mark, `Delete` remove, `Shift+←/→` jump between keys. | Each shortcut behaves as described, clamped to the frame range. |
| FR-CAP-05 | Must | ⬜ | `K` runs GVHMR on **only** that frame (batch 1) in a `QThread`, FP16, releasing CUDA cache after. | One frame inferred; UI stays responsive; cache does not grow across keys. |
| FR-CAP-06 | Must | ⬜ | Extracted pose is remapped to the production hierarchy (per AGENTS.md). | Result matches the documented skeleton naming/hierarchy. |
| FR-CAP-07 | Should | 🟡 | At most one key per frame; extraction failure is non-fatal. | Re-marking a frame does not duplicate; a failed `K` keeps prior keys and reports. |

### Blocking export

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| FR-EXP-01 | Must | ✅ | Write binary FBX with keys **only** at marked frames, stepped/constant tangents, skeleton only. | Keys for {15,42} exist exactly at 15 and 42; re-import shows Constant, no baked frames. |
| FR-EXP-02 | Must | ✅ | Follow the documented transforms & conventions (Main global, Pelvis height-only, quaternions, axes/time). | Matches AGENTS.md «Domain invariants»; round trip validates with `anim_offset = 0.0`. |

### Refined import

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| FR-IMP-01 | Must | ✅ | Import a Refined FBX; validate hierarchy (must include `Main`). | Hand-edited file loads; missing/renamed critical bone → clear error, no silent import. |
| FR-IMP-02 | Must | ✅ | Only keyed frames become snapshots; interpolation types ignored; each snapshot is a full pose. | Bézier/Linear inputs yield the same set as Constant. |
| FR-IMP-03 | Must | ✅ | Read via Blender subprocess only; never `import bpy` in-process. | No `bpy` in the app; a subprocess crash does not kill the app. |

### Generative inbetweening, IK & delivery

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| FR-GEN-01 | Must | ⬜ | Human keys are locked as hard constraints; only gaps are filled. | Output equals input at every human key (within tolerance); nothing outside the first/last key. |
| FR-GEN-02 | Must | ⬜ | Engine behind a Model Factory selectable from the GUI; MVP = CondMDI. | Swapping the engine needs no `core/` edits; CondMDI is the default. |
| FR-GEN-03 | Must | ⬜ | Generation runs in a `QThread`, batch 1, FP16, cache released; stays ≤ 10 GB VRAM. | Same constraints as FR-CAP-05; long spans complete on target hardware. |
| FR-IK-01 | Must | ⬜ | Detect planted feet in the original keys; IK pins contacts (no sliding/penetration) before final export. | Foot position stays constant across a contact span within tolerance. |
| FR-GEN-04 | Must | ⬜ | Export the approved final FBX (same conventions as blocking), preserving the frame range. | Output is a valid FBX; `frame_start`/`frame_end` match the import. |

## 3. Non-functional requirements

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| NFR-01 | Must | 🟡 | `core/` and `ports/` stay free of third-party imports. | Enforced by a test/lint check on import surfaces. |
| NFR-02 | Must | ⬜ | No blocking of the UI on AI/IO work. | No frozen window during extraction/generation. |
| NFR-03 | Must | 🟡 | Errors are explicit and actionable; state stays recoverable. | Failures report a message; no silent failures. |
| NFR-04 | Should | ✅ | Blender read path is manual-test-only (needs a Blender install). | Documented as manual; not required in CI. |

## 4. Open questions

1. VRAM pre-check (≥ 6 GB): hard block or warning?
2. Import behavior when Blender is not installed?
3. `fps` source: clip metadata, user setting, or project setting?
4. Re-marking an existing frame: overwrite or refuse? *(service layer: overwrite.)*
5. Project persistence (session file) or export-only? *(MVP assumption: export-only.)*
6. One reference video per session or a list? *(MVP: one.)*
7. `AIPort` method signatures for extraction and inbetweening.
8. Numeric threshold defining "no foot sliding".
9. *(Resolved 2026-10-15.)* "Offset calculation" in `core/services.py`:
   `build_production_pose` maps a raw `WorldPose` onto the production
   hierarchy — `Main` stays **clean** (`(0,0,0)`, identity rotation), because it
   is the animator's world control and the export ships "in place"; the captured
   horizontal displacement is deliberately **not** exported. `Pelvis` carries the
   hip **height** only, with local x/y pinned to `0`; every other joint carries
   rotation only. Translations are offsets from each joint's `rest_translation`,
   the convention the FBX writer adds back. This supersedes the plan's §5.B
   assignment of the AI scene displacement to `Main`.

## 5. Change log

| Version | Date       | Change                                                |
| ------- | ---------- | ----------------------------------------------------- |
| 0.1.0   | 2026-10-15 | Initial draft from the plan and AGENTS.md.            |
| 0.2.0   | 2026-10-15 | Synthesized: removed content duplicating AGENTS.md.   |
| 0.3.0   | 2026-10-15 | Added per-requirement status column and legend.       |
| 0.3.1   | 2026-10-15 | Core keyframe-management services landed (FR-CAP-07). |
| 0.3.2   | 2026-10-15 | Resume notes + open question on "offset calculation". |
| 0.3.3   | 2026-10-15 | "Offset calculation" landed: plan §5.B split, §4.9 resolved. |
| 0.3.4   | 2026-10-15 | `Main` reserved for the animator; blocking export ships in place. |

## 6. Session state (resume here)

**Done**

- Docs/SDD: `AGENTS.md` at repo root (engineering principles: SOLID, SDD, good
  practices) and this `spec.md` with per-requirement status.
- FBX I/O committed (`binary`, `document`, `transform`, `blender_import`,
  `fbx_adapter`) and hardened: object-type counts fixed, integer ranges
  validated, duplicate frames rejected.
- `core/services.py`: pure keyframe management (mark/remove/find/navigation/
  clamp) with tests. 46 tests green, `ruff check` clean.
- `core/services.py` offset calculation (M3 part 2): `WorldPose` +
  `build_production_pose` map a raw world pose onto the production hierarchy —
  `Main` stays clean (`(0,0,0)`, identity) for the animator and `Pelvis` takes
  the hip height as an offset from its bind (§4.9). 52 tests green,
  `ruff check` clean.

**Next**

1. **M4 (GUI)**: split view, video, timeline, shortcuts — the largest
   remaining pillar; `core/services.py` already provides its key logic.
2. Then M5 (`AIPort` + GVHMR) → M6 (CondMDI + Model Factory) → M7 (IK) → M8
   (wiring in `main.py`).

**Known follow-ups**

- `AIPort` is still an empty stub (§4.7).
- NFR-01 has no automated "no third-party imports" check yet (only a smoke test).
