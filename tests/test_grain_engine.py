"""Grain Sync with the real grain engine under Unicorn: a held note keeps sounding, also across Density changes.

Real firmware runs for: the grain render FUN_080af8b4, the grain spawn FUN_080af5a0 (through grain_spawn), the Density
change FUN_080b0b24. Stubbed: the sample read (constant 1.0), the parameter registry.
NOT checked: the voice render around them (FUN_080afaf0: playhead, Speed), the UI (hardware).
Each run holds one granular voice for 4000 blocks, changes Density at blocks 1000, 2000 and 3000, and counts the share
of blocks with sound in the last 750. Beat sync has to keep sounding wherever Free does.
"""
import struct
import sys

from common import IMAGE, Checker
from emu import Emu

c = Checker()
N = 128
APP_PADS, ARR = 0x24013CB0 + 0x1840, 0x24072000
PAD, VOICE, GR, WAVE, NOW, TR = 0x24060000, 0x24062000, 0x24064000, 0x24065000, 0x24066000, 0x24030000
RD, RD_L, RD_R = 0x24067000, 0x24067100, 0x24067500
OUT, OUT_L, OUT_R = 0x24068000, 0x24068100, 0x24068500


def run(sync, densities):
    e = Emu(IMAGE, "out/cave.elf")

    def read2():
        l, r, n = e.arg(1), e.arg(2), e.arg(3)
        e.wr(l, struct.pack(f"<{n}f", *([1.0] * n)))
        e.wr(r, struct.pack(f"<{n}f", *([1.0] * n)))
        e.ret(1)

    e.stub(0x080A44C8, read2)
    e.stub(0x08069ED4)
    e.stub(0x08069E7C)
    e.call("grain_register", 0x24001000)
    addr, arr = APP_PADS + 1 * 0xF0 + 2 * 0x30, ARR + 0x100 * 7          # pad row 1, column 2: Beat or Free, 1/16
    e.wr(arr, struct.pack("<HHiHHi", 0x17E, 0, sync, 0x17F, 0, 7))
    e.w32(addr + 4, arr)
    e.w16(addr + 10, 2)
    e.w16(addr + 12, 64)
    e.wr(PAD, bytes(0x600))
    e.wr(VOICE, bytes(0x600))
    e.wr(GR, bytes(0x200))
    e.w32(PAD + 0x18, 1 << 8 | 2)
    e.w32(PAD + 0x6C, 1)                              # one voice in the pad's voice list
    e.w32(PAD + 0x2C, VOICE)
    e.w32(PAD + 0x578, 4)                             # grains
    e.w32(PAD + 0x57C, 2048)                          # grain length
    e.wf(PAD + 0x58C, 0.5)                            # Density
    e.w8(VOICE, 1)
    e.w32(VOICE + 0xC, WAVE)
    e.w32(WAVE + 0x10, 480000)
    e.w32(VOICE + 0x10, 10000)                        # playhead
    e.wf(VOICE + 0x13C, 1.0)                          # grain read rate
    e.w32(VOICE + 0x138, GR)
    now = 1_000_000
    e.wr(NOW, struct.pack("<q", now))
    e.wr(VOICE + 0x530, struct.pack("<q", now))
    for i in range(4):                                # note on: every slot spawned the stock way
        e.call(0x080AF5A0, PAD, NOW, VOICE, 0, stack_args=(0, GR + i * 0x40))
    sound = []
    for k in range(4000):
        e.wr(TR, struct.pack("<qqqf", now, 0, 0, 120.0))
        e.call("grain_clock", TR, N)
        e.wr(NOW, struct.pack("<q", now))
        e.wr(OUT, struct.pack("<iiIIBB", N, N, OUT_L, OUT_R, 0, 1))
        e.wr(OUT_L, bytes(4 * N))
        for i in range(8):
            e.w32(PAD + 0x5A8, 0)
            e.wr(RD, struct.pack("<iiIIBB", N + 8, N + 8, RD_L, RD_R, 0, 1))
            e.call(0x080AF8B4, PAD, NOW, VOICE, GR + i * 0x40, stack_args=(RD, 0, OUT))
        sound.append(max(abs(x) for x in struct.unpack(f"<{N}f", e.rd(OUT_L, 4 * N))) > 1e-3)
        if k in (1000, 2000, 3000):
            e.wf(PAD + 0x58C, densities[k // 1000 - 1])
            e.call(0x080B0B24, PAD, NOW)
        now += N
    return sum(sound[3250:]) / 750


for dens in ((0.4, 0.2, 0.45), (0.8, 0.9, 1.0), (0.9, 0.3, 0.6)):
    free, beat = run(0, dens), run(1, dens)
    c.check(f"Density {dens[0]} -> {dens[1]} -> {dens[2]}: a held Beat note still sounds (Free {free:.2f}, Beat {beat:.2f})",
            beat > 0.2 or free < 0.1, (free, beat))

sys.exit(c.done())
