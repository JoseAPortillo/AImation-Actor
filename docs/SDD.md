# Software Design Document (SDD) — AImation Actor v0.2

| Field | Value |
|---|---|
| **Project** | AImation Actor |
| **SDD Version** | 0.1 |
| **Date** | August 28, 2026 |
| **Architecture** | Modular Monolith |
| **Core Principles** | Clean Code + SpecSecDev |
| **Core Stack** | Python 3.11 / FastAPI / PyTorch |
| **UI Stack** | Tauri 2.x / React 18 / React Flow |

---

## 1. Introduction

### 1.1 Purpose
This document defines the technical architecture, code quality standards, and Security by Design (SpecSecDev) requirements for the development of AImation Actor. It serves as a technical contract between the ML team, DCC plugin developers, and frontend/desktop engineers.

### 1.2 SDD Scope
This document exclusively covers the **AI Core (Python)**, the **Desktop Application (Tauri)**, and the **Communication API**. Maya/Blender plugins are governed by specific integration documents but must comply with the contracts defined herein.

### 1.3 Guiding Principles
1.  **Modular Monolith:** A single deployment of the AI Core, internally divided into decoupled modules with explicit interfaces.
2.  **Clean Code:** Readability over cleverness. SOLID, DRY, KISS. Mandatory unit tests for business logic.
3.  **SpecSecDev:** Security is not a patch; it is derived directly from the functional specification. Every endpoint and node has threats modeled before implementation.

---

## 2. Modular Monolith Architecture

### 2.1 Justification
For a small/medium team and a local processing product, microservices add unnecessary operational complexity. A modular monolith enables:
- Simple deployment (single Python process).
- Safe refactoring thanks to clear module boundaries.
- Future extraction of modules into independent services if scaling requires it.

### 2.2 Core Module Map

```text
aimation_actor_core/
├── api/                # Presentation layer (FastAPI routers)
│   ├── jobs.py         # /jobs/* endpoints
│   ├── sessions.py     # /sessions/* endpoints
│   ├── nodes.py        # /nodes/* endpoints
│   └── health.py       # Healthcheck and metrics
├── domain/             # Pure business logic (framework-free)
│   ├── animation/      # Entities: Pose, Frame, Skeleton, Motion
│   ├── pipeline/       # Node graph orchestrator
│   └── retargeting/    # Mapping and conversion logic
├── infrastructure/     # External adapters
│   ├── ai_models/      # PyTorch/ONNX wrappers
│   ├── video/          # ffmpeg/OpenCV adapters
│   ├── storage/        # JSON/BVH/FBX read/write
│   └── dcc_bridge/     # WebSocket session management
├── shared/             # Cross-cutting utilities
│   ├── config.py       # Typed configuration (Pydantic Settings)
│   ├── logging.py      # Structured logging
│   └── errors.py       # Domain exception hierarchy
└── main.py             # Entry point and composition root
```

### 2.3 Module Dependency Rules

| Module | Can Import | CANNOT Import |
|---|---|---|
| `api/` | `domain/`, `shared/` | `infrastructure/` directly |
| `domain/` | `shared/` | `api/`, `infrastructure/` |
| `infrastructure/` | `domain/`, `shared/` | `api/` |
| `shared/` | Nothing internal | Everything |

> **Golden Rule:** The `domain/` layer is pure Python with no heavy external dependencies. All interaction with AI models, files, or network goes through interfaces defined in `domain/` and implemented in `infrastructure/`.

### 2.4 Dependency Injection
A lightweight DI container (e.g., `dependency-injector` or FastAPI Depends) is used to assemble modules in `main.py`. No module creates concrete infrastructure instances internally.

---

## 3. Clean Code Standards

