# Tasks: 2D Pose Estimation (pose-2d)

## Task 1: Domain value objects (Keypoints2D)

**Description**: Crear los value objects puros en domain que representan keypoints 2D normalizados.

**Files**:
- `aimation_actor_core/domain/animation/keypoints.py` (nuevo)
- `aimation_actor_core/domain/animation/__init__.py` (actualizar exports)

**Requirements**:
- `Keypoint`: label (str), x (float 0-1), y (float 0-1), confidence (float 0-1)
- `Keypoints2D`: frame_index (int), keypoints (list[Keypoint])
- Ambos frozen, JSON-safe, validación Pydantic
- Exportar desde `__init__.py`

**Tests**:
- `tests/domain/test_keypoints.py`
  - Keypoint con valores válidos
  - Keypoint rechaza x/y/confidence fuera de rango
  - Keypoints2D con lista de keypoints
  - JSON serialization funciona

**Acceptance**:
- ✅ Tests pasan
- ✅ mypy sin errores
- ✅ ruff sin errores

---

## Task 2: PoseEstimator protocol + SyntheticBackend

**Description**: Definir el protocolo de backend y la implementación sintética determinista para testing.

**Files**:
- `aimation_actor_core/infrastructure/ai_models/estimators.py` (nuevo)
- `aimation_actor_core/infrastructure/ai_models/__init__.py` (actualizar exports)

**Requirements**:
- `PoseEstimator` Protocol con método `estimate(frames: list[ndarray]) -> list[Keypoints2D]`
- `SyntheticBackend` implementa el protocolo
  - Determinista: mismo input → mismo output
  - Genera keypoints ficticios pero con estructura válida
  - No requiere dependencias pesadas

**Tests**:
- `tests/infrastructure/test_estimators.py`
  - SyntheticBackend retorna Keypoints2D válidos
  - Determinismo: misma entrada → misma salida
  - Estructura de keypoints correcta

**Acceptance**:
- ✅ Tests pasan
- ✅ mypy sin errores
- ✅ ruff sin errores

---

## Task 3: OnnxBackend (import lazy)

**Description**: Implementar el backend ONNX con import lazy para que no falle si onnxruntime no está instalado.

**Files**:
- `aimation_actor_core/infrastructure/ai_models/estimators.py` (agregar OnnxBackend)

**Requirements**:
- `OnnxBackend` implementa PoseEstimator
- Import de onnxruntime DENTRO del método `__init__` o `estimate` (lazy)
- Si onnxruntime no está disponible, lanzar error claro al intentar usarlo
- Placeholder para lógica real (por ahora puede lanzar NotImplementedError o retornar keypoints dummy)

**Tests**:
- `tests/infrastructure/test_estimators.py` (agregar)
  - OnnxBackend sin onnxruntime instalado lanza error claro
  - Con onnxruntime instalado, estructura correcta

**Acceptance**:
- ✅ Tests pasan
- ✅ mypy sin errores
- ✅ ruff sin errores
- ✅ No rompe si onnxruntime no está instalado

---

## Task 4: Pose2DNode implementation

**Description**: Implementar el nodo INode que consume FRAMES y produce KEYPOINTS_2D.

**Files**:
- `aimation_actor_core/infrastructure/ai_models/pose_2d.py` (nuevo)
- `aimation_actor_core/infrastructure/ai_models/__init__.py` (actualizar exports)

**Requirements**:
- `Pose2DNode` implementa INode
- `get_schema()`: type="pose-2d", category=AI, inputs=[frames:FRAMES], outputs=[keypoints:KEYPOINTS_2D], params=[model:STRING optional, confidence:NUMBER optional]
- `execute()`:
  - Lee `frames` de inputs
  - Lee `model` de params (default: "synthetic")
  - Lee `confidence` de params (default: 0.0)
  - Instancia backend apropiado según `model`
  - Ejecuta `backend.estimate(frames)` en thread pool (asyncio.to_thread)
  - Filtra keypoints por confidence threshold
  - Retorna NodeOutput con keypoints
- `validate()`: valida que model sea "synthetic" o "onnx" si está presente

**Tests**:
- `tests/infrastructure/test_pose_2d.py`
  - Schema correcto (type, category, ports, params)
  - Execute con synthetic backend retorna Keypoints2D válidos
  - Execute con confidence filter funciona
  - Execute con model desconocido usa synthetic (fallback)
  - Validate rechaza model inválido
  - Asyncio.to_thread se usa para inferencia

