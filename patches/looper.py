"""Live Loop pads (see src/looper.c). Apply together with `mod` and `cave`."""
import struct

from thumb import hooker, symbols

hook = hooker(symbols())

PATCHES = [
    hook(0x080B25D6, 0x080AEC34, "loop_voice_render"),   # sample pads: per-voice render
    hook(0x080B7DCE, 0x080B5AA8, "loop_clip_render"),    # clip and slicer pads: voice A, B, B
    hook(0x080B7DEC, 0x080B5AA8, "loop_clip_render"),
    hook(0x080B7FB0, 0x080B5AA8, "loop_clip_render"),
    hook(0x080B5CB4, 0x080A3228, "loop_clip_chans"),     # in the clip render: the voice's channels
    hook(0x080B1468, 0x080AFAF0, "loop_grain_render"),   # granular pads: per-voice render
    hook(0x080AF962, 0x080A44C8, "loop_grain_read"),     # in the grain render: the grain's sample read
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