### 3.1 Python Conventions
- **Strict Typing:** All parameters and return values typed. `mypy --strict` in CI.
- **Docstrings:** Google Style. Mandatory for public functions and domain classes.
- **Naming:** 
  - Classes: `PascalCase` (`PoseEstimator`, `GraphNode`)
  - Functions/variables: `snake_case` (`estimate_pose`, `frame_count`)
  - Constants: `UPPER_SNAKE_CASE`
  - Interfaces/Protocols: Prefix `I` or suffix `Protocol` (`IPoseEstimator`, `RetargetingProtocol`)
- **Length:** Functions < 30 lines. Files < 300 lines. If exceeded, split.

### 3.2 Applied SOLID Principles

| Principle | Application in AImation Actor |
|---|---|
| **SRP** | Each graph node is a class with a single responsibility. `FootLockNode` only locks feet; it does not smooth or detect contacts. |
| **OCP** | New nodes are added by registering them in the catalog, without modifying the graph orchestrator. |
| **LSP** | Any implementation of `IPoseEstimator` must be interchangeable without breaking the pipeline. |
| **ISP** | Granular interfaces: `ICleanup`, `IFootContact`, `ISmooth` instead of a giant `IMotionProcessor`. |
| **DIP** | The orchestrator depends on `INodeExecutor`, not `PyTorchNodeExecutor`. |

### 3.3 Testing
- **Minimum Coverage:** 90% in `domain/`, 70% in `infrastructure/`, 60% in `api/`.
- **Unit Tests:** No network, no GPU, no real files. Mocks for infrastructure.
- **Integration Tests:** Validate complete flows with small video/pose fixtures.
- **Property-based Testing:** For animation math logic (hypothesis).

### 3.4 Living Documentation
- Auto-generated OpenAPI from FastAPI.
- Node catalog auto-generated from Pydantic schemas.
- Architectural decisions recorded in `/docs/adr/`.

---

## 4. Security by Design (SpecSecDev)

### 4.1 Methodology
SpecSecDev integrates security into the functional specification. For each feature, the following is defined:
1.  **Functional Specification** (what it does).
2.  **Threat Model** (what can go wrong).
3.  **Security Controls** (how it is mitigated).
4.  **Verification** (how to prove the control works).

### 4.2 Primary Threat Model

| Asset | Threat | Severity | SpecSecDev Control | Verification |
|---|---|---|---|---|
| Local API | Unauthorized access from another machine | High | Exclusive bind to `127.0.0.1`. Per-instance session token. | Connection test from external IP fails. |
| Video/Input | Path traversal / malicious file | High | Strict extension + size validation. Read sandboxing. Path canonicalization. | Path fuzzing with `../`, symlinks, etc. |
| Node Graph | Arbitrary code execution | Critical | Allowlist of permitted nodes. No `eval/exec`. Sandboxing for future custom nodes. | Attempt to inject unregistered node returns 403 error. |
| DCC Sessions | Session hijacking | Medium | Ephemeral token + nonce per request. Inactivity timeout. | Replay attack test fails. |
| AI Models | Model poisoning / trojan weights | Medium | SHA256 checksum verified on load. Optional signing. Load only from trusted directory. | Altered weight file → rejection at startup. |
| Animation Data | Proprietary content leakage | Medium | 100% local processing. No content telemetry. Sanitized logs. | Log audit: zero pose/video data. |

### 4.3 Mandatory Cross-Cutting Controls

#### Authentication and Authorization
- **Instance Token:** Randomly generated when starting the Core. Plugins/Tauri obtain it via secure local file or environment variable. Never hardcoded.
- **Restrictive CORS:** Only origins `tauri://localhost` and `http://localhost:*`.
- **Rate Limiting:** Maximum 10 requests/second per session to prevent local DoS.

#### Input Validation
- **Pydantic v2 strict mode:** All payloads validated before reaching business logic.
- **Path Sanitization:** Exclusive use of `pathlib.Path.resolve()` + allowed prefix verification.
- **Size Limits:** Video max 2GB. JSON max 50MB. Graphs max 500 nodes.

