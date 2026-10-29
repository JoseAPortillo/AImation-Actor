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

import pytest
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


# -- reading size and rounded chrome ------------------------------------------ #


def test_reading_text_lifts_one_point_over_the_windows_default(qtbot) -> None:
    # Windows' default is 9 pt Segoe UI; the theme ships 10 pt so labels and
    # menus read comfortably at the animator's arm's length.
    app = QApplication.instance()
    assert app is not None

    theme.apply_theme(app)

    assert app.font().family() == theme.READ_FONT_FAMILY
    assert app.font().pointSize() == theme.READ_FONT_SIZE_PT
    assert theme.READ_FONT_SIZE_PT == 10


def test_the_readouts_grow_with_the_text() -> None:
    qss = theme.stylesheet()
    frame = qss.split("QLabel#frame_readout")[1]
    # The shared selector ends with the same text; take the LAST occurrence,
    # which is the fps-only rule.
    fps = qss.rsplit("QLabel#fps_readout {", 1)[1]
    assert f"font-size: {theme.READOUT_FONT_SIZE_PX}px" in frame
    assert f"font-size: {theme.FPS_FONT_SIZE_PX}px" in fps
    assert theme.READOUT_FONT_SIZE_PX > theme.FPS_FONT_SIZE_PX


def test_menu_items_round_with_the_chrome() -> None:
    # Full-width square selection bars at a menu's corners made the popup
    # read square: the items inset and round so the menu's radius shows.
    qss = theme.stylesheet()
    items = qss.split("QMenu::item")[1]
    assert f"border-radius: {theme.ITEM_RADIUS}px" in items
    assert "margin" in items


def test_the_video_viewer_paints_rounded_corners(qtbot) -> None:
    # The surface paints the picture itself, so QSS cannot round it: the
    # pin is on the rendered pixels — corners show the window ground, the
    # center is the black picture, and the frame border is drawn on top.
    from PySide6.QtWidgets import QLabel  # noqa: F401 - qtbot keeps the app alive

    from aimation_actor.adapters.gui.video_player import _VideoSurface

    app = QApplication.instance()
    assert app is not None
    theme.apply_theme(app)

    surface = _VideoSurface()
    qtbot.addWidget(surface)
    surface.resize(120, 80)

    grabbed = surface.grab().toImage()
    corner = grabbed.pixelColor(3, 3).name().upper()
    center = grabbed.pixelColor(60, 40).name().upper()
    assert corner != "#000000"  # the corner is clipped away from the picture
    assert center == "#000000"  # the picture fills the rounded frame
    edge = grabbed.pixelColor(60, 1).name().upper()
    assert edge != "#000000"  # the frame border is painted on the rim


# -- the light mode and its switch --------------------------------------------- #


def test_light_keeps_the_accent_family_and_inverts_the_text() -> None:
    # The accents are the brand: identical in both modes. What flips is the
    # ground and the reading color.
    assert theme.LIGHT.bg_base != theme.DARK.bg_base
    assert theme.LIGHT.primary == theme.PRIMARY
    assert theme.LIGHT.accent == theme.ACCENT
    assert theme.LIGHT.text != theme.TEXT
    assert theme.LIGHT.border_radius == theme.BORDER_RADIUS


def test_apply_theme_light_recolors_and_back(qtbot) -> None:
    app = QApplication.instance()
    assert app is not None

    theme.apply_theme(app, "light")

    assert app.property("theme_mode") == "light"
    assert app.palette().window().color().name().upper() == theme.LIGHT.bg_base
    assert app.palette().text().color().name().upper() == theme.LIGHT.text
    assert theme.LIGHT.bg_base in app.styleSheet()

    theme.apply_theme(app, "dark")

    assert app.palette().window().color().name().upper() == theme.BG_BASE


def test_the_active_spec_follows_the_applied_mode(qtbot) -> None:
    # The custom painters (the video viewer) read the ACTIVE spec at paint
    # time: the pin is that the accessor answers with what was applied.
    app = QApplication.instance()
    assert app is not None

    theme.apply_theme(app, "light")
    assert theme.active().name == "light"

    theme.apply_theme(app, "dark")
    assert theme.active().name == "dark"


def test_the_settings_store_round_trips(tmp_path) -> None:
    from PySide6.QtCore import QSettings

    store = theme.QSettingsThemeStore(
        QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat)
    )
    assert store.load() == "dark"  # the default before anything was saved
    store.save("light")
    assert store.load() == "light"


class _MemoryThemeStore:
    def __init__(self) -> None:
        self.mode = "dark"
        self.saved: list[str] = []

    def load(self) -> str:
        return self.mode

    def save(self, mode: str) -> None:
        self.saved.append(mode)
        self.mode = mode


class _MemoryRecents:
    def __init__(self) -> None:
        self.paths: tuple[str, ...] = ()

    def load(self) -> tuple[str, ...]:
        return self.paths

    def save(self, paths) -> None:
        self.paths = tuple(paths)


@pytest.fixture
def themed_window(qtbot):
    from aimation_actor.adapters.gui.main_window import MainWindow

    store = _MemoryThemeStore()
    main = MainWindow(
        recents=_MemoryRecents(),  # type: ignore[arg-type]
        theme_store=store,  # type: ignore[arg-type]
        theme_mode="dark",
    )
    qtbot.addWidget(main)
    return main, store


def test_the_view_menu_offers_the_theme_switch(themed_window) -> None:
    main, _store = themed_window

    view = next(a for a in main.menuBar().actions() if a.text() == "&View")
    assert [a.text() for a in view.menu().actions()] == [
        "&Dark theme",
        "&Light theme",
    ]
    assert main.action_dark_theme.isChecked()
    assert not main.action_light_theme.isChecked()


def test_switching_to_light_recolors_and_persists(themed_window) -> None:
    main, store = themed_window
    app = QApplication.instance()
    assert app is not None

    main.action_light_theme.trigger()

    assert app.palette().window().color().name().upper() == theme.LIGHT.bg_base
    assert store.saved == ["light"]
    assert main.action_light_theme.isChecked()
    assert not main.action_dark_theme.isChecked()


def test_a_window_started_in_light_opens_checked_light(qtbot) -> None:
    from aimation_actor.adapters.gui.main_window import MainWindow

    main = MainWindow(
        recents=_MemoryRecents(),  # type: ignore[arg-type]
        theme_store=_MemoryThemeStore(),  # type: ignore[arg-type]
        theme_mode="light",
    )
    qtbot.addWidget(main)

    assert main.action_light_theme.isChecked()
    assert not main.action_dark_theme.isChecked()
    app = QApplication.instance()
    assert app is not None
    assert app.palette().window().color().name().upper() == theme.LIGHT.bg_base


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
