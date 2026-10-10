"""Fidelity list only (src/filter.c interp_register), without the rest of mod.py: a bisection build for hardware
bring-up. Don't combine with mod."""
from thumb import hooker, symbols

hook = hooker(symbols())

PATCHES = [
    hook(0x0806B34A, 0x08069E7C, "interp_register"),
]
