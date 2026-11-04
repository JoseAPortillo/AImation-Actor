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
from aimation_transpose import mapping, operators, preview, props, ui  # noqa: E402

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


def near(colour, expected, tolerance: float = 0.02) -> bool:
    """Custom bone colours round-trip through 8-bit theme storage, not floats."""
    return all(
        abs(actual - wanted) <= tolerance
        for actual, wanted in zip(colour, expected, strict=True)
    )


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

    # -- S4: nothing to map before a capture exists -------------------------- #
    ok, message = mapping.activate(scene)
    check(
        "mapping refuses without a capture, by name",
        not ok and "capture" in message.lower(),
        message,
    )

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
    # The legacy importer must run with automatic bone orientation: left at its
    # default it keeps the FBX-authored axes and the skeleton is drawn
    # inside-out. Measured on this very capture: the Pelvis bone's rest offset
    # goes DOWN from the hips, and only with the flag on does its tail end up
    # below its head.
    head = source.data.bones["Pelvis"].head_local
    tail = source.data.bones["Pelvis"].tail_local
    check(
        "a bone that extends downward actually points downward",
        tail.y < head.y,
        f"head={tuple(round(v, 2) for v in head)} tail={tuple(round(v, 2) for v in tail)}",
    )
    check(
        "the capture is imported through the legacy importer with bone orientation on",
        "automatic_bone_orientation=True" in inspect.getsource(preview._import),
    )
    # The viewer's controls live in the panel, so they must tell the truth about
    # whether a viewer window exists. Play/pause and the maximize toggle were
    # removed by user decision (feature doc L14): the viewer window's own
    # timeline already plays the capture, and the floating window is already
    # as large as the animator wants it.
    check("no viewer window is open headless", preview.viewer_window() is None)

    def registered(oper_id: str) -> bool:
        # `hasattr(bpy.ops.aimation, ...)` lies: attribute access always
        # succeeds and returns a lazy wrapper. Registration is only proven by
        # resolving the operator's RNA, which raises for anything unregistered.
        try:
            getattr(bpy.ops.aimation, oper_id).get_rna_type()
        except Exception:  # noqa: BLE001 - any failure means "not registered"
            return False
        return True

    check(
        "the play and maximize operators are gone",
        not registered("toggle_preview") and not registered("maximize_viewer"),
    )
    check(
        "the playback timer no longer backs the viewer",
        not hasattr(addon, "playback") and "playback" not in sys.modules,
    )
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

    # -- S2: Import Capture is a single-file path ---------------------------- #
    # Importing one capture must not drag its whole folder in: the capture
    # folder field above the list is the whole-folder workflow (user decision,
    # feature doc L14). A hand-picked file joins the list remembering its own
    # path, and survives folder refreshes.
    check(
        "Import Capture does not adopt the picked file's folder",
        "preferences.capture_folder = folder" not in inspect.getsource(operators),
    )
    solo_folder = Path(tempfile.mkdtemp(prefix="aimation-smoke-single-"))
    write_capture(solo_folder / "solo_take.fbx", frames=(0, 10), angles=(0.0, 90.0))
    item = scene.capture_items.add()
    item.name = "solo_take.fbx"
    item.path = str(solo_folder / "solo_take.fbx")
    ok, message = preview.load_capture(scene, "solo_take.fbx", stub.capture_folder)
    check(
        "a hand-imported capture loads from its own path, folder aside",
        ok and scene.capture_loaded == "solo_take.fbx",
        message,
    )
    scene.capture_loaded = ""
    item.path = str(solo_folder / "gone.fbx")
    ok, message = preview.load_capture(scene, "solo_take.fbx", stub.capture_folder)
    check(
        "a hand-imported row whose file vanished fails with a named reason",
        not ok and "solo_take.fbx" in message,
        message,
    )
    item.path = str(solo_folder / "solo_take.fbx")
    count = props.refresh_captures(scene, bpy.context)
    rows = [(row.name, row.path) for row in scene.capture_items]
    check(
        "a hand-imported row survives a folder refresh",
        count == 0 and rows == [("solo_take.fbx", str(solo_folder / "solo_take.fbx"))],
        f"count={count} rows={rows}",
    )
    stub.capture_folder = str(solo_folder)
    count = props.refresh_captures(scene, bpy.context)
    rows = [(row.name, row.path) for row in scene.capture_items]
    check(
        "a folder row replaces a hand-imported row for the same file",
        count == 1 and rows == [("solo_take.fbx", "")],
        f"count={count} rows={rows}",
    )

    # -- S2: removing a capture from the list -------------------------------- #
    # The guard must hold while the selection MOVES, not only when the list
    # empties: a clamp that changes capture_index fires the RNA update, and an
    # unguarded update would schedule a load of the row the clamp lands on.
    stub.capture_folder = str(folder)
    count = props.refresh_captures(scene, bpy.context)
    scene.capture_index = 2
    preview._deferred_load()  # consume the scheduled load; the list is settled
    check("a row can be removed from the list", props.remove_capture(scene, "a_take.fbx"))
    check(
        "removing another row keeps the selection",
        props.selected_name(scene) == "c_other.fbx",
        props.selected_name(scene),
    )
    check("removing a row never schedules a load", preview._pending is None)
    check("removing a row leaves the viewer alone", scene.capture_loaded == "c_other.fbx")
    check("removing a missing row fails", not props.remove_capture(scene, "a_take.fbx"))
    stub.capture_folder = str(folder)
    count = props.refresh_captures(scene, bpy.context)
    check(
        "a refresh re-lists a removed folder file",
        count == 3 and "a_take.fbx" in [row.name for row in scene.capture_items],
        f"count={count}",
    )

    # -- S4/S7: the mapping surface ------------------------------------------ #
    # The smoke owns no rig, so one is built by hand: the mapping only needs an
    # armature to point at (and an empty to be offered by the popup).
    rig_data = bpy.data.armatures.new("Test Rig")
    rig = bpy.data.objects.new("Test Rig", rig_data)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bone = rig_data.edit_bones.new("hand_ik")
    edit_bone.head = (0.0, 0.0, 0.0)
    edit_bone.tail = (0.0, 10.0, 0.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    ctrl = bpy.data.objects.new("ctrl_hand", None)
    scene.collection.objects.link(ctrl)

    ok, message = mapping.activate(scene)  # still no rig
    check(
        "mapping refuses without a target rig, by name",
        not ok and "rig" in message.lower(),
        message,
    )
    scene.target_rig = rig
    ok, message = mapping.activate(scene)
    check("mapping starts with a capture and a rig", ok, message)
    armature = preview.source_armature()
    check(
        "mapping forces the bind pose",
        scene.preview_rest is True and armature.data.pose_position == "REST",
        f"rest={scene.preview_rest} pos={armature.data.pose_position}",
    )
    check("mapping turns bone colours on", armature.data.show_bone_colors is True)
    # S4: the rig joins the viewer for the session — one window shows one scene,
    # so seeing a control next to the capture bone requires linking it there.
    shown_rig = bpy.data.scenes[props.PREVIEW_SCENE].objects.get(rig.name)
    check(
        "the target rig joins the viewer while mapping",
        shown_rig is not None and rig.name in scene.objects,
        f"preview={shown_rig is not None} working={rig.name in scene.objects}",
    )
    check(
        "the rig is shown in bind pose, not in its own animation",
        rig.data.pose_position == "REST",
        rig.data.pose_position,
    )
    check(
        "the rig is not mistaken for the capture",
        preview.source_armature() is not None
        and preview.source_armature().name == props.SOURCE_NAME,
        str(preview.source_armature()),
    )
    check(
        "an unmapped bone is grey",
        near(armature.data.bones["L_Ankle"].color.custom.normal, mapping.GREY),
        str(tuple(armature.data.bones["L_Ankle"].color.custom.normal)),
    )

    choices = list(mapping.build_choices(scene))
    check(
        "the popup lists the rig's bones",
        any(identifier.startswith("BONE:Test Rig:hand_ik") for identifier, _ in choices),
        str(choices),
    )
    check(
        "the popup lists the empties in the file",
        any(identifier.startswith("EMPTY:ctrl_hand:") for identifier, _ in choices),
        str(choices),
    )
    check(
        "the panel counts the controls it can offer",
        mapping.available(scene) == len(choices) and mapping.available(scene) >= 2,
        f"{mapping.available(scene)} vs {len(choices)}",
    )
    check(
        "a ready picker reports no blockage",
        mapping.problem(scene) == "",
        mapping.problem(scene),
    )
    # The enum callback must not depend on the context Blender hands it: the
    # list is frozen when the popup opens and read back as-is from there.
    mapping._refresh_choices(scene)
    served = mapping._items(None, types.SimpleNamespace())
    check(
        "the popup serves its frozen list without a context",
        [identifier for identifier, _label, _desc in served]
        == [identifier for identifier, _ in choices],
        str(served),
    )
    check(
        "the frozen list survives a context that resolves no scene",
        any(identifier.startswith("BONE:Test Rig:hand_ik") for identifier, _, _ in served)
        and all(identifier != mapping._NO_CHOICE for identifier, _, _ in served),
        str(served),
    )
    # The trap that kept the popup empty: with ``from __future__ import
    # annotations`` the property annotation is a string, and Blender evaluates
    # it in a namespace without this module's globals, so the lambda's call to
    # ``_items`` raised NameError at draw time and Blender drew no rows.
    annotation = mapping.AIMATION_OT_pick_target.__annotations__["choice"]
    check(
        "the picker's enum annotation is not a postponed string",
        not isinstance(annotation, str),
        type(annotation).__name__,
    )
    items_callback = (
        annotation.keywords.get("items") if not isinstance(annotation, str) else None
    )
    resolved = items_callback(None, types.SimpleNamespace()) if items_callback else []
    check(
        "the enum callback Blender holds resolves _items in real globals",
        len(resolved) == len(choices),
        f"{len(resolved)} vs {len(choices)}",
    )
    kept_rig, scene.target_rig = scene.target_rig, None
    # Without a rig mapping cannot start, but an empty is still a legal target:
    # the count says what the popup would list, the message says what blocks
    # the session, and neither pretends the other.
    check(
        "the panel names a missing target rig instead of showing nothing",
        "rig" in mapping.problem(scene).lower() and mapping.available(scene) == 1,
        f"{mapping.problem(scene)} / {mapping.available(scene)}",
    )
    scene.target_rig = kept_rig

    scene.mapping_pending = "L_Ankle"
    mapping.refresh_colours(scene)
    check(
        "the bone awaiting its control turns amber",
        near(armature.data.bones["L_Ankle"].color.custom.normal, mapping.PENDING),
    )

    mapping.link(scene, "L_Ankle", "BONE", "Test Rig", "hand_ik")
    scene.mapping_pending = ""
    mapping.refresh_colours(scene)
    check(
        "a linked bone turns green",
        near(armature.data.bones["L_Ankle"].color.custom.normal, mapping.GREEN),
    )
    stored = props.link_of(scene, "L_Ankle")
    check(
        "the link is stored by source bone name",
        stored is not None
        and (stored.kind, stored.object, stored.target_bone) == ("BONE", "Test Rig", "hand_ik"),
    )
    scene.mapping_pending = "L_Ankle"
    labels = [label for _identifier, label in mapping.build_choices(scene)]
    check("a mapped bone offers to remove its link", "Remove link" in labels, str(labels))
    scene.mapping_pending = ""
    check("a resolvable link is not reported missing", mapping.unresolved(scene) == 0)

    # A link names a control, not an object pointer: reloading another capture
    # must repaint it on the skeleton that is showing now (S7).
    scene.capture_index = 0
    preview._deferred_load()
    reloaded = preview.source_armature()
    check("the mapping survives a capture reload", props.link_of(scene, "L_Ankle") is not None)
    check(
        "a link repaints green on the reloaded skeleton",
        reloaded is not None
        and near(reloaded.data.bones["L_Ankle"].color.custom.normal, mapping.GREEN),
    )

    check("a link can be removed", mapping.unlink(scene, "L_Ankle"))
    check(
        "an unlinked bone returns to grey",
        reloaded is not None
        and near(reloaded.data.bones["L_Ankle"].color.custom.normal, mapping.GREY),
    )
    check("unlinking a missing link fails", not mapping.unlink(scene, "L_Ankle"))

    mapping.link(scene, "Main", "EMPTY", "ghost_control")
    check("a link to a vanished control is counted", mapping.unresolved(scene) == 1)
    check(
        "a link to a vanished control is not painted green",
        reloaded is not None
        and not near(reloaded.data.bones["Main"].color.custom.normal, mapping.GREEN),
    )
    mapping.unlink(scene, "Main")

    mapping.finish(scene)
    check(
        "finishing mapping returns the viewer to the pose",
        scene.mapping_active is False and reloaded.data.pose_position == "POSE",
    )
    check(
        "finishing takes the rig back out of the viewer",
        bpy.data.scenes[props.PREVIEW_SCENE].objects.get(rig.name) is None
        and rig.name in scene.objects,
        f"preview={bpy.data.scenes[props.PREVIEW_SCENE].objects.get(rig.name)}",
    )
    check(
        "the rig's own pose mode comes back with it",
        rig.data.pose_position == "POSE",
        rig.data.pose_position,
    )
    check(
        "the mapping operators are registered",
        registered("map_bones") and registered("pick_target") and registered("finish_mapping"),
    )
    # Headless cannot invoke a modal (the operator call is invalid without a
    # window manager), so the refusal condition is exercised directly: no
    # window, a window on the animator's scene, and the viewer's own window.
    check(
        "the map modal refuses a window that is not the viewer",
        "viewer" in (mapping._refusal(types.SimpleNamespace(scene=scene, window=None)) or ""),
    )
    check(
        "the map modal refuses the animator's own window",
        "viewer"
        in (
            mapping._refusal(
                types.SimpleNamespace(
                    scene=scene, window=types.SimpleNamespace(scene=scene)
                )
            )
            or ""
        ),
    )
    check(
        "the map modal accepts the viewer window",
        mapping._refusal(
            types.SimpleNamespace(
                scene=preview_scene, window=types.SimpleNamespace(scene=preview_scene)
            )
        )
        is None,
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
