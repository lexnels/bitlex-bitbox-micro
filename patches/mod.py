"""Base hooks every feature builds on (see src/mod.c): new parameters and memory at boot, the per-block engine hook,
and the mod's per-pad settings in the pad settings stores. Apply first, with `cave` last."""
import struct

from thumb import hooker, symbols

hook = hooker(symbols())

PATCHES = [
    hook(0x0806B34A, 0x08069E7C, "mod_register"),    # registry setup, at the Interp list: + Fidelity, Live Loop, ...
    hook(0x0809418A, 0x08096530, "engine_block"),    # audio task: the engine's block process
    hook(0x08089740, 0x0808951E, "mod_pad_store"),   # pad settings store (type 3): + Live Loop after Interp
    hook(0x08089960, 0x0808951E, "mod_pad_store"),   # pad settings store (type 0x45): + Live Loop after Interp
]
