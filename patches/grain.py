"""Granular controls (see src/grain.c): Shape, Grain Sync / Sync Rate, Position, and polyphony. Apply with `mod`,
`looper` and `cave`."""
import struct

from thumb import hooker, symbols

hook = hooker(symbols())
IDS = struct.pack("<4H", 0x17D, 0x17E, 0x17F, 0x180)       # Shape, Grain Sync, Sync Rate, Position

PATCHES = [
    hook(0x080AFAC8, 0x080AF5A0, "grain_spawn"),           # grain render: a finished grain spawns the next
    (0x080AFAE8, struct.pack("<I", 0x080CAC00), struct.pack("<I", 0x38008000)),   # grain window table -> MOD_RAM
    # granular pad page (Density, Grain Size, Window, Scatter, Pan Rnd, Speed): + the four after Speed, both variants
    (0x080C7054 + 12, bytes(8), IDS),
    (0x080C7270 + 12, bytes(8), IDS),
    # polyphony: the voice start FUN_080aff60 sends granular pads (pad + 0x575) down its mono path whatever Poly Mode
    # says; every voice has its own grains (FUN_080b8b1c), so the branch goes and Poly Mode (0x82) decides, as for
    # sample pads. Poly Mode joins the granular pad's page (Launch Mode, Output, ..., Live Loop), both variants.
    (0x080AFF9A, bytes.fromhex("7fd1"), bytes.fromhex("00bf")),   # bne 0x080b009c -> nop
    (0x080C70AE + 14, bytes(2), struct.pack("<H", 0x82)),
    (0x080C72CA + 14, bytes(2), struct.pack("<H", 0x82)),
]
