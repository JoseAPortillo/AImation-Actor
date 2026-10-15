# Technical Design and Specification Document: Golden Pose Tool

This document consolidates the software architecture, pipeline design decisions, interface specifications, and input/output (I/O) management for developing the **Minimum Viable Product (MVP)** of a standalone application for professional 3D animators.

---

## 1. Software Technology Architecture

To avoid compatibility issues and ensure project scalability, the tool will be designed using a clean, decoupled development strategy.

### A. Architectural Paradigm: Hexagonal Modular Monolith

The software will be structured as a unified desktop application (a monolith) to simplify local distribution and installation on production workstations, while adopting **Hexagonal Architecture (Ports and Adapters)** in its code structure.

- **Application Core (Core/Domain):** Holds the pure logic for the animation pipeline and timeline state. It is completely independent of GUI frameworks and AI models.
- **Ports (Contract Interfaces):** Define strict communication rules for exchanging 3D files and running motion algorithms, acting as a “black box” to the user interface.
- **Adapters (Interchangeable Infrastructure):** Specific implementations connected to the ports. They allow AI engines (CondMDI, MDM, LAFAN1), 3D viewers (PyOpenGL), and the GUI (PySide6) to be updated, replaced, or added after the MVP without changing a single line of the system core.

### B. Base Technology Stack

- **Language and GUI Framework:** **PySide6** (Qt6 for Python 3.14.x or earlier) for native window management, cross-platform performance (Windows, Linux, macOS), and low-latency event handling.
- **Video Module:** `PySide6.QtMultimedia` and `PySide6.QtMultimediaWidgets` for hardware-accelerated video streaming and frame-accurate inspection.
- **Integrated 3D Viewer (Viewport):** `PySide6.QtOpenGLWidgets.QOpenGLWidget` integrated with **PyOpenGL** (or `PySide6.QtQuick3D`) to render the interactive skeleton with GPU acceleration.
- **3D Interchange Engine (I/O):** _Autodesk FBX Python SDK_ (or open-source parsing libraries such as `pyfbx` / `trimesh`) to read, structure, and write `.fbx` animation files.
- **Pose Capture and Estimation Core:** **GVHMR** (World-Grounded Human Motion Recovery).
- **Artificial Intelligence Backend:** **PyTorch** to run generative models and vision networks. All heavy processing is isolated from the interface in Qt worker threads (`QThread`).

---

## 2. Detailed Workflow (MVP Pipeline)

The pipeline strictly separates AI-automated calculations from the animator’s creative input and manual refinement.

```text
[ Reference Video ] ──➡️ [ 1. Manual Marking in PySide UI ]
                                           │
  [ 3. Real-Time 3D Preview ] 🚀 ─────────┼──➡️ [ 2. Pose Verification in Viewer ]
                                           │
[ 5. Generative Inbetweening ] ⬅️── [ 4. Refinement in Maya/Blender (FBX) ]
        ⬇
[ 6. Final FBX Delivered ]
```

### Pipeline Phase Details

#### Phase 1: Selective Golden Pose Extraction

1. **Load and Inspect:** The animator imports the reference video (MP4/MOV) into the application’s split-view interface.
2. **Human Marking:** The animator moves through the timeline and manually selects the exact frames that represent their _Golden Poses_ (contacts, extremes, anticipations) using keyboard shortcuts.
3. **Per-Frame Inference:** When a pose is marked, the **GVHMR** backend processes **only that isolated frame** atomically.
4. **Instant Visual Feedback:** The 3D viewer draws the extracted 3D skeleton in real time so the animator can verify whether the pose is a good starting point.
5. **Clean Blocking Export:** The application generates an `.fbx` file in which rotations are stored **strictly at the original frame indices** (e.g., Frame 12 and Frame 45). Intermediate sections are exported with no keyframes at all.

#### Phase 2: The Artistic Filter (Human Intervention)

1. **Import into 3D Software:** The animator imports the generated `.fbx` into Blender or Maya and binds it to the final character rig.
2. **Traditional Refinement:** With a clean timeline free of the noise typical of continuous mocap, the animator edits the curves in the traditional _Graph Editor_: refining silhouettes, exaggerating arcs, and adjusting _timing_ or _spacing_.
3. **Refined Blocking Export:** Once the human-authored _blocking_ is final, the animator exports the articulated skeleton back as a “Refined FBX.”

#### Phase 3: Generative Inbetweening (AI Refinement)

