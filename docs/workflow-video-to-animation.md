# Workflow: Video a Animación 3D

Este workflow muestra cómo convertir un video de una persona en una animación 3D neutral usando los nodos de AImation Actor.

## Objetivo

Extraer la pose de una persona de un video y generar un archivo de animación 3D que pueda usarse en otros sistemas.

## Flujo de nodos

```
[Video Source] → [Pose 2D] → [Pose 3D] → [Video to Motion]
     ↓              ↓            ↓              ↓
  frames        keypoints_2d  keypoints_3d  neutral_animation
```

## Paso a paso

### 1. Crear el nodo de video source

**Arrastra** el nodo "Frame Extractor" desde la paleta (categoría "Sources") al canvas.

**Configura el parámetro `video_path`:**
- Haz clic en el campo de archivo del nodo
- Selecciona un archivo de video (MP4, AVI, MOV)
- Verás una preview del video en el nodo

**Ajusta los parámetros opcionales:**
- `start`: segundo de inicio (default: 0)
- `end`: segundo de fin (default: duración completa)
- `resize`: factor de escala (default: 1.0, usar 0.5 para mitad de resolución)

**Tip:** Usa `resize: 0.5` si el video es 4K para acelerar el procesamiento.

### 2. Crear el nodo de estimación de poses 2D

**Arrastra** el nodo "Pose 2D" desde la paleta (categoría "AI").

**Conecta los puertos:**
- Arrastra desde el puerto `frames` (verde) del Video Source
- Hasta el puerto `frames` (verde) del Pose 2D

**Configura los parámetros:**
- `model`: "synthetic" (rápido, para testing) o "onnx" (preciso, requiere modelo descargado)
- `confidence`: umbral de confianza (default: 0.0, usar 0.5 para filtrar detecciones débiles)

### 3. Crear el nodo de lifting 3D

**Arrastra** el nodo "Pose 3D" desde la paleta (categoría "AI").

**Conecta los puertos:**
- Desde `keypoints` (violeta) del Pose 2D
- Hasta `keypoints` (violeta) del Pose 3D

**Configura los parámetros:**
- `model`: "synthetic" (heurístico) o "onnx" (requiere modelo entrenado)
- `depth_mode`: "proportional" (respeta proporciones corporales) o "flat" (profundidad uniforme)
- `confidence`: umbral de confianza (default: 0.0)

### 4. Crear el nodo de conversión a animación

**Arrastra** el nodo "Video to Motion" desde la paleta (categoría "Output").

**Conecta los puertos:**
- Desde `keypoints_3d` (violeta) del Pose 3D
- Hasta `keypoints_3d` (violeta) del Video to Motion

**Configura los parámetros:**
- `person_height_cm`: altura de la persona en cm (default: 172). **Importante:** ajústalo a la altura real de la persona en el video para que la animación tenga proporciones correctas.
- `only_local`: true (default) para generar offsets relativos entre huesos, false para coordenadas absolutas

### 5. Ejecutar el pipeline

**Haz clic** en el botón "Run" en la barra inferior.

**Monitorea el progreso:**
- Verás el estado del job (queued → running → succeeded)
- Los logs aparecen en tiempo real
- Si hay error, se muestra en rojo

**Para cancelar:** haz clic en "Stop" durante la ejecución.

### 6. Obtener el resultado

Cuando el job termina con éxito:
- El nodo "Video to Motion" muestra el resultado
- El resultado es un archivo JSON con la animación neutral
- Puedes guardar el grafo completo con "Save" en el header

## Features útiles

### Duplicar nodos
Selecciona un nodo y haz clic en el botón "⎘" (duplicar) en el header. Útil para crear variantes de un nodo con la misma configuración.

### Colapsar nodos
Haz clic en "▣" para colapsar un nodo y ver solo el header. Útil cuando tienes muchos nodos en el canvas.

### Eliminar nodos
Haz clic en "✕" para eliminar un nodo. Las conexiones se borran automáticamente.

### Drag & drop
Arrastra nodos desde la paleta al canvas. Suéltalos en la posición deseada.

### Conexiones
- Los puertos tienen colores según el tipo de dato
- Solo puedes conectar puertos compatibles (mismo tipo o `any`)
- Si intentas conectar tipos incompatibles, verás un mensaje de error

### Guardar/cargar grafos
- **Save:** guarda el grafo completo (nodos, conexiones, parámetros) en formato `.aimgraph.json`
- **Load:** carga un grafo previamente guardado

## Workflow alternativo: Merge de videos

Si quieres procesar dos videos y combinarlos:

```
[Video Source 1] → [Pose 2D] → [Pose 3D] → [Video to Motion]
       ↓
    [Merge] ← [Video Source 2]
```

1. Crea dos nodos "Video Source" con videos diferentes
2. Conecta ambos al nodo "Merge" (puertos `input_a` y `input_b`)
3. El output `merged` del Merge es un stream combinado
4. Conecta `merged` al Pose 2D y continúa el flujo normal

## Tips de rendimiento

- **Reduce la resolución:** usa `resize: 0.5` o `0.25` en Video Source
- **Limita el rango:** usa `start` y `end` para procesar solo una sección del video
- **Modelo sintético:** usa `model: "synthetic"` para testing rápido (resultados menos precisos)
- **Confianza alta:** usa `confidence: 0.7` para filtrar detecciones ruidosas

## Troubleshooting

### "Cannot connect X → Y: incompatible port types"
Estás intentando conectar puertos de tipos diferentes. Verifica que los colores coincidan:
- Verde: frames, frame_stream
- Violeta: keypoints_2d, pose_3d, neutral_pose, neutral_animation
- Naranja: image
- Azul: number
- Gris: string, boolean

### El job se queda en "queued"
El backend puede estar ocupado. Espera unos segundos o verifica que el servidor esté corriendo.

### Error "model not found"
Algunos modelos ONNX requieren descarga manual. Usa `model: "synthetic"` para testing sin dependencias externas.

### La preview del video no aparece
Verifica que el archivo de video sea compatible (MP4 H.264, AVI, MOV). Algunos codecs no están soportados.

## Siguientes pasos

Una vez que tengas la animación neutral:
- Exporta el resultado para usarlo en Blender, Unity, Unreal Engine
- Combina múltiples animaciones con el nodo "Merge"
- Aplica transformaciones con nodos de la categoría "Rigging" (próximamente)
