# Design: In-Between Generation and Enrichment (§12.5)

## Technical Approach

New `inbetween-generation` ENRICHMENT node after `temporal-cleanup`. Pure-stdlib math in `domain/animation/inbetween.py` (`InbetweenParams`, `enrich_motion`) runs a deterministic, stateless chain: resample (Hermite/linear upsample, eased timing) → rotation filter (quaternion sign canonicalization + shortest-arc slerp) → tangent smoothing (centered box). `InbetweenGenerationNode` mirrors `TemporalCleanupNode` (dict coercion, `asyncio.to_thread`, validation). Registry gains 9th seed; `NodeCategory` additive `ENRICHMENT`.

## Architecture Decisions

| Decision | Options | Tradeoff | Decision |
|---|---|---|---|
| Math location | domain vs infra | AGENTS.md §3.1 forbids it; proposal's numpy REJECTED (spec settled) | `domain/animation/inbetween.py`, `math` only |
| Rotation interp | slerp vs Hermite-eulers | Rotations are quaternions; eulers unavailable; slerp keeps norm and exact keys | slerp, nlerp fallback near-antipodal |
| Easing placement | post-pass vs fused timing | Post-pass destroys tangents; easing is a timing remap | `u=ease(ξ)` inside resample |
| Smoothing | box vs one-euro | Box window 1 = identity; variance non-increasing; monotonic in intensity | Centered box, `w=1+round(intensity*9)` |
| Category | reuse vs new | Spec mandates `ENRICHMENT`; triggers §3.2 soft constraint + TS sync | New `ENRICHMENT` member |
| contacts/keyposes | remap vs passthrough | Spec: MVP untouched; refs stale after upsample | Pass-through; remap deferred |

## Data Flow

```
resample+ease → rotation filter → tangent smooth
grid t_i=i/fps_target; n_out=int(duration*fps_target)+1
keys exact; passthrough when fps_target<=fps or 1 frame; meta updated; invariants last
```

## File Changes

| File | Action | Description |
|---|---|---|
| `aimation_actor_core/domain/animation/inbetween.py` | Create | Pure-stdlib math: params, easing, Hermite, slerp, box, `enrich_motion` |
| `aimation_actor_core/infrastructure/ai_models/inbetween_generation.py` | Create | `InbetweenGenerationNode` adapter |
| `aimation_actor_core/infrastructure/virtual/node_registry.py` | Modify | Register 9th seed; docstring 8→9 |
| `aimation_actor_core/domain/pipeline/schema.py` | Modify | Add `ENRICHMENT` member |
| `aimation_actor_core/domain/animation/__init__.py` | Modify | Re-exports |
| `aimation_actor_core/infrastructure/ai_models/__init__.py` | Modify | Re-exports |
| `frontend/src/api/types.ts` | Modify | `NodeCategory` += `"enrichment"` (contract) |
| `frontend/src/core/handles.ts` | Modify | `CATEGORY_COLORS` += enrichment |
| `frontend/src/components/palette/Palette.tsx` | Modify | `CATEGORY_LABEL` + order insertion |
| `frontend/src/test/fixtures/nodeCatalog.json` | Modify | Add node entry (fixture) |
| `tests/domain/test_inbetween.py` | Create | Unit tests per stage |
| `tests/infrastructure/test_inbetween_generation.py` | Create | Schema/execute/validate |
| `tests/infrastructure/test_inbetween_generation_registry.py` | Create | 9th-seed citizen test |
| `test_executor.py`, `test_temporal_cleanup_registry.py`, `test_api.py` | Modify | Seed counts 8 → 9 |

## Interfaces / Contracts

```python
@dataclass(frozen=True)
class InbetweenParams:
    interpolation_method: str = "cubic"   # "linear" | "cubic"
    target_fps: float = 30.0              # > 0
    easing: str = "none"                  # "none" | "ease-in" | "ease-out" | "ease-in-out"
    euler_filter: bool = True
    tangent_smoothing: float = 0.0        # [0, 1]
    def __post_init__(self) -> None: ...  # ValueError on invalid enum/range/fps

def enrich_motion(motion: NeutralMotion, params: InbetweenParams | None = None) -> NeutralMotion
def _resample(motion, target_fps, method, easing) -> NeutralMotion   # upsample only
def _apply_rotation_filter(motion, enabled) -> NeutralMotion         # no-op when disabled
def _apply_tangent_smooth(motion, intensity) -> NeutralMotion        # identity at 0
```

- **Hermite** (~50 lines): basis `h00=2u³-3u²+1, h10=u³-2u²+u, h01=-2u³+3u², h11=u³-u²`; Catmull-Rom tangents `m_i=(p_{i+1}-p_{i-1})/2`, one-sided ends.
- **Easing** (monotonic, f(0)=0, f(1)=1): ease-in `t²`; ease-out `1-(1-t)²`; ease-in-out `3t²-2t³`.
- **Rotation filter**: per-joint running sign (`dot<0 → flip`) over resampled sequence; slerp flips far endpoint (short arc); `|dot|>1-1e-6` or `sinθ<1e-6` → nlerp (no NaN).
- **Tangent smoothing**: centered box per translation axis, window `1+round(intensity*9)` clamped; identity at 0. Rotations untouched (norm-drift risk; deferred).

Semantics: upsample only (`fps_target<=meta.fps` or 1 frame → passthrough); frames `1..n_out`, `time=frame/fps_target` (producer convention); new frames `confidence=None`; `tracking`/`contacts`/`keyposes` unchanged; `meta.fps`/`duration_frames` updated; invariants validated last.

Node adapter: `type="inbetween-generation"`, `category=ENRICHMENT`; `execute` = `_coerce_motion` → `asyncio.to_thread`; `validate` = enums, `tangent_smoothing∈[0,1]`, `target_fps>0`, reject `bool` numerics.

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit | Resample: exact keys, first/last, C1 vs C0, 30→60 (3→5), passthroughs, meta | Synthetic motion; finite differences |
| Unit | Easing speed asymmetry (halves; in-out midpoint peak) | Constant-velocity input; segment speeds |
| Unit | Rotation filter: flips removed, short arc, disabled, near-antipodal | Alternating `q`/`-q` sources |
| Unit | Smoothing: identity at 0, variance non-increasing a<b | Jittered trajectory; per-axis variance |
| Unit | Order + determinism + invariants | Stage spies; run-twice compare |
| Unit | Params: invalid rejected, defaults valid | Dataclass + node validate |
| Infra | Schema/execute/validate, coercion, to_thread | Mirror test_temporal_cleanup.py |
| Infra | Registry 9 seeds, ENRICHMENT, ports | New registry test; count updates |

## Threat Matrix

N/A — no routing/shell/subprocess/VCS/PR/executable/process boundary; no IO; params validated.
⚠️ **§3.2**: threat-model entry + Champion sign-off before archive.

## Migration / Rollout

No migration. Additive and bypassable; graphs without it unaffected. TS sync ships with the change (Sub_Agents.md §4.3); contract tests confirm no drift.

## Open Questions / Risks

- [ ] **Euler vs quaternions**: MVP = canonicalization; Euler/gimbal-lock deferred.
- [ ] **contacts/keyposes** stale, **tracking** length mismatch (pass-through, MVP).
- [ ] **Performance**: 60fps doubles frames; profile early; `to_thread` offloads.