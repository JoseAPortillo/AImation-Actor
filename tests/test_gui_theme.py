"""Tests for the dark theme (visual identity NFR).

The palette and typography are a user-approved product decision (2026-10-29):
warm dark base, orange for golden-pose/action accents, teal for active
state, off-white for reading. What is pinned here is the CONTRACT, not the
pixels: the tokens are the approved hexes, the stylesheet carries them, the
Fusion+palette application colors custom painters (``KeyStrip`` paints from
``palette()``), and Rajdhani ships with the app so the display look does not
depend on what the workstation happens to have installed.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from aimation_actor.adapters.gui import theme

# -- the tokens --------------------------------------------------------------- #


def test_the_tokens_are_the_approved_palette() -> None:
    assert theme.BG_BASE == "#1E1813"
    assert theme.PANEL == "#2D2620"
    assert theme.PRIMARY == "#FF6B00"
    assert theme.TEXT == "#EDE8E0"
    assert theme.ACCENT == "#007CA3"
    assert theme.BORDER_COLOR == "#2D2620"
    assert theme.BORDER_WIDTH == 2


def test_the_stylesheet_carries_every_token() -> None:
    qss = theme.stylesheet()
    for token in (
        theme.BG_BASE,
        theme.PANEL,
        theme.PRIMARY,
        theme.TEXT,
        theme.ACCENT,
        theme.BORDER_COLOR,
    ):
        assert token in qss


def test_corners_are_rounded_with_the_general_radius() -> None:
    assert theme.BORDER_RADIUS == 6
    qss = theme.stylesheet()
    # Buttons, inputs, menus, tooltips and the progress bar all share it.
    assert qss.count(f"border-radius: {theme.BORDER_RADIUS}px") >= 5


def test_the_slider_track_is_taller_and_the_playhead_a_round_orange_knob() -> None:
    qss = theme.stylesheet()
    groove = qss.split("QSlider::groove:horizontal")[1]
    assert f"height: {theme.GROOVE_HEIGHT}px" in groove
    assert f"border-radius: {theme.GROOVE_HEIGHT // 2}px" in groove

    handle = qss.split("QSlider::handle:horizontal")[1]
    assert f"width: {theme.HANDLE_SIZE}px" in handle
    # Round: the radius is half the knob's size.
    assert f"border-radius: {theme.HANDLE_SIZE // 2}px" in handle
    assert theme.HANDLE_FILL in handle  # unsaturated orange fill
    assert theme.HANDLE_BORDER in handle  # light gray rim
    assert "solid" in handle


# -- the application ------------------------------------------------------------- #


def test_apply_theme_sets_fusion_and_the_dark_palette(qtbot) -> None:
    app = QApplication.instance()
    assert app is not None

    theme.apply_theme(app)

    # An installed stylesheet wraps the app's style in QStyleSheetStyle, so
    # the Fusion pin is on the two valid observable states: bare Fusion
    # before any stylesheet, or the wrapper over it afterwards.
    style_class = app.style().metaObject().className()
    assert style_class in ("QFusionStyle", "QStyleSheetStyle"), style_class
    assert app.palette().window().color().name().upper() == theme.BG_BASE
    assert app.palette().text().color().name().upper() == theme.TEXT
    assert app.palette().button().color().name().upper() == theme.PANEL
    # The KeyStrip paints its golden-pose markers from ``palette().highlight``:
    # the approved orange reaches the custom painter through this role.
    assert app.palette().highlight().color().name().upper() == theme.PRIMARY
    assert app.palette().accent().color().name().upper() == theme.ACCENT


def test_the_app_stylesheet_is_installed(qtbot) -> None:
    app = QApplication.instance()
    assert app is not None

    theme.apply_theme(app)

    assert app.styleSheet() == theme.stylesheet()


# -- the bundled display font ------------------------------------------------- #


def test_rajdhani_ships_with_the_app() -> None:
    for name in ("Rajdhani-SemiBold.ttf", "Rajdhani-Bold.ttf"):
        assert (theme.FONTS_DIR / name).is_file(), f"missing bundled font {name}"


def test_load_display_fonts_registers_rajdhani(qtbot) -> None:
    app = QApplication.instance()
    assert app is not None

    family = theme.load_display_fonts(app)

    assert family == theme.DISPLAY_FONT_FAMILY
    assert family in theme.QFontDatabase.families()


def test_timeline_readouts_carry_the_display_font(qtbot) -> None:
    # The QSS targets these readouts BY object name: the pin is on the names
    # and on the selectors existing, not on rendered pixels.
    from aimation_actor.adapters.gui.timeline_bar import TimelineBar

    bar = TimelineBar()
    qtbot.addWidget(bar)

    assert bar.frame_label.objectName() == "frame_readout"
    assert bar.fps_label.objectName() == "fps_readout"
    assert "QLabel#frame_readout" in theme.stylesheet()
    assert "QLabel#fps_readout" in theme.stylesheet()