#### Cryptography and Sensitive Data
- **No Secrets in Code:** Tokens and keys via env vars or local secret manager.
- **Hashing:** SHA256 for file integrity. bcrypt/argon2 if future credentials are stored.
- **Logs:** Never log full user paths, video content, or poses. Use opaque IDs.

#### Node Security
- **Static Registration:** Nodes are registered at import time, not dynamically from input.
- **Connection Validation:** The orchestrator verifies data types between nodes BEFORE execution.
- **Per-Node Timeout:** Each node has a configurable timeout. If exceeded, it cancels gracefully.
- **Future Isolation:** Prepare interface to run custom nodes in isolated subprocess/container.

### 4.4 SpecSecDev Checklist per Feature

Before merging any PR that adds/modifies functionality:

- [ ] Was the threat model updated?
- [ ] Is there input validation with Pydantic strict?
- [ ] Was the malicious edge case tested (negative test)?
- [ ] Are logs sanitized?
- [ ] Are there no hardcoded secrets?
- [ ] Is the instance token validated in the new endpoint?
- [ ] Was the security control documented in the corresponding ADR?

---

## 5. Interface Contracts

### 5.1 Node Contract
Every node must implement:

```python
class INode(Protocol):
    @staticmethod
    def get_schema() -> NodeSchema: ...
    
    async def execute(
        self, 
        inputs: dict[str, Any], 
        params: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]: ...
    
    async def validate(self, params: dict[str, Any]) -> ValidationResult: ...
```

### 5.2 DCC Session Contract
```json
{
  "session_id": "uuid-v4",
  "dcc_type": "maya|blender",
  "dcc_version": "2025.0",
  "plugin_version": "0.3.1",
  "registered_at": "ISO8601",
  "last_heartbeat": "ISO8601",
  "capabilities": ["shadow_rig", "bake", "viewport_capture"]
}
```

### 5.3 Neutral Animation Format
Defined in Pydantic schema `NeutralMotion`. It is the immutable contract between Core, Tauri, and Plugins. Any change requires versioned migration.

---

## 6. Deployment and Operations Strategy

### 6.1 Packaging
- **AI Core:** Distributed as an installable Python package (`pip install aimation-actor-core`) or bundled with PyInstaller/Nuitka for users without Python.
- **Tauri App:** Native installer (.msi/.dmg/.deb) that includes the Core embedded or downloads it on first launch.
- **DCC Plugins:** Independent packages requiring Core URL + token.

### 6.2 Observability
- **Structured Logs:** JSON Lines with fields: `timestamp`, `level`, `module`, `trace_id`, `session_id`, `message`.
- **Metrics:** Prometheus-compatible at `/metrics`. Per-node latency, throughput, errors, GPU usage.
- **Health:** `/health` returns loaded model status, available GPU, active sessions.

### 6.3 Updates
- **Tauri Updater:** Automatic desktop app updates.
- **Core:** Independently updatable. Strict semantic versioning.
- **Compatibility:** Plugins must declare supported Core version range. Negotiation during session handshake.

---

## 7. Technical Risks and SDD Mitigations

| Risk | Impact | Architectural Mitigation |
|---|---|---|
| Coupling between modules | Costly refactoring | Dependency rules + architectural linter (import-linter) |
| Regressions in animation logic | Inconsistent quality | Property-based tests + animation golden files |
| Vulnerability in custom node | Local compromise | Sandboxing + allowlist + SpecSecDev checklist |
| Memory leak in long processing | Core crash | Context managers + memory monitoring + graceful degradation |
| DCC incompatibility after update | Broken plugin | Session contract versioning + capability negotiation |

---

## 8. Approvals and Changes

| Role | Name | Date | Signature |
|---|---|---|---|
| Tech Lead | | | |
| Security Champion | | | |
| Product Owner | | | |
| ML Engineer Lead | | | |

> **Note:** This SDD is a living document. Significant architectural changes require a linked ADR (Architecture Decision Record). Security updates require Security Champion review.