**Acceptance**:
- ✅ Tests pasan
- ✅ mypy sin errores
- ✅ ruff sin errores

---

## Task 5: Register pose-2d node

**Description**: Registrar el nodo pose-2d en el registry para que esté disponible en el catálogo.

**Files**:
- `aimation_actor_core/infrastructure/virtual/node_registry.py` (actualizar)
- `aimation_actor_core/infrastructure/virtual/__init__.py` (actualizar exports)

**Requirements**:
- Importar Pose2DNode en node_registry.py
- Agregar Pose2DNode() al registry en `seeded_node_registry()`
- Exportar Pose2DNode desde __init__.py

**Tests**:
- `tests/infrastructure/test_node_registry.py` (actualizar)
  - Registry contiene "pose-2d"
  - /nodes/types retorna 5 nodos (pass-through, merge, frame-range, video-source, pose-2d)

**Acceptance**:
- ✅ Tests pasan
- ✅ mypy sin errores
- ✅ ruff sin errores

---

## Task 6: Update /health endpoint

**Description**: Actualizar el endpoint /health para reportar el backend de pose activo.

**Files**:
- `aimation_actor_core/api/routers/health.py` (actualizar)

**Requirements**:
- Detectar si onnxruntime está disponible (try/except import)
- Retornar `"pose": "onnx"` si disponible, `"pose": "synthetic"` si no
- No romper si hay error en la detección

**Tests**:
- `tests/api/test_health.py` (actualizar)
  - /health retorna campo "pose" con valor "synthetic" o "onnx"
  - Respuesta es JSON válido

**Acceptance**:
- ✅ Tests pasan
- ✅ mypy sin errores
- ✅ ruff sin errores

---

## Task 7: Add onnxruntime dependency

**Description**: Agregar onnxruntime a las dependencias opcionales del proyecto.

**Files**:
- `pyproject.toml` (actualizar)

**Requirements**:
- Agregar `"onnxruntime"` a `[project.optional-dependencies]` group `ai`
- Resultado: `ai = ["opencv-python-headless", "numpy", "onnxruntime"]`

**Tests**:
- No requiere tests (configuración)

**Acceptance**:
- ✅ pyproject.toml válido
- ✅ `pip install -e ".[ai]"` funciona (opcional, solo si se quiere verificar)

---

## Task 8: Integration test (e2e graph)

**Description**: Test de integración que ejecuta el grafo video-source → pose-2d end-to-end.

**Files**:
- `tests/integration/test_video_to_pose_pipeline.py` (nuevo)

**Requirements**:
- Cargar video de test (usar fixture existente de video-source)
- Ejecutar grafo: video-source → pose-2d
- Verificar que output contiene keypoints válidos
- Verificar que cada frame tiene keypoints
- Verificar estructura JSON-safe

**Tests**:
- `tests/integration/test_video_to_pose_pipeline.py`
  - Grafo completo ejecuta sin errores
  - Output tiene estructura correcta
  - Keypoints son JSON-serializables

**Acceptance**:
- ✅ Tests pasan
- ✅ mypy sin errores
- ✅ ruff sin errores

---

## Execution Order

1. **Task 1** (domain value objects) - sin dependencias
2. **Task 2** (PoseEstimator protocol + SyntheticBackend) - depende de Task 1
3. **Task 3** (OnnxBackend) - depende de Task 2
4. **Task 4** (Pose2DNode) - depende de Tasks 2, 3
5. **Task 5** (register node) - depende de Task 4
6. **Task 6** (update /health) - independiente, puede hacerse en paralelo con Task 5
7. **Task 7** (add dependency) - independiente, puede hacerse en paralelo
8. **Task 8** (integration test) - depende de Tasks 4, 5

## Quality Gates (after each task)

```bash
# Tests
.\.venv\Scripts\python.exe -m pytest

# Type checking
.\.venv\Scripts\python.exe -m mypy aimation_actor_core

# Linting
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .

# Import rules
.\.venv\Scripts\lint-imports.exe
```

## Non-Goals (reiterated)

- ❌ No 3D lifting
- ❌ No temporal cleanup
- ❌ No in-betweening
- ❌ No model download/verification
- ❌ No MediaPipe/TensorFlow
- ❌ No GPU support
