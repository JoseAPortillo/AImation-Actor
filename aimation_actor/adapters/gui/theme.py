"""The application's themes: tokens, palettes and stylesheets (visual identity NFR).

The dark palette is a user-approved product decision (2026-10-29): a warm
dark base, panels one tone up with clean 2 px borders, orange reserved for
ACTION (golden-pose accents, primary interactions), teal for ACTIVE state
(playhead, selections, progress), and warm off-white for reading. The light
mode keeps the same brand family — identical accents, geometry and type —
and inverts only the ground and the reading color. The roles are stated
once here, in the ``ThemeSpec`` fields and the QSS, so a widget asking
"what color is active?" has exactly one honest answer per mode.

Two mechanisms, on purpose:

- the ``QPalette`` carries the colors custom painters read at runtime
  (``KeyStrip`` paints from ``palette().highlight()``) and everything Fusion
  draws natively;
- the stylesheet carries the SHAPES: the 2 px borders, the shared corner
  radius, the taller timeline track with its round playhead knob, and the
  Rajdhani display font on the timeline readouts.

The applied mode lives on the ``QApplication`` (property ``theme_mode``):
painters that draw themselves — the video viewer — ask ``active()`` at paint
time instead of capturing a snapshot of the colors at import time.

Rajdhani (SIL OFL, ``assets/fonts``) is bundled because the display look
must not depend on what the workstation happens to have installed; body
reading text stays in Segoe UI, the Windows system font.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

__all__ = [
    "ACCENT",
    "BG_BASE",
    "BORDER_COLOR",
    "BORDER_RADIUS",
    "BORDER_WIDTH",
    "DARK",
    "DEFAULT_MODE",
    "DISPLAY_FONT_FAMILY",
    "FPS_FONT_SIZE_PX",
    "FONTS_DIR",
    "GROOVE_HEIGHT",
    "HANDLE_BORDER",
    "HANDLE_FILL",
    "HANDLE_SIZE",
    "ITEM_RADIUS",
    "LIGHT",
    "MODES",
    "PANEL",
    "PRIMARY",
    "READOUT_FONT_SIZE_PX",
    "READ_FONT_FAMILY",
    "READ_FONT_SIZE_PT",
    "TEXT",
    "QSettingsThemeStore",
    "ThemeSpec",
    "ThemeStore",
    "active",
    "apply_theme",
    "load_display_fonts",
    "stylesheet",
]

# -- the approved tokens (the dark set; shared accents) ------------------------ #

#: The window's ground: warm near-black.
BG_BASE = "#1E1813"
#: Panels, inputs, menus — one warm tone up from the base.
PANEL = "#2D2620"
#: Action / golden poses, in BOTH modes: the brand does not change with the
#: ground. NEVER reading text: contrast does not survive it.
PRIMARY = "#FF6B00"
#: Critical text and icons — the reading color of the dark mode.
TEXT = "#EDE8E0"
#: Active elements and info: playhead, menu selection, progress. In both modes.
ACCENT = "#007CA3"
#: Borders follow the panels: clean, 2 px, visible against the base.
BORDER_COLOR = "#2D2620"
BORDER_WIDTH = 2

#: Corners are rounded everywhere with one radius — panels, buttons, inputs,
#: menus, tooltips, the progress bar and the timeline track. In both modes.
BORDER_RADIUS = 6

# -- timeline geometry (user-tuned, mode-independent) -------------------------- #

#: The slider track's height: a substantial bar, not a hairline.
GROOVE_HEIGHT = 10
#: The playhead knob's diameter: round, bigger than the track.
HANDLE_SIZE = 18
#: The knob's fill: an UNSATURATED orange — present, not screaming.
HANDLE_FILL = "#E08A4C"
#: The knob's rim: light warm gray, so it reads against any track.
HANDLE_BORDER = "#C6C0B6"

# -- type sizes (user-tuned) --------------------------------------------------- #

#: Body reading size: Windows' Segoe UI default is 9 pt; one point up reads
#: comfortably at the animator's arm's length. Applied app-wide.
READ_FONT_SIZE_PT = 10
#: The timeline's frame readout, in Rajdhani.
READOUT_FONT_SIZE_PX = 16
#: The fps readout sits beside it, one step smaller.
FPS_FONT_SIZE_PX = 14

# -- chrome details ------------------------------------------------------------ #

#: Menu entries inset from the menu's edge and round their own selection bar,
#: so the popup's corner radius reads at the first and last item.
ITEM_RADIUS = 4

#: The bundled angular display face (titles, readouts, technical labels).
DISPLAY_FONT_FAMILY = "Rajdhani"
#: Reading text stays on the Windows system face — zero-risk, always present.
READ_FONT_FAMILY = "Segoe UI"

#: Where the bundled font files live (repo-root ``assets/``, per AGENTS.md).
FONTS_DIR = Path(__file__).resolve().parents[3] / "assets" / "fonts"

_FONT_FILES = ("Rajdhani-SemiBold.ttf", "Rajdhani-Bold.ttf")


@dataclass(frozen=True)
class ThemeSpec:
    """One mode's colors, self-contained: a painter asks the spec, never mixes."""

    name: str
    bg_base: str
    panel: str
    border_color: str
    text: str
    #: Disabled / placeholder text: the reading color, dimmed warm.
    dim_text: str
    #: Pressed / hover fills: the panel, one step toward the ground.
    lifted: str
    #: Text drawn ON the orange (selections, highlighted spans): dark in both
    #: modes, because #FF6B00 never carries light reading text well.
    on_primary: str
    #: The brand accents: identical in every mode — the field exists so the
    #: spec answers the whole question, not because they ever differ.
    primary: str = PRIMARY
    accent: str = ACCENT
    #: Shape is mode-independent, but a painter should ask the spec, not guess.
    border_radius: int = BORDER_RADIUS


