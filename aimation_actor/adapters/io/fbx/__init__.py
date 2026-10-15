"""Pure-Python binary FBX 7.4 reader/writer, and the document builder on top.

This package is an independent implementation of the FBX binary container
format. It exists because Blender's exporter always *bakes* animation down to
one key per frame and renumbers the frame range, which is incompatible with the
tool's core requirement: sparse, stepped keys at the exact animator-selected
frame indices.

Modules:

- :mod:`~aimation_actor.adapters.io.fbx.binary` -- node tree, encoder, decoder.
- :mod:`~aimation_actor.adapters.io.fbx.document` -- ``TimelineState`` -> FBX
  node tree.
- :mod:`~aimation_actor.adapters.io.fbx.transform` -- Z-up <-> Y-up conversions.
- :mod:`~aimation_actor.adapters.io.fbx.blender_import` -- Blender-side script
  that dumps an imported FBX to JSON (run as a subprocess, never imported).
"""
