"""Granular controls under Unicorn: Shape, Grain Sync / Sync Rate, Position.

Real firmware runs for: the grain render FUN_080af8b4 (its window lookup through the patched literal, gains, mixing).
Stubbed: the sample read FUN_080a44c8 (writes a constant 1.0, or records where it was asked to read), the stock grain
spawn FUN_080af5a0 (sets the new grain's start), the parameter registry.
NOT checked: the rest of the granular engine (grain scheduling, Density, Speed), the UI (hardware).
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_SP

from common import IMAGE, Checker, bl_target
from emu import Emu

e = Emu(IMAGE, "out/cave.elf")
c = Checker()
img = e.image
B = 0x08040000

APP = 0x24013CB0
APP_PADS = APP + 0x1840
ARR = 0x24072000
PAD, VOICE, GRAIN, WAVE = 0x24073000, 0x24075000, 0x24076000, 0x24077000
RD, RD_L, RD_R = 0x24071000, 0x24071100, 0x24071500
OUT, OUT_L, OUT_R = 0x24071A00, 0x24071B00, 0x24071F00
TR = 0x24030000
N = 128
STOCK = struct.unpack_from("<8192f", img, 0x080CAC00 - B)


def r32(a):
    return struct.unpack_from("<I", img, a - B)[0]


# --- patched sites
c.check("bl at 0x80afac8 -> grain_spawn", bl_target(img, 0x080AFAC8) == e.sym["grain_spawn"] & ~1)
c.check("grain window literal 0x80afae8 -> MOD_RAM table 0x38008000", r32(0x080AFAE8) == 0x38008000)
page = [struct.unpack_from("<10H", img, a - B) for a in (0x080C7054, 0x080C7270)]
c.check("both granular pad page variants: Density .. Speed, then Shape, Grain Sync, Sync Rate, Position",
        all(p == (0x160, 0x15C, 0x3E, 0x15E, 0x15F, 0x40, 0x17D, 0x17E, 0x17F, 0x180) for p in page), page)


def pad_store(row, col, **kv):
    ids = {"shape": 0x17D, "sync": 0x17E, "rate": 0x17F, "pos": 0x180}
    entries = {ids[k]: v for k, v in kv.items()}
    addr, arr = APP_PADS + row * 0xF0 + col * 0x30, ARR + 0x100 * (row * 5 + col)
    e.wr(arr, b"".join(struct.pack("<HHi", k, 0, v) for k, v in entries.items()))
    e.w32(addr + 4, arr)
    e.w16(addr + 10, len(entries))
    e.w16(addr + 12, 64)


# --- registration
seen = {}
e.stub(0x08069ED4, lambda: seen.setdefault(e.arg(1), ("num", e.cstr(e.arg(3)))))
e.stub(0x08069E7C, lambda: seen.setdefault(e.arg(1), ("list", e.cstr(e.arg(2)),
                                                       [e.cstr(e.r32(e.arg(3) + 4 * i, False))
                                                        for i in range(e.r32(e.uc.reg_read(UC_ARM_REG_SP)))])))
e.call("grain_register", 0x24001000)
c.check("registers Shape (0x17d), Grain Sync Free/Beat (0x17e), Sync Rate 1/64 .. 4 bars (0x17f), Position (0x180)",
        seen.get(0x17D) == ("num", "Shape:") and seen.get(0x17E) == ("list", "Grain Sync:", ["Free", "Beat"])
        and seen.get(0x17F) == ("list", "Sync Rate:", ["1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1 bar",
                                                       "2 bars", "4 bars"])
        and seen.get(0x180) == ("num", "Position:"), seen)
added = []
e.stub(0x0808951E, lambda: added.append((e.arg(1), e.arg(2))))
e.call("grain_pad_store", 0x24002000)
c.check("pad store defaults: Shape 50 %, Free, 1/16, Position 0", added == [(0x17D, 500), (0x17E, 0), (0x17F, 2),
                                                                        (0x180, 0)], added)
table = struct.unpack("<8192f", e.rd(0x38008000, 4 * 8192))
c.check("at boot the window table is the stock Hann window", table == STOCK)

# --- Shape, through the real grain render
reads = []


def read2():
    l, r, n, pos = e.arg(1), e.arg(2), e.arg(3), e.arg(4)
    reads.append((n, pos))
    e.wr(l, struct.pack(f"<{n}f", *([1.0] * n)))
    e.wr(r, struct.pack(f"<{n}f", *([1.0] * n)))
    e.ret(1)


e.stub(0x080A44C8, read2)
e.w32(PAD + 0x18, 1 << 8 | 2)                         # row 1, column 2
e.w8(VOICE, 1)
e.w32(VOICE + 0xC, WAVE)
e.w32(WAVE + 0x10, 48000)                             # 1 s sample


def grain_block(progress):
    e.wr(GRAIN, bytes(0x40))
    e.w8(GRAIN, 1)
    e.wf(GRAIN + 0x24, 1.0)                           # read rate
    e.w32(GRAIN + 0x2C, 100000)                       # frames left
    e.w32(GRAIN + 0x30, progress)
    e.w32(GRAIN + 0x34, 8192)                         # grain length: window index = progress
    e.w32(PAD + 0x5A8, 0)
    e.wr(RD, struct.pack("<iiIIBB", N + 8, N + 8, RD_L, RD_R, 0, 1))
    e.wr(OUT, struct.pack("<iiIIBB", N, N, OUT_L, OUT_R, 0, 1))
    e.wr(OUT_L, bytes(4 * N))
    e.wr(OUT_R, bytes(4 * N))
    e.call(0x080AF8B4, PAD, 0, VOICE, GRAIN, stack_args=(RD, 0, OUT))
    return struct.unpack(f"<{N}f", e.rd(OUT_L, 4 * N))


def shaped(shape):
    pad_store(1, 2, shape=shape)
    e.call("grain_prepare", PAD, 48000)
    out = []
    for start in (0, 2048, 4096, 8064):
        out += list(zip(range(start, start + N), grain_block(start)))
    return out


ref = shaped(500)
g = ref[N + 10][1] / STOCK[2048 + 10]                 # the render's pan gain
c.check("Shape 50 %: the grain render plays the stock window", g > 0 and all(abs(v - STOCK[i] * g) < 1e-5 for i, v in ref))


def pluck(x):
    return (min(x * 100, 1.0)) * (1 - x) ** 4


def swell(x):
    return (min((1 - x) * 100, 1.0) if x > 0.99 else 1.0) * x * x


for shape, f, name in ((0, pluck, "0 %: plucky, no attack, short release"),
                       (1000, swell, "100 %: swell, long attack, no decay")):
    out = shaped(shape)
    c.check(f"Shape {name}", all(abs(v - f(i / 8192) * g) < 1e-4 for i, v in out),
            [(i, v / g, f(i / 8192)) for i, v in out if abs(v - f(i / 8192) * g) >= 1e-4][:3])
out = shaped(250)
c.check("Shape 25 %: halfway between the plucky envelope and the stock window",
        all(abs(v - (0.5 * STOCK[i] + 0.5 * pluck(i / 8192)) * g) < 1e-4 for i, v in out))
pl = shaped(0)
c.check("Shape 0 %: loud at the grain's start, near silent by its middle", pl[100][1] > 0.5 * g and
        pl[2 * N + 10][1] < 0.1 * g)

# --- Position: the grains read further into the sample, wrapping around its end
pad_store(1, 2, pos=250)
off = e.call("grain_prepare", PAD, 48000)
c.check("Position 25 % of a 48000 frame sample: 12000 frames in", off == 12000, off)
reads.clear()
e.w32(0x38003888, 12000)
e.w32(0x38003884, 0)
e.call("loop_grain_read", WAVE, RD_L, RD_R, N, stack_args=(1000,))
e.call("loop_grain_read", WAVE, RD_L, RD_R, N, stack_args=(47000,))
e.w32(0x38003888, 0)
c.check("Position: a read at 1000 comes from 13000; one at 47000 from 11000 (wrapped)",
        reads == [(N, 13000), (N, 11000)], reads)
reads.clear()
e.w32(0x38003888, 47950)
e.call("loop_grain_read", WAVE, RD_L, RD_R, N, stack_args=(0,))
e.w32(0x38003888, 0)
c.check("Position: a read that runs past the end continues from the sample's start", reads == [(50, 47950), (78, 0)],
        reads)

# --- Grain Sync: a new grain starts on the next free step of the grid
spawned = []


def spawn():
    grain = e.arg(5)
    e.w8(grain, 1)
    e.w32(grain + 0x28, spawned.pop(0))
    e.ret()


e.stub(0x080AF5A0, spawn)


def transport(now, tempo=120.0):
    e.wr(TR, struct.pack("<qqqf", now, 0, 0, tempo))


def spawn_with(delay):
    spawned.append(delay)
    e.call("grain_spawn", PAD, 0, VOICE, 0, 0, stack_args=(0, GRAIN))
    return e.r32(GRAIN + 0x28)


transport(48000 * 3 + 100)                            # 120 BPM: 1/16 = 6000 frames; song at 144100
e.call("grain_clock", TR, N)
pad_store(1, 2, sync=0, rate=2)
c.check("Grain Sync Free: the stock start stays", spawn_with(700) == 700)
pad_store(1, 2, sync=1, rate=2)
d1 = spawn_with(700)                                  # wants 144800: next 1/16 step is 150000
d2 = spawn_with(50)                                   # wants 144150, step 150000 is taken: 156000
c.check("Grain Sync Beat 1/16: starts on the next step (150000 - 144100 = 5900 frames)", d1 == 5900, d1)
c.check("Grain Sync Beat: one grain per step, the next grain takes the following step (11900)", d2 == 11900, d2)
pad_store(1, 2, sync=1, rate=6)                       # 1 bar = 96000
d3 = spawn_with(0)
c.check("Sync Rate 1 bar: the next bar line (192000 - 144100)", d3 == 192000 - 144100, d3)
transport(48000 * 3 + 100 + N)                        # transport ran on one block
e.call("grain_clock", TR, N)
transport(48000 * 3 + 100 + N)                        # stalled for a block
e.call("grain_clock", TR, N)
song = struct.unpack("<d", e.rd(0x38003898, 8))[0]
c.check("Grain Sync clock runs on by itself when the transport stalls", song == 144100 + 2 * N, song)

sys.exit(c.done())
