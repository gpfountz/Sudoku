# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

"""Toolkit-independent light and dark color specifications for named Sudoku themes."""

from dataclasses import dataclass

ACCENT_PALETTES: dict[str, tuple[str, str]] = {
    "Default Teal": ("00635D", "70D5CA"),
    "Default Forest": ("28663F", "8CD6A0"),
    "Default Plum": ("75458C", "D4ACED"),
    "Default Bronze": ("79500F", "E4BD75"),
    "Default Olive": ("58621E", "C0CE80"),
    "Default Espresso": ("6D4C3C", "DCB59D"),
    "Default Graphite": ("50545A", "B9C0C9"),
    "Default Orchid": ("843E7C", "E4A5DA"),
}


@dataclass(frozen=True)
class Palette:
    """Store opaque sRGB colors for surfaces, ink, controls, hints, and incorrect answers."""

    board: str
    window: str
    text: str
    secondary_text: str
    accent: str
    control: str
    border: str
    selected_text: str
    evidence: str
    incorrect_answer: str


@dataclass(frozen=True)
class PalettePair:
    """Pair appearance variants with optional contrast cues and legacy pressed colors."""

    light: Palette
    dark: Palette
    high_contrast: bool = False
    pressed: tuple[str, str] | None = None


# Name every color role explicitly; keep the published preview colors stable.
PALETTES: dict[str, PalettePair] = {
    "Warm Paper": PalettePair(
        light=Palette(
            board="FFF9EC",
            window="F7F0E2",
            text="302A23",
            secondary_text="706657",
            accent="965326",
            control="F1E6D2",
            border="B8A68C",
            selected_text="FFF9EC",
            evidence="A96724",
            incorrect_answer="FF0000",
        ),
        dark=Palette(
            board="29251F",
            window="25211C",
            text="F3EBDD",
            secondary_text="C7B9A5",
            accent="DDA35E",
            control="40372C",
            border="87735B",
            selected_text="261E16",
            evidence="F0B66D",
            incorrect_answer="FF4545",
        ),
        pressed=("E5CFAB", "6A5036"),
    ),
    "Sage Linen": PalettePair(
        light=Palette(
            board="F8FAF2",
            window="EDF2E7",
            text="26332B",
            secondary_text="536456",
            accent="386348",
            control="E3EBDC",
            border="A1B39D",
            selected_text="F8FAF2",
            evidence="A9651F",
            incorrect_answer="FF0000",
        ),
        dark=Palette(
            board="202B24",
            window="171F1A",
            text="E5EDE4",
            secondary_text="B4C5B7",
            accent="97C69C",
            control="304135",
            border="6B8973",
            selected_text="18271C",
            evidence="E9B66F",
            incorrect_answer="FF4545",
        ),
    ),
    "Coastal Mist": PalettePair(
        light=Palette(
            board="F3F9F8",
            window="EAF1F1",
            text="263639",
            secondary_text="51666A",
            accent="28656E",
            control="DFEBEC",
            border="9BB4B8",
            selected_text="F3F9F8",
            evidence="A15D23",
            incorrect_answer="FF0000",
        ),
        dark=Palette(
            board="1D2B2F",
            window="172124",
            text="DFECEC",
            secondary_text="ACC5C9",
            accent="88C4CC",
            control="2C4047",
            border="648A94",
            selected_text="14292F",
            evidence="EDB87C",
            incorrect_answer="FF4545",
        ),
    ),
    "Lavender Slate": PalettePair(
        light=Palette(
            board="F9F7FC",
            window="F0EDF5",
            text="342E42",
            secondary_text="695D79",
            accent="69508B",
            control="E7E0EF",
            border="B2A4C5",
            selected_text="F9F7FC",
            evidence="95601E",
            incorrect_answer="FF0000",
        ),
        dark=Palette(
            board="282332",
            window="211D29",
            text="EDE5F4",
            secondary_text="C4B6D4",
            accent="BCA6DE",
            control="3B334B",
            border="8A79A3",
            selected_text="291D3B",
            evidence="E7BD82",
            incorrect_answer="FF4545",
        ),
    ),
    "Tangerine Cream": PalettePair(
        light=Palette(
            board="FFF6E7",
            window="FCEBD4",
            text="33261C",
            secondary_text="785B43",
            accent="AD4E12",
            control="F7DEC0",
            border="B99570",
            selected_text="FFF6E7",
            evidence="654CAE",
            incorrect_answer="FF0000",
        ),
        dark=Palette(
            board="2C2118",
            window="201A15",
            text="FCEADA",
            secondary_text="D2B8A0",
            accent="FFAB66",
            control="463124",
            border="AC805B",
            selected_text="2B190E",
            evidence="C2AFE8",
            incorrect_answer="FF4545",
        ),
    ),
    "Rose Clay": PalettePair(
        light=Palette(
            board="FFF6F1",
            window="F7ECE5",
            text="432F2B",
            secondary_text="7B5E56",
            accent="98514C",
            control="F0DDD4",
            border="C5A497",
            selected_text="FFF6F1",
            evidence="8D6821",
            incorrect_answer="FF0000",
        ),
        dark=Palette(
            board="302421",
            window="281E1C",
            text="F3E5DE",
            secondary_text="D0B9AE",
            accent="DDA39A",
            control="493430",
            border="9F786B",
            selected_text="321E1B",
            evidence="E6BE7C",
            incorrect_answer="FF4545",
        ),
    ),
    "Peony Pink": PalettePair(
        light=Palette(
            board="FFF5F9",
            window="F8E8F0",
            text="3F2534",
            secondary_text="795467",
            accent="A82F6B",
            control="F0D8E5",
            border="B68DA3",
            selected_text="FFF5F9",
            evidence="89610E",
            incorrect_answer="FF0000",
        ),
        dark=Palette(
            board="32202D",
            window="261922",
            text="F9E5F0",
            secondary_text="D6B5C7",
            accent="F0A3C8",
            control="4F3144",
            border="A47894",
            selected_text="361D2A",
            evidence="E6C775",
            incorrect_answer="FF4545",
        ),
    ),
    "High Contrast": PalettePair(
        light=Palette(
            board="FFFFFF",
            window="F2F2F2",
            text="000000",
            secondary_text="111111",
            accent="003C94",
            control="FFFFFF",
            border="111111",
            selected_text="FFFFFF",
            evidence="633000",
            incorrect_answer="BF0000",
        ),
        dark=Palette(
            board="000000",
            window="0C0C0C",
            text="FFFFFF",
            secondary_text="FFFFFF",
            accent="FFE066",
            control="141414",
            border="FFFFFF",
            selected_text="000000",
            evidence="5FE2FF",
            incorrect_answer="FF6262",
        ),
        high_contrast=True,
    ),
    "Autumn Harvest": PalettePair(
        light=Palette(
            board="FFF4E2",
            window="F5E6CE",
            text="3E3022",
            secondary_text="78634A",
            accent="985025",
            control="EED8B7",
            border="B49D7A",
            selected_text="FFF7EA",
            evidence="526633",
            incorrect_answer="FF0000",
        ),
        dark=Palette(
            board="2C2319",
            window="211A12",
            text="F6E9D5",
            secondary_text="D2BDA1",
            accent="E5AE62",
            control="463523",
            border="927554",
            selected_text="2F2213",
            evidence="B6C78A",
            incorrect_answer="FF4545",
        ),
    ),
    "Winter Frost": PalettePair(
        light=Palette(
            board="F4FAFF",
            window="E6EFF7",
            text="233547",
            secondary_text="546B82",
            accent="285E91",
            control="DAE8F3",
            border="91ADC3",
            selected_text="F4FAFF",
            evidence="8D5790",
            incorrect_answer="FF0000",
        ),
        dark=Palette(
            board="1C2935",
            window="14202C",
            text="E4F1FB",
            secondary_text="B5CBDD",
            accent="9BCBF2",
            control="2A3F52",
            border="6A8FAC",
            selected_text="142B3D",
            evidence="D7B1E4",
            incorrect_answer="FF4545",
        ),
    ),
}
