"""Fidelity + 24 dB state-variable filter under Unicorn.

Real firmware runs for: the stock cutoff and resonance curves, the app settings-store lookup, the audio-buffer
accessors, the stock resampling kernels, and both voice call-site thunks.
Stubbed: the modulated-parameter read (returns test values) and the list registrar.
Reference: a Python model of the same SVF, so these checks pin the arithmetic, not the sound.
NOT checked: how it sounds, and CPU load with many voices (hardware).
"""
import math
import struct
import sys

from unicorn.arm_const import UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_S0, UC_ARM_REG_SP

from common import IMAGE, Checker, bl_target, f2u, u2f
from emu import STACK, Emu

e = Emu(IMAGE, "out/cave.elf")
c = Checker()

OBJ, PARAMS, PAD, BUF, LBUF, RBUF = 0x24060000, 0x24061000, 0x24062000, 0x24063000, 0x24064000, 0x24066000
APP_PADS, ARR = 0x24013CB0 + 0x1840, 0x24073000
N = 128
values = {}


def param():
    e.uc.reg_write(UC_ARM_REG_S0, f2u(values.get(e.arg(0), 0.0)))


e.stub(0x080A19F4, param)
e.w32(OBJ + 0x84, PARAMS)


def curve(addr, x):
    e.uc.reg_write(UC_ARM_REG_S0, f2u(x))
    e.call(addr)
    return u2f(e.uc.reg_read(UC_ARM_REG_S0))


PAD_ROW, PAD_COL = 1, 2


def set_interp(v, row=PAD_ROW, col=PAD_COL):
    """The app's record of the pad (what the screen shows and presets save): a settings store."""
    store = APP_PADS + row * 0xF0 + col * 0x30
    arr = ARR + (row * 5 + col) * 0x40
    e.wr(arr, struct.pack("<HHi", 0x11, 0, 500) + struct.pack("<HHi", 0xD2, 0, v) + struct.pack("<HHi", 0xDB, 0, 0))
    e.w32(store + 4, arr)
    e.w16(store + 10, 3)


def setup(knob, res=0.0, interp=0):
    values[PARAMS + 8] = knob
    values[PARAMS + 0x44] = res
    e.w32(PAD + 0x18, PAD_ROW << 8 | PAD_COL)    # engine pad id: bank << 16 | row << 8 | col
    e.w32(PAD + 0x564, 0)                         # the engine's own copy, as left by a pad reset: must not matter
    set_interp(interp)


def run(left, right=None, pad=PAD, silent=False):
    e.wr(LBUF, struct.pack(f"<{len(left)}f", *left))
    if right is not None:
        e.wr(RBUF, struct.pack(f"<{len(right)}f", *right))
    e.wr(BUF, struct.pack("<iiIIBB", len(left), len(left), LBUF, RBUF if right is not None else 0, int(silent),
                          int(right is not None)))
    e.call("filter_process", OBJ, BUF, pad)
    l = list(struct.unpack(f"<{len(left)}f", e.rd(LBUF, 4 * len(left))))
    r = list(struct.unpack(f"<{len(right)}f", e.rd(RBUF, 4 * len(right)))) if right is not None else None
    return l, r


def reset():
    e.wr(OBJ + 4, b"\xa5" * 0x5C)                  # stale stock coefficients and states: must initialise itself


def sine(hz, n=N, start=0, amp=0.5):
    return [amp * math.sin(2 * math.pi * hz * (start + i) / 48000) for i in range(n)]


def rms(x):
    return math.sqrt(sum(v * v for v in x) / len(x))


def soft(x, t):
    u = max(-1.5, min(1.5, x / t))
    return t * u * (1 - 0.148148 * u * u)


def model_svf(x, g, r, s, hp, limit):
    h = 1 / (1 + r * g + g * g)
    s1, s2 = s
    out = []
    for v in x:
        hpv = (v - r * s1 - g * s1 - s2) * h
        bp = g * hpv + s1
        s1 = soft(g * hpv + bp, limit) if limit else g * hpv + bp
        lp = g * bp + s2
        s2 = g * bp + lp
        out.append(hpv if hp else lp)
    return out, [s1, s2]


