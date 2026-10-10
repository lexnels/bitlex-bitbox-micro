"""Live Loop under Unicorn.

Real firmware runs for: the settings-store lookups, the dB -> gain table, the audio-buffer accessors, the in-memory
sample read (FUN_080a4500).
Stubbed: the SDRAM allocator (fixed buffers), the stock per-voice render and the voice's output stage (both record what
they were given), the voice modulation tick, and the engine's block process.
NOT checked: the real engine graph, stereo samples read through their provider, the UI (hardware).
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_SP

from common import IMAGE, Checker, bl_target
from emu import Emu

e = Emu(IMAGE, "out/cave.elf")
c = Checker()

APP = 0x24013CB0
APP_PADS, APP_REC = APP + 0x1840, APP + 0x7FD0
ENGINE = 0x24030000                     # the transport lives at the engine's start
CTX = ENGINE + 0x127D8
BUS0, BUS3 = CTX + 0x1588C, CTX + 0x158C8
IN_L, IN_R, RS_L, RS_R = 0x24070000, 0x24070400, 0x24070800, 0x24070C00
OUT, OUT_L, OUT_R, BLOCK = 0x24071000, 0x24071100, 0x24071500, 0x24071900
ARR = 0x24072000
PAD, PAD2, VOICE, VOICE2 = 0x24073000, 0x24074000, 0x24075000, 0x24076000
WAVE, WAVE_L = 0x24077000, 0xC1000000
N = 128
TEMPO = 120.0

# --- stubs
bufs = iter((0xC0000000 + (i % 4) * 0x400000) for i in range(1000))   # boot runs again for every test section
e.stub(0x08042DC0, lambda: e.ret(next(bufs)))
stock_render, stage = [], []
e.stub(0x080AEC34, lambda: stock_render.append(e.arg(0)))


def stage_fn():
    out = e.arg(2)
    l, r = e.r32(out + 8, False), e.r32(out + 12, False)
    stage.append((e.arg(0), e.arg(1), list(struct.unpack(f"<{N}f", e.rd(l, 4 * N))),
                  list(struct.unpack(f"<{N}f", e.rd(r, 4 * N)))))


e.stub(0x080AD870, stage_fn)
e.stub(0x080BA3E4, lambda: None)


def store(addr, arr, entries):
    blob = b"".join(struct.pack("<HHi", k, 0, v) for k, v in entries.items())
    e.wr(arr, blob)
    e.w32(addr + 4, arr)
    e.w16(addr + 10, len(entries))
    e.w16(addr + 12, 64)


def pad_store(row, col, mode, length=1, source=0):
    store(APP_PADS + row * 0xF0 + col * 0x30, ARR + 0x100 * (row * 5 + col),
          {0xD2: 0, 0x17C: mode, 0x79: length, 0x7C: source})


def rec_store(length=1, source=0, gain=0, per_pad=0):
    store(APP_REC, 0x24078000, {0x79: length, 0x7C: source, 0xBA: gain, 0xC2: per_pad})


def clear_pads():
    for i in range(20):
        e.w16(APP_PADS + (i // 5) * 0xF0 + (i % 5) * 0x30 + 10, 0)


def transport(now, anchor_ticks=0, anchor_samples=0, tempo=TEMPO):
    e.wr(ENGINE, struct.pack("<qqqf", now, anchor_ticks, anchor_samples, tempo))
    e.w32(CTX, ENGINE)


def bus(addr, l, r, n=N, silent=0, stereo=1):
    e.wr(addr, struct.pack("<iiIIBB", n, n, l, r, silent, stereo))


def enc(x):
    """A sample number as a level the 16-bit loop stores exactly (0.03 .. 0.46, so two overdubbed passes don't clip)."""
    return float(x % 14000 + 1000) / 32768.0


def set_input(block):
    """Input sample k (absolute) = enc(k + 1) (L), -enc(k + 1) (R): every sample tells where it came from."""
    base = block * N
    e.wr(IN_L, struct.pack(f"<{N}f", *[enc(base + i + 1) for i in range(N)]))
    e.wr(IN_R, struct.pack(f"<{N}f", *[-enc(base + i + 1) for i in range(N)]))


def voice(addr, pad, row, col, wave=WAVE):
    e.w32(pad + 0x18, row << 8 | col)
    e.w8(addr, 1)
    e.w32(addr + 0xC, wave)


def mono_wave(values):
    e.wr(WAVE, bytes(0x30))
    e.w32(WAVE + 4, WAVE_L)
    e.w32(WAVE + 0x10, len(values))
    e.wr(WAVE_L, struct.pack(f"<{len(values)}f", *values))


def render(pad=PAD, v=VOICE):
    e.wr(OUT, struct.pack("<iiIIBB", N, N, OUT_L, OUT_R, 1, 0))
    e.wr(BLOCK, struct.pack("<iiIIBB", N, N, 0, 0, 0, 0))
    stage.clear()
    stock_render.clear()
    e.call("loop_voice_render", pad, v, 0, 0, stack_args=(OUT, BLOCK))


def block(k, render_pads=((PAD, VOICE),), now0=0):
    transport(now0 + k * N)
    set_input(k)
    e.call("looper_block", CTX, N)
    outs = []
    for p, v in render_pads:
        render(p, v)
        outs.append((list(stage), list(stock_render)))
    e.call("looper_after", CTX, N)
    return outs


# --- patched call sites and pages
img = e.image
for at, name in [(0x0806B34A, "mod_register"), (0x0809418A, "engine_block"), (0x08089740, "mod_pad_store"),
                 (0x08089960, "mod_pad_store"), (0x080B25D6, "loop_voice_render")]:
    c.check(f"bl at {at:#x} -> {name}", bl_target(img, at) == e.sym[name] & ~1)
LL_PAGES = [0x080C6BEA, 0x080C6E06, 0x080C70BA, 0x080C72D6, 0x080C7892, 0x080C7AAE, 0x080C7CC8, 0x080C7FF6, 0x080C8214]
c.check("all nine pad settings page variants end with Live Loop (0x17c) after Pad Note",
        all(e.r16(a) == 0x17C and e.r16(a - 2) == 0xD6 and e.r16(a + 2) == 0 for a in LL_PAGES))

# --- boot: no memory taken (the samples may already fill it); buffers come on first use
e.w32(0x24000088, 0xC0000000)                         # SDRAM: bump allocator bottom, sample allocator top
e.w32(0x2400008C, 0xC4000000)
e.call("looper_boot")
c.check("boot takes no loop memory", [e.r32(0x38000040 + 4 * i, False) for i in range(2)] == [0] * 2)
bus(BUS0, IN_L, IN_R)
bus(BUS3, RS_L, RS_R)
rec_store(length=1)                                   # Length 1/4 (one beat): 24000 frames at 120 BPM
clear_pads()
LEN = 24000

# --- off: stock render
pad_store(1, 2, 0)
voice(VOICE, PAD, 1, 2)
mono_wave([0.5] * LEN)
out = block(0)
c.check("Live Loop Off: the stock voice render runs", out[0][1] == [PAD] and not out[0][0])

# --- replace: what plays is what came in one loop earlier
pad_store(1, 2, 1)
waveval = [1000.0 + i for i in range(LEN)]
mono_wave(waveval)
k0 = 0
out = block(k0)                                       # first block: the voice sees the sample, the loop restarts from it
c.check("Live Loop on: the stock render is skipped, the voice stage gets the loop", out[0][1] == [] and len(out[0][0]) == 1)
blocks = LEN // N * 2 + 40
ok_first, ok_after, bad = True, True, None
for k in range(1, blocks):
    if k % 64 == 0:
        print(f"     block {k}/{blocks}", end="\r")
    st, sr = block(k)[0]
    l, r = st[0][2], st[0][3]
    for i in range(N):
        t = k * N + i
        ph = t % LEN
        cycle = t // LEN
        first = t < N + LEN                           # the voice first saw the sample in block 0: one loop from block 1
        if first:
            exp_l = exp_r = waveval[ph]
        else:
            exp_l, exp_r = enc(t - LEN + 1), -enc(t - LEN + 1)
        if abs(l[i] - exp_l) > 1e-3 or abs(r[i] - exp_r) > 1e-3:
            if first:
                ok_first = False
            else:
                ok_after = False
            bad = bad or (k, i, l[i], exp_l, r[i], exp_r)
c.check("first pass plays the pad's sample at the loop position (mono sample on both sides)", ok_first, bad)
c.check("after that, Replace plays exactly the input from one loop (24000 frames) earlier, L and R", ok_after, bad)

# --- the loop is locked to the song position, not to when the pad started
SLOT0 = 0x38000100 + 32                               # struct looper: magic, block, frames, pad_slot[20]
loop_l = e.r32(SLOT0 + 20, False)                     # slot 0: pad, mode, len, prefill, wave, played, l, r
transport(5 * N, anchor_ticks=480, anchor_samples=0)  # half a beat in at sample 0: song position = 12000 + now
set_input(5)
e.call("looper_block", CTX, N)
first_in = struct.unpack("<h", e.rd(loop_l + (12000 + 5 * N) % LEN * 2, 2))[0] / 32768.0
c.check("loop position = (anchor ticks x samples per tick + now - anchor samples) mod length",
        abs(first_in - enc(5 * N + 1)) < 1e-6, first_in)

# --- overdub: each pass adds
clear_pads()
e.call("looper_boot")
pad_store(1, 2, 2)
mono_wave([0.0] * LEN)
rec_store(length=1)
results = {}
for k in range(0, 3 * LEN // N + 4):
    st, _ = block(k)[0]
    for i in range(N):
        results[k * N + i] = st[0][2][i] if st else None
t = 2 * LEN + 1000
c.check("Overdub: pass 3 plays pass 1 + pass 2 input", abs(results[t] - (enc(t - LEN + 1) + enc(t - 2 * LEN + 1))) < 1e-6,
        (results[t], enc(t - LEN + 1) + enc(t - 2 * LEN + 1)))

# --- sources: In 1 on both sides, Resam = what bus 3 held a block earlier
clear_pads()
e.call("looper_boot")
pad_store(1, 2, 1)
rec_store(length=1, source=1)
mono_wave([0.0] * LEN)
for k in range(0, LEN // N + 3):
    e.wr(RS_L, struct.pack(f"<{N}f", *[0.25] * N))
    e.wr(RS_R, struct.pack(f"<{N}f", *[0.375] * N))
    st, _ = block(k)[0]
t = (LEN // N + 2) * N
c.check("Rec Input In 1: input L recorded on both sides", abs(st[0][2][0] - enc(t - LEN + 1)) < 1e-6 and
        abs(st[0][3][0] - enc(t - LEN + 1)) < 1e-6, (st[0][2][0], st[0][3][0]))
clear_pads()
e.call("looper_boot")
pad_store(1, 2, 1)
rec_store(length=1, source=3)
for k in range(0, LEN // N + 3):
    st, _ = block(k)[0]
c.check("Rec Input Resam: records the master bus", st[0][2][5] == 0.25 and st[0][3][5] == 0.375, (st[0][2][5], st[0][3][5]))

# --- gain: Rec Gain -6 dB halves the input
clear_pads()
e.call("looper_boot")
pad_store(1, 2, 1)
rec_store(length=1, gain=-6021)
for k in range(0, LEN // N + 3):
    st, _ = block(k)[0]
t = (LEN // N + 2) * N
c.check("Rec Gain applies (-6 dB -> x0.5)", abs(st[0][2][0] / enc(t - LEN + 1) - 0.5) < 0.01, st[0][2][0] / enc(t - LEN + 1))

# --- per-pad recording settings (RecConfig Per Pad): the pad's own Length
clear_pads()
e.call("looper_boot")
pad_store(1, 2, 1, length=2)                          # 1/2 = two beats = 48000 frames
rec_store(length=1, per_pad=1)
block(0)
c.check("RecConfig Per Pad: the pad's Length (1/2 -> 48000 frames)", e.r32(SLOT0 + 4) == 48000, e.r32(SLOT0 + 4))

# --- a second voice of the same pad stays silent; a fifth looping pad gets stock playback
clear_pads()
e.call("looper_boot")
rec_store(length=1)
for i, (row, col) in enumerate([(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]):
    pad_store(row, col, 1)
voice(VOICE, PAD, 0, 0)
voice(VOICE2, PAD2, 0, 0)
outs = block(0, render_pads=((PAD, VOICE), (PAD, VOICE2)))
c.check("two voices of one pad: the second plays silence", outs[1][0] and all(v == 0.0 for v in outs[1][0][0][2]))
voice(VOICE2, PAD2, 0, 4)
outs = block(1, render_pads=((PAD2, VOICE2),))
c.check("a fifth Live Loop pad (four loops in use) plays stock", outs[0][1] == [PAD2])

# --- too long for a loop buffer: stock
clear_pads()
e.call("looper_boot")
pad_store(1, 2, 1, length=8)                          # 32 bars at 120 BPM = 64 s
rec_store(length=8)
voice(VOICE, PAD, 1, 2)
outs = block(0)
c.check("a loop longer than the loop memory (5.4 s): stock playback", outs[0][1] == [PAD])

# --- engine_block: looper before, engine, looper after
order = []
e.stub(0x08096530, lambda: order.append("engine"))
transport(0)
e.call("engine_block", ENGINE, 0, 0)
c.check("engine_block runs the engine's block process once", order == ["engine"])

# --- Live Loop list registration
seen = {}
e.stub(0x08069E7C, lambda: seen.setdefault(e.arg(1), (e.cstr(e.arg(2)), e.r32(e.uc.reg_read(UC_ARM_REG_SP)),
                                                        [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(3)],
                                                        e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4)))))
e.call("looper_register", 0x24001000)
c.check("Live Loop list: 0x17c 'Live Loop:' Off / Replace / Overdub, xml 'liveloop'",
        seen.get(0x17C) == ("Live Loop:", 3, ["Off", "Replace", "Overdub"], "liveloop"), seen.get(0x17C))

# --- memory: one block for all loops, only while 3 MB stay free for the firmware
e.call("looper_boot")
e.w32(0x2400008C, 0xC0000000 + (4 << 20) - 16)        # just under 1 MB + 3 MB free: no loop memory
clear_pads()
pad_store(0, 0, 1)
transport(0)
e.call("looper_block", CTX, N)
c.check("too little free memory: no loop memory taken", e.r32(0x38000040, False) == 0)
e.w32(0x2400008C, 0xC0000000 + (7 << 20))             # 7 MB free (a real unit): 4 MB, 262144 frames per loop
e.call("looper_block", CTX, N)
c.check("7 MB free: 4 MB taken, 5.4 s per loop", e.r32(0x38000040, False) != 0 and e.r32(0x38000044, False) == 262144,
        e.r32(0x38000044, False))
e.w32(0x2400008C, 0xC4000000)
sys.exit(c.done())
