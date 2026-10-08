"""Fidelity (Interp list: machine modes + crunch) and the 24 dB state-variable filter with drive (see src/filter.c).
Apply together with `cave`."""
from thumb import hooker, symbols

hook = hooker(symbols())

PATCHES = [
    hook(0x0806B34A, 0x08069E7C, "interp_register"),   # parameter 0xd2: Interp list 2 -> 14 entries, "Fidelity:"
    hook(0x080AD960, 0x080B8420, "filter_voice_a"),    # sample voices: per-voice filter
    hook(0x080B5CCC, 0x080B8420, "filter_voice_b"),    # slicer voices: per-voice filter
    # machine modes: park pad / position / rate on the way into the sample reader, then swap its two kernels
    *[hook(a, 0x080ADC4C, "voice_read") for a in (0x080AEE92, 0x080AF0D8, 0x080AF19A)],
    *[hook(a, 0x080A1400, "read_normal") for a in (0x080ADF00, 0x080ADF24, 0x080ADF48)],
    *[hook(a, 0x080A1494, "read_hq") for a in (0x080ADD4C, 0x080ADDD8, 0x080ADDFC)],
]