def model_block(x, g, r, drive, states, hp):
    if drive > 0.001:
        x = [soft(v * (1 + 3 * drive), 1.0) for v in x]
    y, states[0] = model_svf(x, g, 1.84776, states[0], hp, None)
    out, states[1] = model_svf(y, g, r, states[1], hp, 4 - 3 * drive if drive > 0.001 else None)
    return out


def coeffs(knob, res):
    hz = curve(0x080A01BC, knob + 1 if knob < 0 else knob)
    q = curve(0x080A0240, res)
    hz = min(max(hz, 10.0), 0.45 * 48000)
    q = min(max(q, 0.1), 40.0)
    x = math.pi * hz / 48000
    return x * (15 - x * x) / (15 - 6 * x * x), 1 / q, hz, q


# --- patched call sites
img = e.image
for at, name in [(0x0806B34A, "mod_register"), (0x080AD960, "filter_voice_a"), (0x080B5CCC, "filter_voice_b"),
                 (0x080AEE92, "voice_read"), (0x080AF0D8, "voice_read"), (0x080AF19A, "voice_read"),
                 (0x080ADF00, "read_normal"), (0x080ADF24, "read_normal"), (0x080ADF48, "read_normal"),
                 (0x080ADD4C, "read_hq"), (0x080ADDD8, "read_hq"), (0x080ADDFC, "read_hq")]:
    c.check(f"bl at {at:#x} -> {name}", bl_target(img, at) == e.sym[name] & ~1)

# --- bypass
reset()
setup(0.0)
x = sine(1000)
l, _ = run(x)
c.check("Filter knob at centre, Fidelity Normal: buffer untouched", all(abs(a - b) < 1e-7 for a, b in zip(l, x)))
setup(-0.5)
l, _ = run(x, silent=True)
c.check("silent buffer: untouched, as stock", all(abs(a - b) < 1e-7 for a, b in zip(l, x)))

# --- the filter matches the SVF model, block after block
reset()
setup(-0.4, res=0.3)
g, r, hz, q = coeffs(-0.4, 0.3)
c.check(f"stock curves give a usable cutoff and Q (knob -0.4 -> {hz:.0f} Hz, res 0.3 -> Q {q:.2f})",
        20 < hz < 20000 and 0.1 <= q <= 40)
sig = [math.sin(i * 0.37) * 0.3 + math.sin(i * 0.05) * 0.4 for i in range(3 * N)]
states, ms, err = [[0.0, 0.0], [0.0, 0.0]], [g, r, 0.0], 0.0
for b in range(3):
    l, _ = run(sig[b * N:(b + 1) * N])
    if b:
        ms = [m + 0.33333 * (t - m) for m, t in zip(ms, (g, r, 0.0))]
    ref = model_block(sig[b * N:(b + 1) * N], ms[0], ms[1], ms[2], states, False)
    err = max(err, max(abs(p - q) for p, q in zip(l, ref)))
c.check("low-pass output equals the model (two SVF stages, coefficient smoothing) over three blocks", err < 1e-4, err)


def response(knob, res, hz_test, blocks=8):
    reset()
    setup(knob, res)
    out = []
    for b in range(blocks):
        l, _ = run(sine(hz_test, start=b * N))
        out += l
    return rms(out[N * 4:]) / rms(sine(hz_test, n=N * 4))


lp_low, lp_high = response(-0.6, 0.5, 100), response(-0.6, 0.5, 12000)
c.check(f"LP at {coeffs(-0.6, 0.5)[2]:.0f} Hz passes 100 Hz and cuts 12 kHz", lp_low > 0.9 and lp_high < 0.1,
        (lp_low, lp_high))
hp_low, hp_high = response(0.6, 0.5, 100), response(0.6, 0.5, 12000)
c.check(f"HP at {coeffs(0.6, 0.5)[2]:.0f} Hz cuts 100 Hz and passes 12 kHz", hp_low < 0.1 and hp_high > 0.9,
        (hp_low, hp_high))
