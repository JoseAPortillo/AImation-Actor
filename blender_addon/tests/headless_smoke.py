"""Headless smoke for the transposition add-on's ``bpy`` shell (S1, S2, S3, S9).

A secondary Blender window cannot be opened in ``--background``, so the window
itself is validated by hand. Everything else the add-on does — the preview
scene, the import into *that* scene, the frame-range binding, the action swap on
reload, and the honest failure paths — is real ``bpy`` behaviour and is checked
here, the same policy the application's FBX read bridge follows.

Run it from the repository root::

    & "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" \
        --background --factory-startup --python-exit-code 1 \
        --python blender_addon/tests/headless_smoke.py

It is self-contained: it writes three synthetic captures with the repository's
own FBX writer into a temporary folder, so nothing has to be committed.
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _entry in (str(REPO), str(REPO / "blender_addon")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import aimation_transpose as addon  # noqa: E402
import bpy  # noqa: E402
from aimation_transpose import preview, props  # noqa: E402

from aimation_actor.adapters.io.fbx import binary, document  # noqa: E402
from aimation_actor.core.models import (  # noqa: E402
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)

_FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    """Record one assertion instead of aborting, so one run reports everything."""
    if condition:
        print(f"  ok   {label}")
        return
    _FAILURES.append(label)
    print(f"  FAIL {label}" + (f" — {detail}" if detail else ""))


# --------------------------------------------------------------------------- #
# Synthetic captures
# --------------------------------------------------------------------------- #


def _skeleton(extra_bone: str | None) -> Skeleton:
    joints = [
        JointData(name="Main", parent=None),
        JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=90.0)),
        JointData(name="L_Ankle", parent="Pelvis", rest_translation=Vector3(z=-80.0)),
    ]
    if extra_bone is not None:
        joints.append(
            JointData(name=extra_bone, parent="L_Ankle", rest_translation=Vector3(z=-10.0))
        )
    return Skeleton(joints=tuple(joints))


def write_capture(path: Path, frames: tuple[int, ...], extra_bone: str | None = None) -> None:
    """Write one sparse capture with the application's writer."""
    skeleton = _skeleton(extra_bone)
    keyframes = tuple(
        Keyframe(
            frame=frame,
            pose={name: JointPose(rotation=Quaternion.identity()) for name in skeleton.names()},
        )
        for frame in frames
    )
    state = TimelineState(
        skeleton=skeleton,
        keyframes=keyframes,
        fps=30.0,
        frame_start=frames[0],
        frame_end=frames[-1],
    )
    path.write_bytes(binary.serialize(document.build_document(state)))


# --------------------------------------------------------------------------- #
# Preferences stub
# --------------------------------------------------------------------------- #


class _StubPreferences:
    """Stands in for the add-on preferences block.

    The package is imported from this repository, not installed as a Blender
    extension, so it has no entry in ``context.preferences.addons``. Patching the
    lookup is enough to exercise the real code path — every caller goes through
    ``prefs.preferences`` at call time.
    """

    capture_folder = ""


