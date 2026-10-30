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

import inspect
import math
import re
import sys
import tempfile
import traceback
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _entry in (str(REPO), str(REPO / "blender_addon")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import aimation_transpose as addon  # noqa: E402
import bpy  # noqa: E402
from aimation_transpose import preview, props, ui  # noqa: E402

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


def _quat_x(angle_deg: float) -> Quaternion:
    """A rotation about the domain X axis (it moves both Y and Z)."""
    half = math.radians(angle_deg) / 2.0
    return Quaternion(math.cos(half), math.sin(half), 0.0, 0.0)


def write_capture(
    path: Path,
    frames: tuple[int, ...],
    extra_bone: str | None = None,
    angles: tuple[float, ...] | None = None,
) -> None:
    """Write one sparse capture with the application's writer.

    ``angles`` gives each key an X-axis spin. Without it every key is identity and
    the file cannot show a missing motion — which is exactly the blind spot that
    let the "keys but no movement" report through the first version of this smoke.
    """
    skeleton = _skeleton(extra_bone)
    keyframes = tuple(
        Keyframe(
            frame=frame,
            pose={
                name: JointPose(
                    rotation=_quat_x(angles[index]) if angles is not None else Quaternion.identity()
                )
                for name in skeleton.names()
            },
        )
        for index, frame in enumerate(frames)
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


def channel_values(action, data_path: str) -> dict:
    """The animated channels of one transform property, by component index.

    Read straight off the fcurves: ``FCurve.evaluate`` is deterministic and needs
    no depsgraph, so it pins what the viewer will really show. The *evaluated
    pose* of a non-active scene is not readable reliably in background mode
    (values lag or freeze depending on the window's own depsgraph), so "the
    skeleton visibly moves" stays a manual check, like the window itself.
    """
    curves = {}
    for layer in action.layers:
        for strip in layer.strips:
            for slot in action.slots:
                bag = strip.channelbag(slot)
                if bag is None:
                    continue
                for fcurve in bag.fcurves:
                    if fcurve.data_path == data_path:
                        curves[fcurve.array_index] = fcurve
    return curves


def sample(channels: dict, frame: int) -> tuple:
    return tuple(round(channels[index].evaluate(frame), 4) for index in sorted(channels))


def interpolations(action) -> set[str]:
    found = set()
    for layer in action.layers:
        for strip in layer.strips:
            for slot in action.slots:
                bag = strip.channelbag(slot)
                if bag is None:
                    continue
                for fcurve in bag.fcurves:
                    found.update(point.interpolation for point in fcurve.keyframe_points)
    return found


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="aimation-smoke-"))
    write_capture(folder / "b_take.fbx", frames=(0, 10, 20), angles=(0.0, 45.0, 90.0))
    write_capture(folder / "a_take.fbx", frames=(0, 15, 30), angles=(0.0, 90.0, 180.0))
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
    check(
        "the viewer shows the pose, not the bind pose, by default",
        source.data.pose_position == "POSE" and scene.preview_rest is False,
        f"{source.data.pose_position} rest={scene.preview_rest}",
    )
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

    # -- S1: the keys must actually move the skeleton ------------------------ #
    # Every capture this smoke first wrote used identity rotations, so it could
    # never have caught a viewer that shows a frozen pose. Read the channels the
    # animator's file actually carries.
    action = source.animation_data.action
    channels = channel_values(action, 'pose.bones["L_Ankle"].rotation_quaternion')
    check(
        "the capture animated the skeleton's rotation",
        bool(channels),
        f"channels={sorted(channels)}",
    )
    at_first = sample(channels, scene.capture_first)
    at_key = sample(channels, scene.capture_first + 15)
    between = sample(channels, scene.capture_first + 20)
    at_last = sample(channels, scene.capture_last)
    check(
        "a keyed frame differs from the first frame",
        at_first != at_key,
        f"{at_first} vs {at_key}",
    )
    check(
        "a frame between keys holds the previous key (stepped, nothing invented)",
        between == at_key,
        f"{between} vs {at_key}",
    )
    check("the last key moves further still", at_last != between, f"{at_last} vs {between}")
    found = interpolations(action)
    check(
        "the viewer re-asserts stepped keys over the importer's LINEAR",
        found == {"CONSTANT"},
        str(found),
    )

    # -- S1: the tool must survive being drawn in the viewer window ---------- #
    viewer_context = types.SimpleNamespace(scene=preview_scene)
    check("the preview scene records its owner", preview_scene.preview_owner == scene)
    check(
        "the tool state resolves from the viewer window",
        props.tool_scene(viewer_context) == scene,
    )
    check(
        "the tool state resolves from the working window",
        props.tool_scene(types.SimpleNamespace(scene=scene)) == scene,
    )
    check(
        "the panel is reachable from the viewer window",
        ui.AIMATION_PT_transpose.poll(viewer_context) is True,
    )
    # Any other scene is a working scene: it gets its own panel, not the viewer's.
    stranger = bpy.data.scenes.new("Stranger Scene")
    check(
        "an unrelated scene still gets its own panel",
        props.tool_scene(types.SimpleNamespace(scene=stranger)) == stranger,
    )
    # A viewer window whose owner is gone must hide the panel, not drive nothing.
    owner_backup = preview_scene.preview_owner
    preview_scene.preview_owner = None
    check(
        "a viewer window with no owner hides the panel instead of misbehaving",
        ui.AIMATION_PT_transpose.poll(viewer_context) is False,
    )
    preview_scene.preview_owner = owner_backup

    # -- S1: bind pose is the opt-in mode, and it really freezes ------------ #
    scene.preview_rest = True
    check("Bind pose switches the armature to REST", source.data.pose_position == "REST")
    scene.preview_rest = False
    check("leaving Bind pose returns to POSE", source.data.pose_position == "POSE")
    check(
        "the panel's own state survives a Rest round trip",
        scene.preview_rest is False and source.data.pose_position == "POSE",
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

    # -- the viewer's write surface ----------------------------------------- #
    # `open_window` only runs interactively, and that is exactly where the first
    # user test crashed: `Window.width` is read-only. These checks pin every
    # attribute the viewer assigns, so a write that Blender forbids fails here
    # instead of in someone's face. Types are looked up by RNA id, never by class
    # name: 5.2 calls these `View3DShading` / `View3DOverlay`, and an earlier
    # draft of this very check crashed on the wrong name.
    def readonly_of(rna_id: str, prop: str):
        for class_name in dir(bpy.types):
            candidate = getattr(bpy.types, class_name, None)
            rna = getattr(candidate, "bl_rna", None)
            if rna is not None and rna.identifier == rna_id:
                return rna.properties[prop].is_readonly
        return "MISSING"

    window_ro = {
        name: readonly_of("Window", name)
        for name in ("scene", "view_layer", "width", "height", "x", "y")
    }
    check("the viewer binds its window by scene", window_ro["scene"] is False, str(window_ro))
    check(
        "the viewer follows that scene's view layer",
        window_ro["view_layer"] is False,
        str(window_ro),
    )
    check(
        "the viewer does not try to size the window (geometry is read-only)",
        all(window_ro[name] is True for name in ("width", "height", "x", "y")),
        str(window_ro),
    )
    check("the viewer can set solid shading", readonly_of("View3DShading", "type") is False)
    check(
        "the viewer can hide relationship lines",
        readonly_of("View3DOverlay", "show_relationship_lines") is False,
    )
    framing = {
        name: readonly_of("RegionView3D", name)
        for name in ("view_location", "view_distance", "view_perspective")
    }
    check(
        "the viewer can frame the armature",
        not any(framing.values()),
        str(framing),
    )
    probe_area = next(
        (area for area in bpy.data.screens[0].areas if area.type == "VIEW_3D"), None
    )
    check(
        "the viewer can ask a viewport to repaint",
        probe_area is not None and callable(getattr(probe_area, "tag_redraw", None)),
    )

    # Headless never reaches the window writes at all (`window_new` fails its
    # poll first), so the checks above cannot catch a forbidden assignment in
    # this function. Read the source instead: the user's crash was exactly an
    # assignment to a read-only property that no headless path would have hit.
    # Every assignment is matched, not a fixed list, so a future write to some
    # other Window property cannot sneak past either.
    assigned = set(re.findall(r"\bwindow\.(\w+)\s*=", inspect.getsource(preview.open_window)))
    writable = {name: readonly_of("Window", name) is False for name in sorted(assigned)}
    forbidden = {name: flag for name, flag in writable.items() if not flag}
    check(
        "open_window assigns only writable Window properties",
        not forbidden,
        f"assigned={writable}",
    )

    # Last, because a successful `window_new` in this mode would rebind the only
    # window's scene and disturb everything above. Headless has no window
    # manager, so the PASS here is the honest refusal; what must never happen is
    # an unwritable attribute blowing up the operator (the user's crash).
    try:
        ok, message = preview.open_window()
    except AttributeError as error:
        check("open_window writes only writable attributes", False, str(error))
    else:
        check(
            "open_window refuses headless with a named reason, not a crash",
            ok is False and "interactive editor" in message,
            message,
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