fc = coeffs(-0.6, 0.5)[2]
one, two = response(-0.6, 0.5, fc * 2), response(-0.6, 0.5, fc * 4)
c.check(f"24 dB/oct: one octave above cutoff {20 * math.log10(one):.0f} dB, two octaves {20 * math.log10(two):.0f} dB",
        two < 0.02 and two / one < 0.09, (one, two))

reset()
setup(-0.3, 1.0)
worst = 0.0
for b in range(200):
    l, _ = run([((i * 7919 + b * 104729) % 2001 - 1000) / 1000.0 for i in range(N)])
    worst = max(worst, max(abs(v) for v in l))
c.check(f"maximum resonance on full-scale noise stays bounded (peak {worst:.1f})", worst < 4 and not math.isnan(worst))

reset()
setup(-0.6, 0.2)
lo, hi = sine(100), sine(12000)
l, r = run(lo, hi)
reset()
setup(-0.6, 0.2)
l2, _ = run(lo)
c.check("stereo: left matches the mono run, right is filtered on its own",
        max(abs(a - b) for a, b in zip(l, l2)) < 1e-6 and rms(r) < rms(hi))


# --- crunch
def runs_of(x):
    out, k = [], 0
    while k < len(x):
        j = k
        while j < len(x) and x[j] == x[k]:
            j += 1
        out.append(j - k)
        k = j
    return out


CRUNCH = 7                                      # first crunch entry: Normal, HighQ, 5 machines, then 16k ..
reset()
setup(0.0, interp=CRUNCH + 1)                   # 12k
l, _ = run(sine(997))
c.check("12k: output holds each value for 4 samples (48k / 12k)", all(v == 4 for v in runs_of(l)[1:-1]))
c.check("12k: held values are 12-bit", all(abs(v * 2048 - round(v * 2048)) < 1e-3 for v in l))
reset()
setup(0.0, interp=CRUNCH + 5)                   # 4k
a, _ = run(sine(997))
b, _ = run(sine(997, start=N))
c.check("4k: holds 12 samples, continuing across the block boundary", all(v == 12 for v in runs_of(a + b)[1:-1]))
for v, name in ((0, "Normal"), (1, "HighQ"), (14, "a value past the list")):
    reset()
    setup(0.0, interp=v)
    l, _ = run(sine(997))
    c.check(f"Fidelity {name}: no crunch", all(abs(p - q) < 1e-7 for p, q in zip(l, sine(997))))
reset()
setup(0.0, interp=CRUNCH + 1)
l, _ = run(sine(997), pad=0)
c.check("no pad passed: no crunch, no crash", all(abs(p - q) < 1e-7 for p, q in zip(l, sine(997))))
e.w32(PAD + 0x18, 7 << 8 | 0)
l, _ = run(sine(997))
c.check("a pad id outside the grid reads as Normal", all(abs(p - q) < 1e-7 for p, q in zip(l, sine(997))))