DARK = ThemeSpec(
    name="dark",
    bg_base=BG_BASE,
    panel=PANEL,
    border_color=BORDER_COLOR,
    text=TEXT,
    dim_text="#93887C",
    lifted="#3A322A",
    on_primary=BG_BASE,
)
# The light mode keeps the warm family and the same accents: a paper ground,
# panels that are the brightest tone, and dark warm text.
LIGHT = ThemeSpec(
    name="light",
    bg_base="#F4EEE5",
    panel="#FBF8F1",
    border_color="#FBF8F1",
    text="#2A241E",
    dim_text="#8B8072",
    lifted="#E9E1D3",
    on_primary="#1E1813",
)

MODES = ("dark", "light")
DEFAULT_MODE = "dark"


class ThemeStore(Protocol):
    """Where the animator's theme choice persists (same seam shape as recents)."""

    def load(self) -> str: ...

    def save(self, mode: str) -> None: ...


class QSettingsThemeStore:
    """The default store: the user's ``QSettings``, keyed ``theme/mode``."""

    _KEY = "theme/mode"

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()

    def load(self) -> str:
        value = str(self._settings.value(self._KEY, DEFAULT_MODE))
        # A hand-edited config must not crash startup: an unknown mode is the
        # default mode, not an exception.
        return value if value in MODES else DEFAULT_MODE

    def save(self, mode: str) -> None:
        self._settings.setValue(self._KEY, mode)


def active(app: QApplication | None = None) -> ThemeSpec:
    """The spec the application is currently dressed in.

    Custom painters call this at PAINT time, so a theme switch mid-session
    reaches them on the very next frame without any wiring.
    """
    application = app if app is not None else QApplication.instance()
    mode = application.property("theme_mode") if application is not None else None
    return LIGHT if mode == "light" else DARK


