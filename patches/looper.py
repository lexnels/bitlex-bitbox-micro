"""Live Loop pads (see src/looper.c). Apply together with `mod` and `cave`."""
import struct

from thumb import hooker, symbols

hook = hooker(symbols())

PATCHES = [
    hook(0x080B25D6, 0x080AEC34, "loop_voice_render"),   # sample pads: per-voice render
    # pad settings pages (Launch Mode, Output, ..., Pad Note): + Live Loop at the end. Every variant of the page, one per
    # pad type (3, 0x45) and play mode: they all belong to the two store types that carry Live Loop (mod_pad_store).
    (0x080C6BEA, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
    (0x080C6E06, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
    (0x080C70BA, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
    (0x080C72D6, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
    (0x080C7892, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
    (0x080C7AAE, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
    (0x080C7CC8, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
    (0x080C7FF6, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
    (0x080C8214, struct.pack("<H", 0), struct.pack("<H", 0x17C)),
]
