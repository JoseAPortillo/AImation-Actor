# Guía Rápida: Ejecutar Workflow en AImation Actor

## Paso 1: Iniciar el Backend

Abre una terminal PowerShell y ejecuta:

```powershell
cd D:\DEEP_CAVE_WORKS\CODE_WORKS\AImation_Actor

# Configurar token de sesión (IMPORTANTE: debe ser el mismo en frontend y backend)
$env:AIMATION_SESSION_TOKEN = "mi-token-12345"

# Iniciar el servidor
.\.venv\Scripts\python.exe -m uvicorn aimation_actor_core.main:app --host 127.0.0.1 --port 8765
```

Deja esta terminal abierta. El servidor debe mostrar:
```
INFO:     Uvicorn running on http://127.0.0.1:8765
```

## Paso 2: Iniciar el Frontend

Abre **otra terminal** PowerShell:

```powershell
cd D:\DEEP_CAVE_WORKS\CODE_WORKS\AImation_Actor\frontend

# Configurar el mismo token
$env:AIMATION_SESSION_TOKEN = "mi-token-12345"

# Iniciar el servidor de desarrollo
npm run dev
```

El frontend se abrirá en `http://localhost:5173` (o te dará la URL exacta).

## Paso 3: Crear el Workflow en el Editor

1. **Arrastra nodos** desde la paleta izquierda al canvas:
   - `Frame Extractor` (Source)
   - `Pose 2D` (AI)
   - `Pose 3D` (AI)
   - `Video to Motion` (Output)

2. **Conecta los puertos** arrastrando desde un puerto de salida (derecha) a un puerto de entrada (izquierda):
   - `Frame Extractor.frames` → `Pose 2D.frames`
   - `Pose 2D.keypoints` → `Pose 3D.keypoints`
   - `Pose 3D.keypoints_3d` → `Video to Motion.keypoints_3d`

3. **Configura el nodo Frame Extractor**:
   - Haz clic en el campo `video_path`
   - Selecciona un archivo de video (ej: `media/sample.avi`)
   - Verás una preview del video en el nodo

4. **Configura parámetros opcionales**:
   - `Frame Extractor`: `start=0`, `end=5`, `resize=1.0`
   - `Pose 2D`: `model="synthetic"`, `confidence=0.0`
   - `Pose 3D`: `model="synthetic"`, `depth_mode="proportional"`
   - `Video to Motion`: `person_height_cm=172`, `only_local=true`

## Paso 4: Ejecutar el Workflow

1. Haz clic en el botón **Run** en la barra inferior
2. Verás el estado del job:
   - `running` → el job está ejecutándose
   - `succeeded` → completado exitosamente
   - `failed` → error (ver logs)
3. Los logs aparecen en tiempo real
4. Cuando termina, el resultado aparece en formato JSON

## Paso 5: Obtener el Resultado

El resultado se muestra en un panel `<pre>` con el JSON de la animación neutral:

```json
{
  "status": "succeeded",
  "result": {
    "meta": {
      "duration_frames": 120,
      "source_type": "video-to-motion"
    },
    "skeleton": { ... },
    "frames": [
      { "frame": 1, "time": 0.041, "pose": { ... } },
      { "frame": 2, "time": 0.083, "pose": { ... } },
      ...
    ]
  }
}
```

## Paso 6: Guardar el Grafo (Opcional)

Haz clic en **Save** en el header para guardar el workflow como `.aimgraph.json`. Puedes cargarlo después con **Load**.

## Troubleshooting

### "Cannot connect X → Y: incompatible port types"
Los puertos tienen tipos diferentes. Verifica que los colores coincidan:
- Verde: `frames`, `frame_stream`
- Violeta: `keypoints_2d`, `pose_3d`, `neutral_pose`, `neutral_animation`

### "Missing required: video-source:video_path"
No has configurado el archivo de video en el nodo Frame Extractor.

### El job se queda en "running"
- Verifica que el backend esté corriendo
- Revisa los logs en la terminal del backend
- El procesamiento de video puede tardar varios segundos

### Error "model not found"
Usa `model="synthetic"` para testing sin dependencias de modelos ONNX.

### El frontend no conecta con el backend
- Verifica que ambos tengan el mismo `AIMATION_SESSION_TOKEN`
- El backend debe estar en `http://127.0.0.1:8765`
- El frontend en `http://localhost:5173`

## Video de Prueba

Si no tienes un video, genera uno de prueba:

```powershell
cd D:\DEEP_CAVE_WORKS\CODE_WORKS\AImation_Actor
.\.venv\Scripts\python.exe -c @"
import cv2, numpy as np
vw=cv2.VideoWriter('media/sample.avi',cv2.VideoWriter_fourcc(*'MJPG'),10,(128,128))
for i in range(20):
    f=np.zeros((128,128,3),np.uint8); cv2.circle(f,(64+i,64),20,(0,200,255),-1); vw.write(f)
vw.release()
"@
```

Esto crea `media/sample.avi` con 20 frames de un círculo moviéndose.

## Resumen del Flujo

```
Backend (terminal 1)          Frontend (terminal 2)
     ↓                              ↓
uvicorn :8765                  npm run dev :5173
     ↓                              ↓
     └────────── HTTP REST ─────────┘
                    ↓
              Editor de Nodos
                    ↓
              Botón Run
                    ↓
              POST /jobs/execute
                    ↓
              Polling GET /jobs/{id}
                    ↓
              Resultado JSON
```
