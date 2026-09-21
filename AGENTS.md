# Code Review Rules

## Python
- Type annotations on every public function and method; mypy `strict = true` must pass.
- Keep functions small and single-purpose; no dead code, no unused imports.
- Prefer typing.Protocol for extension points; concrete classes stay behind dependency injection.
- No `# type: ignore` without a documented reason (error code must be covered).

## Architecture (aimation_actor_core)
- Layered: `api/` must never import `infrastructure/` directly; `domain/` stays pure (no torch, numpy, or third-party AI deps); `infrastructure/` never imports `api/`; `shared/` imports nothing internal. See `[tool.importlinter]` in pyproject.toml.
- Model runtimes run in cache-local child processes (`tools/*_helper.py`); `infrastructure/ai_models` backends communicate via bounded subprocess JSON.
- Every AI backend keeps its safety net: the authored-fidelity gate and procedural fallback.

## Tests
- Functional, deterministic tests in `tests/` mirroring the package layout.
- No tests depending on network, model downloads, or local GPU.

## Git
- Conventional Commits only: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
- Work-unit commits: commit behavior with its tests and docs in the same unit.
- Never add AI attribution lines (no `Co-Authored-By`).

## UI copy and comments
- English by default for code comments, UI labels, and documentation.