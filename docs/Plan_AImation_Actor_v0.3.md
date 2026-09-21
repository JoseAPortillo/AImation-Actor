# Plan AImation Actor v0.3 — Animator-First

**Estado**: Plan vigente. **Sustituye** a `Plan_AImation_Actor_EXT.md` (v0.2), que queda como referencia histórica. **Fecha**: 2026-09-14.

Este plan replantea el producto alrededor de su usuario final: **un animador sin conocimientos técnicos**. La aplicación debe ser directa, tangible y con todo el núcleo de funcionamiento invisible. Lo construido hasta ahora se reutiliza en la medida en que sirva a ese flujo.

---

## Quick Path — El flujo base

```
🎬 Video            ✏️ Blender           ✨ Generar           🎬 Blender
(ver video,      →  (editar poses    →  (in-betweens     →  (rig sombra
 marcar golden       en pose mode)       realistas con IA)    + bake)
 poses)
```

1. El animador carga un video en el nodo **Video**.
2. Marca **golden poses** en un timeslider visual (pines dorados G1…Gn), o captura el video completo.
3. Pulsa **"Editar en Blender"** — las poses viajan a Blender de forma transparente.
4. Ajusta las poses en pose mode (toda la potencia del DCC).
5. Pulsa **"Volver a la app"** — las poses ya editadas regresan.
6. En el nodo **Generar movimiento**, ajusta 2 sliders sencillos y pulsa generar.
7. Revisa el preview 3D; pulsa **"Otra versión"** si quiere variantes, o **"Enviar a Blender"** para crear el rig sombra.

**Regla de oro: el animador nunca ve JSON, nodos de procesamiento, ni configuración de modelos.**

---

## 1. Qué cambia respecto a v0.2

| Área | v0.2 (anterior) | v0.3 (vigente) |
|---|---|---|
| Usuario objetivo | Animador + TD | **Animador no técnico** (TDs conservan el modo avanzado) |
| Criterio de éxito | Catálogo de nodos y editor | **Flujo completo tangible** sobre un video real |
| In-betweening | Procedural primero (§12.5) | **Generativo como mecanismo principal**; procedural queda de fallback |
| Editor JSON de blocking | UX visible | **Eliminado como UX**; queda solo en modo debug/avanzado |
| Entrada de poses clave | Export manual | **Timeslider visual con pines dorados** |
| Edición de poses 3D | (no definido) | **En Blender**, vía sesión transparente |
| Modelos | ONNX para pose (rtmpose, motionbert) | **Añade categoría motion-generation** con doble backend |
| Importancia de lo generativo | Fase 8 opcional | **Núcleo del producto** |

---

## 2. UX detallada

### 2.1 Nodo Video — timeslider de golden poses

```
┌─────────────────────────────────────────────┐
│  🎬 Video — Fuente de movimiento             │
│  ┌───────────────────────────────────────┐  │
│  │      [ Preview del video ]            │  │
│  │      [ frame 0042 / 0300 ]            │  │
│  └───────────────────────────────────────┘  │
│  [Cargar video] [▶/⏸] [Capturar TODO el video] │
│                                              │
│  ────●────────●──────────────●───────────   │  ← timeslider
│       G1       G2             G3             │
│  Frame 042 │ t=01:44 │ Pose ✓ conf 0.92      │
│                                              │
│  [Enviar a Blender →]                        │
└─────────────────────────────────────────────┘
```

| Elemento | Comportamiento |
|---|---|
| Navegación | Controles estándar: play/pause, arrastrar playhead, teclas ←/→ |
| Marcar pose | Botón **"Marcar pose"** o doble clic en el timeslider |
| Pin dorado | `G1`…`Gn` en el timeslider; clic salta al frame, arrastre reposiciona, clic derecho/Supr borra |
| Estado del pin | `⏳ procesando → ✓ confianza` o `✗` (el frame no sirve, se re-marca) |
| Miniatura | Al pasar el ratón: frame + pose detectada |
| Overlay de esqueleto | **Esqueleto 2D en vivo sobre el video** con toggle para ocultarlo |
| Capturar TODO | Detecta el video completo (reutiliza el flujo video-to-motion actual) |

La detección de cada golden pose es silenciosa: pose-2d → pose-3d → representación neutral, en segundo plano.

### 2.2 Nodo Generar movimiento

```
┌─────────────────────────────────────────────┐
│  ✨ Generar movimiento                       │
│  Golden poses:  G1 ✓  G2 ✓  G3 ✓  G4 ✓      │
│  (4 poses, editadas en Blender)             │
│  Naturalidad        [────────●────] 50%      │
│  Respetar mis poses [────●─────────] 70%     │
│  [🎬 Generar movimiento]  ⏳ ██████ 80%      │
│  ┌─ Preview 3D (MotionViewer) ────────────┐  │
│  [↻ Otra versión]   [Enviar a Blender →]    │
└─────────────────────────────────────────────┘
```