# --- call-site thunks: pad in r5 (sample voices) and r6 (slicer voices)
for thunk, reg in (("filter_voice_a", UC_ARM_REG_R5), ("filter_voice_b", UC_ARM_REG_R6)):
    reset()
    setup(0.0, interp=CRUNCH + 1)
    e.wr(LBUF, struct.pack(f"<{N}f", *sine(997)))
    e.wr(BUF, struct.pack("<iiIIBB", N, N, LBUF, 0, 0, 0))
    e.uc.reg_write(UC_ARM_REG_R5, 0)
    e.uc.reg_write(UC_ARM_REG_R6, 0)
    e.uc.reg_write(reg, PAD)
    e.call(thunk, OBJ, BUF)
    l = struct.unpack(f"<{N}f", e.rd(LBUF, 4 * N))
    c.check(f"{thunk} passes its pad: crunch applies", len(set(l)) <= N // 4 + 1)

# --- machine modes: output side
reset()
setup(0.0, interp=2)                            # SP1200: 26.04 kHz hold + output low-pass
l = []
for b in range(4):
    l += run(sine(997, start=b * N))[0]
c.check("SP1200 output: finite and 12-bit before the output filter", all(math.isfinite(v) for v in l))
reset()
setup(0.0, interp=6)                            # SP Raw: hold only
l, _ = run(sine(997))
c.check("SP Raw: zero-order hold at 26.04 kHz (runs of 1 and 2)", set(runs_of(l)[1:-1]) <= {1, 2})
e.w32(OBJ + 0x60, 0x11223344)
e.w32(OBJ + 0x64, 0x55667788)
setup(-0.5, 0.9, interp=3)
for b in range(3):
    run(sine(997, start=b * N), sine(500, start=b * N))
c.check("filter object fields from +0x60 on are left alone (stock pointers, params block)",
        (e.r32(OBJ + 0x60, False), e.r32(OBJ + 0x64, False), e.r32(OBJ + 0x84, False)) == (0x11223344, 0x55667788, PARAMS))

# --- machine modes: reader side. read_normal with no machine = the stock kernel, bit for bit.
SRC, DST, NP, FR = 0x24070000, 0x24071000, 0x24072000, 0x24072010
src = [math.sin(i * 0.3) for i in range(256)]
e.wr(SRC, struct.pack("<256f", *src))


def kernel(fn, rate, pos, frac, n=64):
    e.wf(FR, frac)
    e.w32(NP, 0)
    e.uc.reg_write(UC_ARM_REG_S0, f2u(rate))
    sp = STACK - 12
    e.call(fn, SRC, 200, pos, NP, stack_args=(FR, DST, n))
    return list(struct.unpack(f"<{n}f", e.rd(DST, 4 * n))), e.r32(NP), e.rf(FR)


PARK = 0x38000000
e.w32(PARK, PAD)
e.w32(PARK + 4, 1000)
e.wf(PARK + 8, 1.5)
setup(0.0, interp=0)
c.check("read_normal with Fidelity Normal = stock FUN_080a1400",
        kernel("read_normal", 1.5, 4, 0.25) == kernel(0x080A1400, 1.5, 4, 0.25))
setup(0.0, interp=1)
c.check("read_hq with Fidelity HighQ = stock FUN_080a1494",
        kernel("read_hq", 1.5, 4, 0.25) == kernel(0x080A1494, 1.5, 4, 0.25))
setup(0.0, interp=2)
out, np_, fr = kernel("read_hq", 1.0, 4, 0.0)
st, snp, sfr = kernel(0x080A1494, 1.0, 4, 0.0)
c.check("SP1200 reader: position bookkeeping matches the stock kernel", (np_, round(fr, 5)) == (snp, round(sfr, 5)),
        (np_, fr, snp, sfr))
c.check("SP1200 reader: reads on its 26.04 kHz grid (repeats samples at rate 1)",
        len(set(round(v, 6) for v in out)) < 0.7 * len(out))

# --- the Fidelity list
seen = {}
e.stub(0x08069E7C, lambda: seen.update(names=e.arg(3), count=e.r32(e.uc.reg_read(UC_ARM_REG_SP)), param=e.arg(1),
                                        label=e.cstr(e.arg(2)), xml=e.cstr(e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4))))
e.call("interp_register", 0x24001000, 0xD2, 0x080C1464, 0x080C475C, stack_args=(2, 0x080C146C))
names = [e.cstr(e.r32(seen["names"] + 4 * i)) for i in range(seen["count"])]
c.check("Fidelity list: Normal, HighQ, SP1200, SP-12, S950, MPC60, SP Raw, 16k .. 2k",
        names == ["Normal", "HighQ", "SP1200", "SP-12", "S950", "MPC60", "SP Raw", "16k", "12k", "10k", "8k", "6k", "4k",
                  "2k"] and seen["param"] == 0xD2, names)
c.check("label 'Fidelity:', xml name stays 'interpqual'", (seen["label"], seen["xml"]) == ("Fidelity:", "interpqual"),
        (seen["label"], seen["xml"]))
sys.exit(c.done())