def armature_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="aimation-smoke-"))
    write_capture(folder / "b_take.fbx", frames=(0, 10, 20))
    write_capture(folder / "a_take.fbx", frames=(0, 15, 30))
    write_capture(folder / "c_other.fbx", frames=(0, 10), extra_bone="R_Hand")
    (folder / "notes.txt").write_text("not a capture", encoding="utf-8")

    stub = _StubPreferences()
    stub.capture_folder = str(folder)
    addon.prefs.preferences = lambda context=None: stub  # type: ignore[assignment]

    addon.register()
    scene = bpy.context.scene

    # -- S2: the list ------------------------------------------------------ #
    count = props.refresh_captures(scene, bpy.context)
    names = [item.name for item in scene.capture_items]
    check("the list holds only .fbx captures", count == 3, f"count={count} names={names}")
    check("the list is sorted case-insensitively", names == sorted(names, key=str.casefold), names)

    # -- S2/S1: the first load --------------------------------------------- #
    # The animator's scene must come out of an import exactly as it went in.
    scene.render.fps = 24
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = 250
    scene.frame_current = 7

    scene.capture_index = 0
    check("the listbox selection resolves to a name", props.selected_name(scene) == "a_take.fbx")

    # -- S3: same bones swap, different bones replace ----------------------- #
    preview._deferred_load()  # what the timer would run; timers never fire headless

    preview_scene = bpy.data.scenes.get(props.PREVIEW_SCENE)
    check("the preview scene exists", preview_scene is not None)
    in_preview = [obj for obj in preview_scene.objects if obj.type == "ARMATURE"]
    check("exactly one armature lives in the preview scene", len(in_preview) == 1)
    check(
        "the working scene never contains the capture",
        not [obj for obj in scene.objects if obj.type == "ARMATURE"],
    )
    if not in_preview:
        return

    source = in_preview[0]
    source_pointer = source.as_pointer()
    check("the source armature is marked", bool(source.get(props.SOURCE_MARKER)))
    check("the source is shown in front", source.show_in_front is True)
    check("the source is in rest pose while mapping", source.data.pose_position == "REST")
    check(
        "the clock took the capture's frame range",
        (scene.capture_first, scene.capture_last) == (0, 30),
        f"{(scene.capture_first, scene.capture_last)}",
    )
    check(
        "the capture's frame rate reached the preview scene",
        preview_scene.render.fps == 30,
        str(preview_scene.render.fps),
    )
    check("the loaded capture is recorded", scene.capture_loaded == "a_take.fbx")
    check("the clock starts on the first frame", scene.preview_frame == 0)
    check("no duplicate armature was left behind", len(armature_objects()) == 1)
    check(
        "the animator's scene is restored after the import",
        (
            scene.render.fps,
            scene.frame_start,
            scene.frame_end,
            scene.frame_current,
        )
        == (24, 1, 250, 7),
        (
            f"fps={scene.render.fps} range={(scene.frame_start, scene.frame_end)} "
            f"frame={scene.frame_current}"
        ),
    )

    scene.capture_index = 1
    preview._deferred_load()
    in_preview = [obj for obj in preview_scene.objects if obj.type == "ARMATURE"]
    check("a same-skeleton capture keeps one armature", len(armature_objects()) == 1)
    check(
        "a same-skeleton capture reuses the armature",
        bool(in_preview) and in_preview[0].as_pointer() == source_pointer,
    )
    check(
        "a same-skeleton capture rebinds the frame range",
        (scene.capture_first, scene.capture_last) == (0, 20),
        f"{(scene.capture_first, scene.capture_last)}",
    )
    check("a same-skeleton capture updates the record", scene.capture_loaded == "b_take.fbx")

    scene.capture_index = 2
    preview._deferred_load()
    in_preview = [obj for obj in preview_scene.objects if obj.type == "ARMATURE"]
    check("a different skeleton still leaves one armature", len(armature_objects()) == 1)
    check(
        "a different skeleton replaces the source",
        bool(in_preview) and in_preview[0].as_pointer() != source_pointer,
    )
    if in_preview:
        check("the replacement carries the new bone", "R_Hand" in in_preview[0].data.bones)
        check(
            "the replacement keeps the normalised name",
            in_preview[0].name == props.SOURCE_NAME,
            in_preview[0].name,
        )

    # -- S9: honest failures ------------------------------------------------ #
    ok, message = preview.load_capture(scene, "nope.fbx", str(folder))
    check("a missing capture fails with a named reason", not ok and "nope.fbx" in message, message)

    broken = folder / "broken"
    broken.mkdir()
    (broken / "broken.fbx").write_bytes(b"")
    working_before = {obj.as_pointer() for obj in scene.objects}
    ok, message = preview.load_capture(scene, "broken.fbx", str(broken))
    check(
        "a failed import leaves no half-built state",
        not ok and len(armature_objects()) == 1,
        f"ok={ok} armatures={len(armature_objects())} reason={message}",
    )
    check(
        "the working scene is still free of imported objects",
        not [obj for obj in scene.objects if obj.as_pointer() not in working_before],
        [obj.name for obj in scene.objects],
    )

    stub.capture_folder = str(folder / "does-not-exist")
    count = props.refresh_captures(scene, bpy.context)
    check(
        "a missing folder is an empty list, not an error",
        count == 0 and scene.capture_index == -1,
        f"count={count} index={scene.capture_index}",
    )

    addon.unregister()


try:
    main()
except Exception:  # noqa: BLE001 - a smoke script must print why it died
    traceback.print_exc()
    _FAILURES.append("unhandled exception")

print(f"\nSMOKE {'FAILED' if _FAILURES else 'PASSED'} ({len(_FAILURES)} failure(s))")
for failure in _FAILURES:
    print(f"  - {failure}")
if _FAILURES:
    raise SystemExit(1)
