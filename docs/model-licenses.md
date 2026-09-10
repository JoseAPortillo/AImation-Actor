# Model Licenses & Integrity Policy

**Status:** decision — mitigation for **Risk 4: Model and Dataset Licenses**
(`docs/Plan_AImation_Actor_EXT.md`, §Risk 4). Supersedes ad-hoc model pickups:
every model artifact shipped or planned must appear either here or in
`models/manifest.json` with its license recorded.

## Decision

The product is intended for **commercial** use. Only models whose licenses
permit commercial distribution, modification, and redistribution may land in
the catalog; research-only or otherwise restricted weights are excluded.

## License table

| Model | Kind | License | Commercial use | Decision |
|---|---|---|---|---|
| RTMPose-S (`rtmpose-light`) | pose-2d | Apache-2.0 | ✅ Yes | **Use** — catalog entry `rtmpose-light` (ONNX, COCO 17 keypoints) |
| MediaPipe Pose | pose-2d | Apache-2.0 | ✅ Yes | Alternative pose-2d backend (TFLite/ONNX export) if RTMPose underperforms |
| MotionBERT | pose-3d | Apache-2.0 | ✅ Yes | **Use** — catalog entry `motionbert`; ONNX export pending, backend lands in a follow-up change |
| VideoPose3D | pose-3d | Research-only (non-commercial) | ❌ No | **Do not use** — excluded despite being common in academic pipelines |
| SMPL / SMPL-X | body model | Restricted (custom SMPL license, redistribution restrictions) | ⚠️ Review | Only after legal review of the specific license terms; not required for the neutral-skeleton pipeline |

Notes:

- Apache-2.0 (RTMPose, MediaPipe, MotionBERT) is permissive and
  commercially safe. VideoPose3D's research-only grant is a hard blocker for a
  commercial product (Risk 4).
- SMPL-family licenses restrict redistribution and commercial usage; the
  neutral skeleton pipeline does **not** depend on them, so no approval is
  needed for the current scope.

## Integrity policy (SpecSecDev, SDD §4.2)

Downloaded model bytes are **untrusted input** (SDD §4 threat "Model
integrity"). The provisioner (`aimation_actor_core/infrastructure/models/`)
enforces:

- **sha256 in the manifest** — every catalog entry records the expected
  digest. `install()` verifies the digest against the downloaded payload
  *before* the file is named; a mismatch leaves no residue.
- **Explicit TOFU** — entries without a recorded hash (e.g. pending upstream
  verification) require an explicit `--trust-on-first-use` flag. The observed
  hash is written back into `manifest.json`, upgrading the entry on next use.
- **No execution** — downloaded content is never evaluated, loaded, or run:
  the provisioner only hashes the bytes and atomically `os.replace()`s them
  into the models root. No `eval`/`exec`/`pickle` anywhere in the model path.
- **License gate before network** — `install` rejects a wrong license before
  any request is sent.

Verification surface: `aimation-models list` (status column),
`aimation-models verify <name>` (exit 1 on missing/corrupt).