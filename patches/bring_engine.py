"""Bring-up test 6: Fidelity + the per-block engine hook (touches SRAM4 every block). No loop memory, no parameter."""
from thumb import hooker, symbols

hook = hooker(symbols())

PATCHES = [
    hook(0x0806B34A, 0x08069E7C, "interp_register"),
    hook(0x0809418A, 0x08096530, "engine_block"),
]