def stylesheet(spec: ThemeSpec = DARK) -> str:
    """The application stylesheet for one mode: shapes, borders, display type."""
    return f"""
    QMainWindow, QDialog {{
        background-color: {spec.bg_base};
    }}
    QMenuBar {{
        background-color: {spec.bg_base};
        color: {spec.text};
        border-bottom: {BORDER_WIDTH}px solid {spec.border_color};
        font-family: "{READ_FONT_FAMILY}";
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 5px 10px;
    }}
    QMenuBar::item:selected {{
        background: {spec.panel};
    }}
    QMenu {{
        background-color: {spec.panel};
        color: {spec.text};
        border: {BORDER_WIDTH}px solid {spec.border_color};
        border-radius: {spec.border_radius}px;
        font-family: "{READ_FONT_FAMILY}";
    }}
    QMenu::item {{
        padding: 5px 24px 5px 12px;
        margin: 3px 6px;
        border-radius: {ITEM_RADIUS}px;
    }}
    QMenu::item:selected {{
        background-color: {spec.accent};
        color: {spec.text};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {spec.border_color};
        margin: 4px 12px;
    }}
    QStatusBar {{
        background-color: {spec.bg_base};
        color: {spec.text};
        border-top: {BORDER_WIDTH}px solid {spec.border_color};
        font-family: "{READ_FONT_FAMILY}";
    }}
    QToolTip {{
        background-color: {spec.panel};
        color: {spec.text};
        border: {BORDER_WIDTH}px solid {spec.border_color};
        border-radius: {spec.border_radius}px;
        padding: 4px;
    }}
    QPushButton {{
        background-color: {spec.panel};
        color: {spec.text};
        border: {BORDER_WIDTH}px solid {spec.border_color};
        border-radius: {spec.border_radius}px;
        padding: 6px 16px;
        font-family: "{READ_FONT_FAMILY}";
    }}
    QPushButton:hover {{
        border-color: {spec.primary};
    }}
    QPushButton:pressed {{
        background-color: {spec.lifted};
    }}
    QPushButton:disabled {{
        color: {spec.dim_text};
    }}
    QDoubleSpinBox {{
        background-color: {spec.panel};
        color: {spec.text};
        border: {BORDER_WIDTH}px solid {spec.border_color};
        border-radius: {spec.border_radius}px;
        padding: 3px 6px;
        selection-background-color: {spec.primary};
        selection-color: {spec.on_primary};
    }}
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        background-color: {spec.panel};
        border: none;
        border-radius: 4px;
        width: 16px;
    }}
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
        background-color: {spec.lifted};
    }}
    QProgressBar {{
        background-color: {spec.panel};
        color: {spec.text};
        border: {BORDER_WIDTH}px solid {spec.border_color};
        border-radius: {spec.border_radius}px;
        text-align: center;
        min-height: 14px;
    }}
    QProgressBar::chunk {{
        background-color: {spec.accent};
        border-radius: 4px;
    }}
    QSlider::groove:horizontal {{
        height: {GROOVE_HEIGHT}px;
        background-color: {spec.panel};
        border-radius: {GROOVE_HEIGHT // 2}px;
    }}
    QSlider::sub-page:horizontal {{
        background-color: {spec.accent};
        border-radius: {GROOVE_HEIGHT // 2}px;
    }}
    QSlider::handle:horizontal {{
        background-color: {HANDLE_FILL};
        border: {BORDER_WIDTH}px solid {HANDLE_BORDER};
        border-radius: {HANDLE_SIZE // 2}px;
        width: {HANDLE_SIZE}px;
        margin: -{(HANDLE_SIZE - GROOVE_HEIGHT) // 2}px 0px;
    }}
    QSlider::handle:horizontal:hover {{
        background-color: {spec.primary};
    }}
    QScrollBar:vertical, QScrollBar:horizontal {{
        background-color: {spec.bg_base};
        width: 10px;
        height: 10px;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background-color: {spec.panel};
        border-radius: 4px;
        min-height: 24px;
        min-width: 24px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
        background-color: {spec.lifted};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0px;
        width: 0px;
    }}
    QLabel#frame_readout, QLabel#fps_readout {{
        font-family: "{DISPLAY_FONT_FAMILY}";
        font-weight: 600;
        font-size: {READOUT_FONT_SIZE_PX}px;
        color: {spec.text};
    }}
    QLabel#fps_readout {{
        font-size: {FPS_FONT_SIZE_PX}px;
    }}
    """


def _palette(spec: ThemeSpec) -> QPalette:
    """The Fusion palette for one mode: every role the native painting and
    the custom painters (``KeyStrip``) read."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(spec.bg_base))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(spec.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(spec.panel))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(spec.bg_base))
    palette.setColor(QPalette.ColorRole.Text, QColor(spec.text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(spec.dim_text))
    palette.setColor(QPalette.ColorRole.Button, QColor(spec.panel))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(spec.text))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(spec.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(spec.primary))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(spec.on_primary))
    palette.setColor(QPalette.ColorRole.Accent, QColor(spec.accent))
    palette.setColor(QPalette.ColorRole.Link, QColor(spec.accent))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(spec.panel))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(spec.text))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(spec.dim_text))
    return palette


def load_display_fonts(app: QApplication) -> str:
    """Register the bundled Rajdhani faces; return the family name.

    Idempotent: ``QFontDatabase`` deduplicates repeated loads, so calling
    this again (a second window, a re-applied theme) is safe.
    """
    for name in _FONT_FILES:
        app_font_id = QFontDatabase.addApplicationFont(str(FONTS_DIR / name))
        if app_font_id < 0:
            raise FileNotFoundError(f"the bundled font could not be loaded: {name}")
    return DISPLAY_FONT_FAMILY


def apply_theme(app: QApplication, mode: str = DEFAULT_MODE) -> None:
    """Dress the application in one mode; safe to call again on a switch.

    The order matters: Fusion first (its palette-aware drawing must be in
    place), then the palette (what painters read), then the stylesheet
    (what overrides shapes on top of it). Without Fusion, Windows' native
    style ignores half of the palette and the result is a patchwork. The
    mode is stamped on the application as ``theme_mode`` — the single place
    self-painting widgets (the video viewer) ask when they need colors.
    """
    spec = LIGHT if mode == "light" else DARK
    app.setStyle("Fusion")
    app.setProperty("theme_mode", spec.name)
    app.setPalette(_palette(spec))
    load_display_fonts(app)
    app.setFont(QFont(READ_FONT_FAMILY, READ_FONT_SIZE_PT))
    app.setStyleSheet(stylesheet(spec))
