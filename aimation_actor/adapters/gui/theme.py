"""The dark theme: tokens, palette and stylesheet (visual identity NFR).

The palette is a user-approved product decision (2026-10-29): a warm dark
base, panels one tone up with clean 2 px borders, orange reserved for
ACTION (golden-pose accents, primary interactions), teal for ACTIVE state
(playhead, selections, progress), and warm off-white for reading. The roles
are stated once here, in comments and QSS, so a widget asking "what color is
active?" has exactly one honest answer.

Two mechanisms, on purpose:

- the ``QPalette`` carries the colors custom painters read at runtime
  (``KeyStrip`` paints from ``palette().highlight()``) and everything Fusion
  draws natively;
- the stylesheet carries the SHAPES: the 2 px borders, the shared corner
  radius, the taller timeline track with its round playhead knob, and the
  Rajdhani display font on the timeline readouts.

Rajdhani (SIL OFL, ``assets/fonts``) is bundled because the display look
must not depend on what the workstation happens to have installed; body
reading text stays in Segoe UI, the Windows system font.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

__all__ = [
    "ACCENT",
    "BG_BASE",
    "BORDER_COLOR",
    "BORDER_RADIUS",
    "BORDER_WIDTH",
    "DISPLAY_FONT_FAMILY",
    "FPS_FONT_SIZE_PX",
    "FONTS_DIR",
    "GROOVE_HEIGHT",
    "HANDLE_BORDER",
    "HANDLE_FILL",
    "HANDLE_SIZE",
    "ITEM_RADIUS",
    "PANEL",
    "PRIMARY",
    "READOUT_FONT_SIZE_PX",
    "READ_FONT_FAMILY",
    "READ_FONT_SIZE_PT",
    "TEXT",
    "apply_theme",
    "load_display_fonts",
    "stylesheet",
]

# -- the approved tokens ------------------------------------------------------ #

#: The window's ground: warm near-black.
BG_BASE = "#1E1813"
#: Panels, inputs, menus — one warm tone up from the base.
PANEL = "#2D2620"
#: Action / golden poses. NEVER reading text: on this base it does not survive
#: contrast. It reaches widgets through QSS borders/hovers and the highlight role.
PRIMARY = "#FF6B00"
#: Critical text and icons — the only body-text color.
TEXT = "#EDE8E0"
#: Active elements and info: playhead, menu selection, progress.
ACCENT = "#007CA3"
#: Borders follow the panels: clean, 2 px, visible against the base.
BORDER_COLOR = "#2D2620"
BORDER_WIDTH = 2

#: Corners are rounded everywhere with one radius — panels, buttons, inputs,
#: menus, tooltips, the progress bar and the timeline track.
BORDER_RADIUS = 6

# -- timeline geometry (user-tuned) ------------------------------------------- #

#: The slider track's height: a substantial bar, not a hairline.
GROOVE_HEIGHT = 10
#: The playhead knob's diameter: round, bigger than the track.
HANDLE_SIZE = 18
#: The knob's fill: an UNSATURATED orange — present, not screaming.
HANDLE_FILL = "#E08A4C"
#: The knob's rim: light warm gray, so it reads against any track.
HANDLE_BORDER = "#C6C0B6"

# -- type sizes (user-tuned) -------------------------------------------------- #

#: Body reading size: Windows' Segoe UI default is 9 pt; one point up reads
#: comfortably at the animator's arm's length. Applied app-wide.
READ_FONT_SIZE_PT = 10
#: The timeline's frame readout, in Rajdhani.
READOUT_FONT_SIZE_PX = 16
#: The fps readout sits beside it, one step smaller.
FPS_FONT_SIZE_PX = 14

# -- chrome details ----------------------------------------------------------- #

#: Menu entries inset from the menu's edge and round their own selection bar,
#: so the popup's corner radius reads at the first and last item.
ITEM_RADIUS = 4

#: The bundled angular display face (titles, readouts, technical labels).
DISPLAY_FONT_FAMILY = "Rajdhani"
#: Reading text stays on the Windows system face — zero-risk, always present.
READ_FONT_FAMILY = "Segoe UI"

# -- derived tones (not tokens: mixes of the approved ones) ------------------- #

#: Disabled / placeholder text: the reading color, dimmed warm.
_DIM_TEXT = "#93887C"
#: Pressed / hover fills: the panel, one step up.
_LIFTED = "#3A322A"

#: Where the bundled font files live (repo-root ``assets/``, per AGENTS.md).
FONTS_DIR = Path(__file__).resolve().parents[3] / "assets" / "fonts"

_FONT_FILES = ("Rajdhani-SemiBold.ttf", "Rajdhani-Bold.ttf")


def stylesheet() -> str:
    """The application stylesheet: shapes, borders and display typography."""
    return f"""
    QMainWindow, QDialog {{
        background-color: {BG_BASE};
    }}
    QMenuBar {{
        background-color: {BG_BASE};
        color: {TEXT};
        border-bottom: {BORDER_WIDTH}px solid {BORDER_COLOR};
        font-family: "{READ_FONT_FAMILY}";
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 5px 10px;
    }}
    QMenuBar::item:selected {{
        background: {PANEL};
    }}
    QMenu {{
        background-color: {PANEL};
        color: {TEXT};
        border: {BORDER_WIDTH}px solid {BORDER_COLOR};
        border-radius: {BORDER_RADIUS}px;
        font-family: "{READ_FONT_FAMILY}";
    }}
    QMenu::item {{
        padding: 5px 24px 5px 12px;
        margin: 3px 6px;
        border-radius: {ITEM_RADIUS}px;
    }}
    QMenu::item:selected {{
        background-color: {ACCENT};
        color: {TEXT};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {BORDER_COLOR};
        margin: 4px 12px;
    }}
    QStatusBar {{
        background-color: {BG_BASE};
        color: {TEXT};
        border-top: {BORDER_WIDTH}px solid {BORDER_COLOR};
        font-family: "{READ_FONT_FAMILY}";
    }}
    QToolTip {{
        background-color: {PANEL};
        color: {TEXT};
        border: {BORDER_WIDTH}px solid {BORDER_COLOR};
        border-radius: {BORDER_RADIUS}px;
        padding: 4px;
    }}
    QPushButton {{
        background-color: {PANEL};
        color: {TEXT};
        border: {BORDER_WIDTH}px solid {BORDER_COLOR};
        border-radius: {BORDER_RADIUS}px;
        padding: 6px 16px;
        font-family: "{READ_FONT_FAMILY}";
    }}
    QPushButton:hover {{
        border-color: {PRIMARY};
    }}
    QPushButton:pressed {{
        background-color: {_LIFTED};
    }}
    QPushButton:disabled {{
        color: {_DIM_TEXT};
    }}
    QDoubleSpinBox {{
        background-color: {PANEL};
        color: {TEXT};
        border: {BORDER_WIDTH}px solid {BORDER_COLOR};
        border-radius: {BORDER_RADIUS}px;
        padding: 3px 6px;
        selection-background-color: {PRIMARY};
        selection-color: {BG_BASE};
    }}
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        background-color: {PANEL};
        border: none;
        border-radius: 4px;
        width: 16px;
    }}
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
        background-color: {_LIFTED};
    }}
    QProgressBar {{
        background-color: {PANEL};
        color: {TEXT};
        border: {BORDER_WIDTH}px solid {BORDER_COLOR};
        border-radius: {BORDER_RADIUS}px;
        text-align: center;
        min-height: 14px;
    }}
    QProgressBar::chunk {{
        background-color: {ACCENT};
        border-radius: 4px;
    }}
    QSlider::groove:horizontal {{
        height: {GROOVE_HEIGHT}px;
        background-color: {PANEL};
        border-radius: {GROOVE_HEIGHT // 2}px;
    }}
    QSlider::sub-page:horizontal {{
        background-color: {ACCENT};
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
        background-color: {PRIMARY};
    }}
    QScrollBar:vertical, QScrollBar:horizontal {{
        background-color: {BG_BASE};
        width: 10px;
        height: 10px;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background-color: {PANEL};
        border-radius: 4px;
        min-height: 24px;
        min-width: 24px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
        background-color: {_LIFTED};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0px;
        width: 0px;
    }}
    QLabel#frame_readout, QLabel#fps_readout {{
        font-family: "{DISPLAY_FONT_FAMILY}";
        font-weight: 600;
        font-size: {READOUT_FONT_SIZE_PX}px;
        color: {TEXT};
    }}
    QLabel#fps_readout {{
        font-size: {FPS_FONT_SIZE_PX}px;
    }}
    """


def _palette() -> QPalette:
    """The Fusion palette: every role the native painting and the custom
    painters (``KeyStrip``) read, in the approved tones."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_BASE))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(PANEL))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_BASE))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(_DIM_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(PANEL))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(PRIMARY))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(BG_BASE))
    palette.setColor(QPalette.ColorRole.Accent, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(PANEL))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(_DIM_TEXT))
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


def apply_theme(app: QApplication) -> None:
    """Put the dark theme on the application, once, before any window builds.

    The order matters: Fusion first (its palette-aware drawing must be in
    place), then the palette (what painters read), then the stylesheet
    (what overrides shapes on top of it). Without Fusion, Windows' native
    style ignores half of the dark palette and the result is a patchwork.
    """
    app.setStyle("Fusion")
    app.setPalette(_palette())
    load_display_fonts(app)
    app.setFont(QFont(READ_FONT_FAMILY, READ_FONT_SIZE_PT))
    app.setStyleSheet(stylesheet())