| Control | Qué hace (lenguaje humano) |
|---|---|
| Slider **Naturalidad** | Cuánto "vive" el movimiento (variación/expresividad) |
| Slider **Respetar mis poses** | Cuánto se mantiene fiel a las golden poses editadas |
| **Avanzado** (colapsable) | Parámetros técnicos para quien los necesite (nunca por defecto) |
| **Generar movimiento** | Ejecuta el modelo; barra de progreso |
| **Otra versión** | Nueva variante con el mismo setup |
| **Enviar a Blender** | Crea el rig sombra con el baker existente |

### 2.3 Integración con Blender (transparente)

- La sesión app↔Blender ya existe (registro + heartbeat + token en memoria, sin archivos).
- **Push**: core → addon crea armature editable con las golden poses.
- **Edición**: el animador trabaja en pose mode.
- **Pull**: "Volver a la app" captura las poses editadas y las envía al core.
- **Salida**: el baker existente genera la Action y el rig sombra.
- Restricción conocida: rigs con constraints requieren la vía `nla.bake` (v0.2 del addon); la guardia actual falla alto en lugar de hornear valores incorrectos.

### 2.4 Modo avanzado (conservado para TDs)

- El editor de nodos completo, el catálogo de 11 nodos y los presets se mantienen.
- El flujo simple (v0.3) y el avanzado comparten el mismo core.

---

## 3. Estrategia de modelos

### 3.1 Qué produce el nodo generativo

**Motion generation 3D**: el modelo genera poses intermedias **sobre el esqueleto neutral**, condicionado por las golden poses (video original como referencia de estilo, ritmo y contactos). **No** es interpolación de fotogramas de video.

### 3.2 Doble backend

| Backend | Cuándo | Modelos candidatos |
|---|---|---|
| **PyTorch fp16 / ONNX+INT8** | **MVP** — modelos compactos de difusión de movimiento | sMDM / MDM-style (sparse-keyframe diffusion, investigación 2025: alineado con flujo de animador) |
| **GGUF / llama.cpp** | **Evolución** — modelos transformer/MLLM grandes | IKMo (image-keyframed, MLLM), MoCoDiff, futuros motion LLMs |

- Con 10 GB de VRAM (mínimo), un modelo compacto de difusión **cabe sin cuantizar**; GGUF se adopta cuando el modelo elegido lo requiera (precedente: conversión Wan2.1-HuMo a GGUF).
- El `provisioner`/`registry` existentes se extienden con la categoría `motion-generation` y soporte de ambos backends.
- **Licencias**: revisar el dataset/modelo base elegido para uso comercial (HumanML3D y derivados) antes de fijarlo.

---

## 4. Arquitectura y reutilización

| Pieza | Estado | Uso en v0.3 |
|---|---|---|
| `pose-2d` / `pose-3d` | ✅ | Detección silenciosa de cada golden pose |
| `video-to-motion` (frame→NeutralMotion) | ✅ | Captura completa + conversión de golden poses |
| `blocking-input` (conversión) | ✅ | Lógica de poses clave; se elimina solo el editor JSON |
| `inbetween-generation` procedural | ✅ | Fallback hasta que el generativo madure |
| MotionViewer 3D (frontend) | ✅ | Preview del nodo Generar |
| Addon Blender: sesión, HTTP, baker, armature | ✅ | Edición en Blender + rig sombra |
| Model provisioner/registry | ✅ | Categoría `motion-generation` (nueva) |
| Canvas React Flow + stores + tests | ✅ | Base del editor y del modo simple |
| Harness de calidad (`eval_cli`) | ✅ | Evaluar el resultado del generativo |

**Piezas nuevas** (las únicas por construir):

1. Timeslider de video con pines dorados (frontend).
2. Push de golden poses core→addon y captura de poses editadas (addon).
3. Nodo generativo MVP: adaptador del modelo + UI.
4. Orquestación del flujo simple (pasos ocultos entre nodos).

---

## 5. Roadmap replanteado

| Fase | Objetivo | Estado | Criterio tangible (demo) |
|---|---|---|---|
| **A — Golden poses viva** | Timeslider + overlay de esqueleto + marcas | ✅ COMPLETA | El animador marca G1…Gn y ve el esqueleto sobre el video |
| **B — Round-trip Blender** | Push de golden poses al addon, edición, captura | ✅ COMPLETA | Poses marcadas → editadas en Blender → de vuelta en la app |
| **C — Generativo MVP** | Modelo compacto + nodo Generar con sliders | 🔄 EN PROCESO | Movimiento realista entre golden poses, preview 3D, variantes |
| **D — Rig sombra + calidad** | Bake final + post-procesado invisible | ⏳ PENDIENTE | Video → rig sombra animado en Blender en una sesión |
| **E — Evolución** | Evaluar GGUF/llama.cpp; modo avanzado; polish/beta | ⏳ PENDIENTE | Beta privada usable por un animador ajeno al proyecto |