1. **Load the Human Work:** The animator imports the modified “Refined FBX” from Maya/Blender back into the application.
2. **Set Constraints (Hard Constraints):** The Motion Diffusion AI reads the file, locks the human keyframes, and marks them as unalterable, mandatory poses.
3. **Generate Transitions (Inbetweens):** Using a generative 3D motion model trained on physics and biomechanics, the AI calculates the accelerations, inertia, and organic arcs needed to connect the animator’s poses.
4. **Approval and Delivery:** The animator previews the fluid animation in the PySide viewer and exports the final `.fbx`, ready for production.

---

## 3. Interaction and Interface Behavior Design

Designed to emulate the experience and speed of professional tools that are industry standards.

### A. Essential Keyboard Shortcuts

- **`Space`:** Play / pause the background reference video.
- **`Right Arrow` / `Left Arrow`:** Advance or rewind exactly **1 frame** for frame-accurate tracking of kinetic contacts.
- **`K` (Keyframe):** Capture the current frame’s pose, send it to the GVHMR engine, and draw a key marker on the timeline.
- **`Delete`:** Remove the selected Golden Pose from the application timeline.
- **`Shift + Right Arrow / Left Arrow`:** Jump directly between captured Golden Poses on the timeline.

### B. Split View Behavior

- **Temporal Synchronization:** The video player and 3D viewer are dynamically linked to the same time indicator.
- **Display on Empty Frames:** When positioned on a frame without a Golden Pose, the 3D viewer displays the skeleton in a neutral pose (or the last pose, faded). This clearly and visually indicates that this timeline region has no keys.

---

## 4. Technical Risk Control and Optimization (VRAM)

A mitigation plan designed specifically to ensure absolute stability when operating with graphics cards limited to **10 GB of VRAM**.

- **Video Performance:** Avoids overloading RAM by reading video through native, direct hardware streaming via PySide. The AI only accesses a temporary bitmap when the capture key is pressed.
- **AI Engine Optimization (GVHMR requires at least 6 GB of VRAM):**
  - **Atomic Inference:** Process one frame at a time (Batch Size = 1) in an isolated `QThread`.
  - **Mixed Precision:** Halve the model weights’ memory footprint by using half-precision data types (`FP16`).
  - **Cache Release:** Explicitly call PyTorch’s memory cleanup function (`torch.cuda.empty_cache()`) after each successful inference.
- **Character Independence (Rig-Agnostic):** The initial `.fbx` export contains only a **clean joint hierarchy** based on the rotation points of the standard analyzed by GVHMR. By excluding complex meshes and heavy deformers, the file is ultralight and compatible with any retargeting system, such as _HumanIK_ in Maya or _Auto-Rig Pro / Rokoko_ in Blender.

---

## 5. Input/Output (I/O Pipeline) Specifications

This module defines file formats, the professional bone hierarchy, and data-conversion requirements to ensure clean, bidirectional exchange between the Tool, Maya, and Blender.

### A. Video Input (Reference Phase)

- **Supported Formats:** `.mp4` and `.mov` using H.264 or ProRes encoding.
- **Reading Logic:** The file is handled through streaming via `PySide6.QtMultimedia`. The application does not decode the entire video into RAM; instead, it extracts a flat RGB image buffer only for the exact frame at which the animator presses `K` to run inference.

### B. Export from Tool ➡️ 3D Software (Phase 1: Initial Blocking)

The goal is to generate an ultralight `.fbx` file containing only the skeleton and keyframes at the exact frames selected by the user, structured according to industry production standards.

#### Standard Bone Hierarchy with Ground Control (Naming Convention)

To ensure direct compatibility with retargeting systems such as **HumanIK (Maya)** or **Auto-Rig Pro / Rokoko (Blender)**, the tool will add a root node at ground level. The base biological rotations calculated by **GVHMR** (SMPL format) will be remapped relative to this node:

```text
Main (Master Bone / Ground Root)
└── Pelvis (Hip / Height relative to Main)
    ├── Spine_1
    │   └── Spine_2
    │       └── Spine_3
    │           └── Neck
    │               └── Head
    │           ├── L_Clavicle          ├── R_Clavicle
    │           │   └── L_Shoulder      │   └── R_Shoulder
    │           │       └── L_Elbow     │       └── R_Elbow
    │           │           └── L_Wrist │           └── R_Wrist
    ├── L_Hip                           ├── R_Hip
    │   └── L_Knee                      │   └── R_Knee
    │       └── L_Ankle                 │       └── R_Ankle
    │           └── L_Foot              │           └── R_Foot
```

#### Data Format and Offset Compensation Logic

