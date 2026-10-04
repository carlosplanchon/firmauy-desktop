# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""The values the whole app is drawn from. No Qt here, so it can be reasoned about and tested
as plain data.

Every name is semantic. There is no `blue600`, because the moment a component asks for a blue it
has decided something the design system should be deciding, and the dark scheme has nowhere to
answer.

The two anchors come from the application icon itself, sampled from it: the blue `#1e50a0` that
is 78% of its pixels, and the chip yellow `#f5c518` that is the other 17%. The rest is built
around them, aiming at serene civic infrastructure: institutional without pretending to be
official, sober, and legible before it is pretty.

Green, amber and red are reserved for verdicts and diagnostics. Nothing decorative may use them,
because the whole point of the Verificar screen is that its colour means something.
"""

from __future__ import annotations

from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"

# The two colours taken from assets/icon.png.
_ICON_BLUE = "#1e50a0"
_ICON_YELLOW = "#f5c518"

SCHEMES: dict[str, dict[str, str]] = {
    "light": {
        # Surfaces: warm white paper on a blue-grey desk. Never pure white on pure grey.
        "bg.app": "#eceff4",
        "bg.surface": "#fdfcfa",
        "bg.sunken": "#e2e7ee",                     # inputs, log panes
        "bg.hover": "#e4e9f0",
        # Text: near-black with a blue cast rather than #000.
        "fg.default": "#1b2430",
        "fg.muted": "#556075",
        "fg.faint": "#7d8798",
        "fg.on-accent": "#ffffff",
        "border.default": "#d3dae3",
        # 3:1 on every surface a control can sit on, not just on a card: WCAG 1.4.11 asks it
        # of a control boundary, and the radios in Diagnóstico sit on the app background.
        "border.strong": "#78848f",
        "border.focus": _ICON_BLUE,
        "accent.default": _ICON_BLUE,
        "accent.hover": "#245cb4",
        "accent.pressed": "#173f7d",
        "accent.subtle": "#dde6f6",
        "identity.default": _ICON_YELLOW,
        "identity.fg": "#3b2d00",
        # Verdicts only.
        "status.ok": "#136c34",
        "status.warn": "#8a5200",
        "status.bad": "#b3261e",
        "status.ok.bg": "#e3f2e8",
        "status.warn.bg": "#faefdc",
        "status.bad.bg": "#fbe6e5",
    },
    "dark": {
        "bg.app": "#161a21",
        "bg.surface": "#1e242d",
        "bg.sunken": "#11151a",
        "bg.hover": "#28303b",
        "fg.default": "#e7ebf1",
        "fg.muted": "#a7b1be",
        "fg.faint": "#78828f",
        "fg.on-accent": "#0c1420",
        "border.default": "#2f3742",
        "border.strong": "#63707d",     # same requirement, already clears it on all three
        "border.focus": "#7aa5ee",
        # The icon blue is too dark to read on a dark surface, so the accent lightens while the
        # identity yellow, which is already bright, does not.
        "accent.default": "#7aa5ee",
        "accent.hover": "#93b6f2",
        "accent.pressed": "#6690d8",
        "accent.subtle": "#1d2a3f",
        "identity.default": _ICON_YELLOW,
        "identity.fg": "#3b2d00",
        "status.ok": "#63d18d",
        "status.warn": "#e8b451",
        "status.bad": "#f2867f",
        "status.ok.bg": "#16301f",
        "status.warn.bg": "#302510",
        "status.bad.bg": "#331b1a",
    },
}

# Spacing, in logical pixels. A scale rather than whatever number felt right at the time: the app
# had nine unrelated magic values and no rhythm at all.
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
RADIUS = {"sm": 4, "md": 8, "lg": 12}

# Multipliers against the platform's own default font size, never absolute points. A flat 18pt
# verdict is 2x on a 9pt Windows default and 1.4x on a 13pt macOS one: the same screen, visibly
# different proportions.
TYPE = {"caption": 0.85, "body": 1.0, "subtitle": 1.15, "title": 1.4, "verdict": 1.9}

ICON = {"sm": 14, "md": 18, "lg": 24, "nav": 20, "verdict": 28}

# What a status means, not what colour it is, so one map serves both schemes.
STATUS_TONE = {
    "PASS": "ok", "VALID": "ok",
    "WARN": "warn", "INDETERMINATE": "warn",
    "FAIL": "bad", "INVALID": "bad",
}

# Icon names, not glyphs. Colour-font emoji ignore `color:`, which splits status colour into
# two incompatible systems at once.
#
# Both vocabularies, exactly like STATUS_TONE: firmauy says PASS/WARN/FAIL about the environment
# and VALID/INDETERMINATE/INVALID about a signature, and a map that only knew one of them left
# the verdict, the most important thing this app says, showing the neutral fallback dot.
STATUS_ICON = {
    "PASS": "check", "VALID": "check",
    "WARN": "warning", "INDETERMINATE": "warning",
    "FAIL": "cross", "INVALID": "cross",
}

# What the icon says out loud. Without this a check row conveys whether it passed **only** through
# its icon: the name and the detail read the same for a check that passed and one that failed, so
# a screen reader announced "La firma es criptográficamente válida" either way. WCAG 1.4.1 asks
# that colour never be the only carrier, and an uncaptioned icon is the same failure.
STATUS_SPOKEN = {
    "PASS": "correcto", "VALID": "correcto",
    "WARN": "advertencia", "INDETERMINATE": "advertencia",
    "FAIL": "falla", "INVALID": "falla",
}


def palette_for(scheme: str) -> dict[str, str]:
    return dict(SCHEMES.get(scheme, SCHEMES["light"]))


def type_scale(base_pt: float) -> dict[str, float]:
    """The type sizes for a platform whose default font is ``base_pt``, to half a point."""
    return {name: round(base_pt * ratio * 2) / 2 for name, ratio in TYPE.items()}


def qss_variables(scheme: str, base_pt: float) -> dict[str, str]:
    """Everything the stylesheet template can substitute.

    Dots become underscores because `string.Template` only accepts identifier characters, so a
    token reads `$bg_app` in the QSS and `bg.app` everywhere else.
    """
    values = {name.replace(".", "_").replace("-", "_"): value
              for name, value in palette_for(scheme).items()}
    values |= {f"space_{name}": str(size) for name, size in SPACE.items()}
    values |= {f"radius_{name}": str(size) for name, size in RADIUS.items()}
    values |= {f"type_{name}": f"{size:g}" for name, size in type_scale(base_pt).items()}
    # Qt cannot tint a QSS `image:`, and the tick on a filled indicator has to read against
    # the accent, so the two baked-colour files are picked here instead.
    values["icons"] = str(ICON_DIR.as_posix())
    values["icon_check_on_accent"] = (
        f"{ICON_DIR.as_posix()}/check-on-accent-{'dark' if scheme == 'dark' else 'light'}.svg")
    return values


# --- contrast, so the palette is checked rather than admired ----------------

def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(colour: str) -> float:
    """WCAG relative luminance of a `#rrggbb` string."""
    raw = colour.lstrip("#")
    r, g, b = (int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio, 1.0 (identical) to 21.0 (black on white)."""
    a, b = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)