### Estado actual (Sept 2026)

- **Phase A**: Completa en `feat/golden-poses-timeslider` (18 commits, no mergeado a main)
- **Phase B**: Completa en misma rama (push/pull Blender, 12 tests addon)
- **Phase C**: Siguiente — Modelo generativo MVP con UI de sliders
- **Prioridad**: Hacer que funcione antes de tests exhaustivos o PRs limpios

Cada fase termina con **algo que un animador puede tocar** — el replanteo abandona la métrica de "nodos construidos".

---

## 6. Fuera de alcance / diferido

- Plugin de Maya — diferido por licencia.
- Cara y dedos — fuera del MVP.
- Cámara en movimiento, múltiples personajes — post-MVP.
- Interpolación de fotogramas de video (RIFE/FILM-style) — descartado: el producto genera animación 3D del esqueleto.
- Generativo basado en texto (prompt-to-motion) — evolución posible, no núcleo.

---

## 7. Prioridad de producción — Funcionamiento primero

**Regla de oro actual**: La aplicación debe **funcionar correctamente** antes de invertir en tests exhaustivos o PRs pulidos.

| Fase | Prioridad | Tests | PRs |
|---|---|---|---|
| **Desarrollo activo** | Hacer que funcione | Mínimos (smoke tests) | WIP, no merge a main |
| **Validación manual** | El usuario verifica el flujo completo | Solo los críticos | Pendientes |
| **Maduración** | Estabilizar | Suite completa | Listos para review |

### Criterios de esta fase

- ✅ **Funcionamiento > Cobertura**: Preferimos una app que funcione con 10 tests a una rota con 400.
- ✅ **Flujo completo tangible**: Cada fase termina con algo que el animador puede tocar.
- ✅ **Tests mínimos viables**: Solo los necesarios para confirmar que el camino feliz funciona.
- ✅ **PRs como registro, no como gate**: Se crean para documentar, no para bloquear el avance.
- ✅ **Deuda técnica controlada**: Sabemos qué dejamos pendiente; lo cerramos cuando el producto esté validado.

### Qué NO hacemos en esta fase

- ❌ Suites de 300+ tests por cambio
- ❌ Requiere review antes de continuar
- ❌ Bloqueamos el avance por coverage
- ❌ Refactors cosméticos antes de funcionalidad

---

## 8. Riesgos

| Riesgo | Mitigación |
|---|---|
| Calidad insuficiente del generativo | Evaluación con `eval_cli` desde la fase C; procedural como fallback |
| Dataset/licencia no comercial del modelo base | Revisión de licencias antes de fijar modelo (paso 3.2) |
| VRAM insuficiente en equipos reales | Modelo compacto fp16 del MVP; GGUF solo si aporta |
| Rigs con constraints en Blender | Vía `nla.bake` en v0.2 del addon; guardia visible mientras tanto |
| Complejidad oculta que vuelve a filtrarse al usuario | Regla de oro: todo técnico vive tras "Avanzado" o en modo TD |

---

## 8. Checklist de éxito (v0.3)

- [ ] Un animador sin instrucciones técnicas completa el flujo: video → marcar → Blender → generar → rig sombra.
- [ ] Las golden poses se marcan con pines dorados en un timeslider, sin JSON ni configuración.
- [ ] El esqueleto se ve en vivo sobre el video (ocultable con un toggle).
- [ ] La edición en Blender es transparente (sin exportar/importar archivos).
- [ ] El nodo Generar produce movimiento realista entre golden poses editadas con 2 sliders.
- [ ] "Otra versión" genera variantes sin fricción.
- [ ] El resultado final crea un rig sombra con su Action en Blender.
- [ ] Todo lo técnico está oculto o tras "Avanzado"; el modo TD conserva el grafo completo.

---

## Next step

**Estado actual**: Phases A y B completas en `feat/golden-poses-timeslider`.

**Siguiente acción**: Continuar con **Phase C — Generativo MVP**.

### Prioridades inmediatas

1. **Levantar la app** (back + front) y verificar que el flujo A→B funciona end-to-end
2. **Implementar Phase C**: Nodo generativo con 2 sliders (Naturalidad + Respetar poses)
3. **Validación manual**: El usuario prueba el flujo completo con un video real
4. **Tests mínimos**: Solo smoke tests que confirmen el camino feliz

### Qué NO hacemos ahora

- No crear PRs until la app funcione
- No suite de tests exhaustiva
- No refactors por refactor
- No pulir UI before funcionalidad

### Criterio de éxito de esta sesión

> "Puedo cargar un video, marcar golden poses, editar en Blender, generar movimiento con sliders, y ver el resultado en 3D."

Cuando eso funcione, hablamos de tests y PRs.