- **File Format:** **Binary FBX** (version 2014/2016 for maximum compatibility with older and newer versions of Maya and Blender).
- **Global Transformations (Main Bone):** `Main` is the **animator's** world control and the Python export script leaves it untouched — `Translation (0, 0, 0)` and identity rotation — so the blocking file ships **in place**. The scene displacement the AI calculates is deliberately **not** exported; the animator places the character at the scene's ground level in their 3D software, and that authored motion is what the re-import reads back as a hard constraint (§5.C.2).
- **Relative Transformations (Pelvis Bone):** The pelvis will be positioned relative to its parent (`Main`). Its local X and Y translation coordinates will remain at `0`, while the Z coordinate will store only the distance (height) from the ground to the actor’s hip.
- **Local Transformations (Body Bones):** All secondary bones will store **Rotation** data only, expressed as **Quaternions (Quaternion: W, X, Y, Z)** to avoid gimbal lock.
- **Timeline Structure (Sparse Keyframing):**
  - If the animator marks Golden Poses on frames `15` and `42`, the FBX SDK will create animation curves containing keys only at indices `15` and `42`.
  - **Tangent Settings:** Keyframes will be exported with **Stepped (Constant)** tangents. This prevents the 3D software from automatically interpolating poses before the animator works on them.

### C. Import from 3D Software ➡️ Tool (Phase 3: Generative Inbetweening)

After artistic refinement in Maya or Blender, the animator exports a new `.fbx` file (“Refined FBX”) and loads it back into the PySide Tool.

#### Return FBX Requirements

- **Hierarchy Consistency:** The file must preserve exactly the same bone names and hierarchy as the original export, including the `Main` root node.
- **Animation Mode:** The animator may have changed the _timing_ or added/modified keyframes. The Tool will read any frame containing human-modified rotation keys.
- **Tangent Handling:** The Tool will ignore the interpolation types from the 3D software (Bézier or Linear). It will extract only static pose _snapshots_ from frames containing keys to feed the diffusion model.

#### Data Conversion and Filtering Module

On receiving the “Refined FBX,” the application’s Python backend will automatically perform the following steps:

1. **Skeleton Validation:** Scan the file to ensure that no critical bones in the hierarchy have been renamed or removed.
2. **Hard Constraint Extraction:** Identify the exact frame numbers containing keyframes edited by the animator, extracting the `Main` translation matrices and the local rotation matrices of the rest of the body.
3. **Normalization for the Generative Model:** Convert the structure with the `Main` offset back into the native mathematical space required by the motion diffusion AI model (PyTorch tensors), preparing the empty timeline gaps to be filled by the _Inbetweening_ algorithm.

---

## 6. Generative Inbetweening Engine Specification (Phase 3 AI)

The application’s generative backend will resolve the empty spans between the animator’s refined Golden Poses, calculating realistic arcs, accelerations, and weight transfers using artificial intelligence based on bone vectors.

### A. Modular and Interchangeable Architecture (Model Factory)

To ensure post-MVP software scalability, the application backend will use an agnostic modular structure. The PySide interface will communicate with a universal connector, allowing the user to switch AI engines using a selector in the GUI.

- **MVP Engine (CondMDI):** Initial implementation based on Conditional Diffusion Transformers. It stands out for its native adherence to the animator’s fixed hard constraints and excellent handling of irregular time intervals.
- **Post-MVP Engines (Roadmap):**
  - **MDM Option (Human Motion Diffusion):** A robust probabilistic alternative based on mask imputation, ideal for highly organic and expressive movements.
  - **LAFAN1 Option (Context/Detail Transformers):** A high-speed deterministic alternative (no diffusion). Designed for direct and predictable physical movement (video game style), with minimal VRAM consumption.

### B. Cinematic Post-Processing (IK Solver Cleanup)

Regardless of the AI model selected by the user, the system will run a final automatic cleanup step to resolve contact imperfections (foot sliding or ground penetration):

1. **Foot Lock Detection:** The system checks whether the `L_Foot` or `R_Foot` joints were planted on the ground during the animator’s original Golden Poses.
2. **Inverse Kinematics Correction (IK Correction):** An analytical/numerical IK solver will correct the AI-generated spans frame by frame to mathematically pin the feet to the ground during calculated contacts, eliminating foot sliding entirely before writing the final `.fbx` file.

---

## 7. Scalability Roadmap (Post-MVP)

Once the workflow’s technical stability and MVP acceptance among animators have been validated, the following evolutionary phase will begin:

- **Phase 2 (AI Pose Suggestions):** Integrate a lightweight video-based kinetic analysis model. The algorithm will automatically analyze velocity peaks, abrupt decelerations, and changes in the actor’s direction in the reference. It will predictively display faded-color “suggested keys” on the PySide timeline. The animator can activate, move, or discard them with a click, automating Phase 1 while always retaining the final artistic decision.
