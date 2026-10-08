"""Live Loop pads (see src/looper.c). Apply together with `mod` and `cave`."""
import struct

from thumb import hooker, symbols

hook = hooker(symbols())

PATCHES = [
    hook(0x080B25D6, 0x080AEC34, "loop_voice_render"),   # sample pads: per-voice render
    # pad settings page (Launch Mode, Output, Poly Mode, Excl Group, Interp, MIDI In, ...): + Live Loop at the end
    (0x080C7892, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
    (0x080C7AAE, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
]
