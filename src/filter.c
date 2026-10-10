/*
 * Fidelity (was Interp) + 24 dB state-variable filter with resonance drive. bitbox micro, firmware 2.3.4.
 * Ported from blackbox-mod's src/filter.c (MIT, Copyright (c) 2026 Justin Joe); the DSP is unchanged, the hooks are
 * the micro's.
 *
 * Stock: every voice runs its pad filter once per block (FUN_080b8420): one RBJ biquad, 12 dB/oct, low-pass left of
 * centre, high-pass right of it, bypassed at centre. This replaces that call (sample voices and slicer voices) with:
 *   1. Fidelity: the pad's Interp list gains machine modes (SP1200, SP-12, S950, MPC60, SP Raw) and plain crunch rates
 *      (16k .. 2k) after Normal / HighQ. Crunch holds the voice's output at a lower rate and rounds it to 12 bits
 *      before the filter. Machine modes also change how the voice reads its sample (machine_read below).
 *   2. Filter: 24 dB/oct, two trapezoidal state-variable filters after Emilie Gillet's stmlib (dsp/filter.h, class Svf;
 *      MIT, Copyright 2014 Emilie Gillet) in series: the first at a fixed Butterworth Q, the second carrying Res.
 *      Cutoff and Q go through the stock curves, so the Filter and Res knobs keep their ranges. Drive rides on Res:
 *      clean below noon, from noon to full the input is pushed into a soft clipper and the resonant integrator is
 *      soft-limited, so high resonance growls instead of only getting louder.
 * State lives in the stock filter object (0x94 bytes, FUN_080b81f0), in the part only the stock process used.
 * Stock firmware treats the new Interp values as HighQ, so presets stay loadable there.
 */
#include "fw.h"
#include "mod.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* per-sample loops run for every voice */

#define FS         48000.0f
#define PI_F       3.14159265f
#define OBJ_PARAMS 0x84          /* filter object -> its parameter block: Filter knob @+8, Res @+0x44 */
#define P_INTERP   0xd2          /* pad Interp ("interpqual") */

static const float crunch_rate[] = {16000.0f, 12000.0f, 10000.0f, 8000.0f, 6000.0f, 4000.0f, 2000.0f};
#define CRUNCHES ((int)(sizeof crunch_rate / sizeof crunch_rate[0]))
#define STOCK_INTERP 2           /* Normal, HighQ */

/*
 * Machine modes: the old samplers' pitch path, not only their output rate.
 *   grid  the machine's sample rate. The voice reader plays the sample as if it had been sampled at this rate: it reads
 *         the source only on that grid (after a 5-tap anti-alias FIR at 0.45 x grid), so pitching skips or doubles
 *         stored samples like the SP's pitch logic, and the aliasing moves with the note.
 *   hold  1: the DAC runs at the grid rate whatever the pitch (SP-1200, SP-12, MPC60): zero-order hold after the voice.
 *         0: a variable-rate DAC (S950): no fixed hold; the reader interpolates linearly between grid samples.
 *   out   output stage, an RBJ low-pass {b0, b1, a1, a2} at 48 kHz (b2 = b0).
 *   raw   SP Raw: SP1200 without the output filter.
 * All 12-bit. The pad's own Filter knob (24 dB SVF) comes after this.
 */
struct machine {
    float grid;
    uint8_t hold, linear, raw;
    float fir[5];
    float out[4];
};
static const struct machine machines[] = {
    {26040.0f, 1, 0, 0, {0.00302f, 0.24563f, 0.5027f, 0.24563f, 0.00302f}, {0.357143f, 0.714286f, 0.0f, 0.428571f}},
    {27500.0f, 1, 0, 0, {-0.00396f, 0.24215f, 0.52363f, 0.24215f, -0.00396f}, {0.376262f, 0.752523f, 0.092392f, 0.412654f}},
    {31250.0f, 0, 1, 0, {-0.02035f, 0.2289f, 0.58291f, 0.2289f, -0.02035f}, {0.361304f, 0.722608f, 0.235922f, 0.209295f}},
    {40000.0f, 1, 0, 0, {-0.03947f, 0.16746f, 0.74402f, 0.16746f, -0.03947f}, {0.506372f, 1.012744f, 0.675162f, 0.350325f}},
    {26040.0f, 1, 0, 1, {0.00302f, 0.24563f, 0.5027f, 0.24563f, 0.00302f}, {0.0f, 0.0f, 0.0f, 0.0f}},     /* SP Raw */
};
#define MACHINES ((int)(sizeof machines / sizeof machines[0]))
#define FIRST_MACHINE STOCK_INTERP
#define FIRST_CRUNCH  (STOCK_INTERP + MACHINES)
#define FIDELITIES    (STOCK_INTERP + MACHINES + CRUNCHES)

const char *const interp_names[FIDELITIES] = {
    (const char *)0x080c2414u, (const char *)0x080c241cu,       /* stock "Normal", "HighQ" */
    "SP1200", "SP-12", "S950", "MPC60", "SP Raw",
    "16k", "12k", "10k", "8k", "6k", "4k", "2k",
};

/* Replaces the Interp list registration (bl at 0x0806b34a): 2 -> 14 entries, label "Interp:" -> "Fidelity:". The xml
   name "interpqual" stays, so presets are unaffected. */
void interp_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    (void)label;
    (void)names;
    (void)count;
    fw_register_list(table, param, "Fidelity:", interp_names, FIDELITIES, xml);
}

struct fstate {                  /* filter object +0x04..+0x43: the stock coefficient sets and biquad states */
    uint32_t magic;
    float g, r, drive;           /* smoothed: SVF frequency coefficient, damping of the resonant stage, drive 0..1 */
    float s1[2][2], s2[2][2];    /* integrator states [stage][channel] */
    float phase, held[2];        /* crunch: hold phase and held sample per channel */
    uint32_t on;                 /* filter was running last block */
};
#define MAGIC 0x53564632u        /* "SVF2" */
#define R_BUTTERWORTH 1.84776f   /* 1 / 0.5412: first stage of a 4-pole Butterworth */
#define SMOOTH 0.33333f

_Static_assert(sizeof(struct fstate) == 0x40, "fstate must end at +0x44");

static float tan_approx(float x)           /* tan(x), 0 <= x < 1.45, Pade (3,2) */
{
    float x2 = x * x;
    return x * (15.0f - x2) / (15.0f - 6.0f * x2);
}

static float quantize12(float x)
{
    float s = x * 2048.0f;
    int i = (int)(s + (s >= 0.0f ? 0.5f : -0.5f));
    return (float)i * (1.0f / 2048.0f);
}

/* Output stage of a machine mode, state at filter object +0x44..+0x57 (stock: biquad states, unused now). */
struct ostate {
    uint32_t magic;
    float z[2][2];
};
#define OMAGIC 0x4d4f5554u       /* "MOUT" */

static void out_stage(uint8_t *obj, float **ch, int n, const float *c)
{
    struct ostate *o = (struct ostate *)(obj + 0x44);
    if (o->magic != OMAGIC) {
        o->z[0][0] = o->z[0][1] = o->z[1][0] = o->z[1][1] = 0.0f;
        o->magic = OMAGIC;
    }
    float b0 = c[0], b1 = c[1], a1 = c[2], a2 = c[3];
    for (int k = 0; k < 2; k++) {
        float *x = ch[k];
        if (!x)
            continue;
        float z1 = o->z[k][0], z2 = o->z[k][1];
        for (int i = 0; i < n; i++) {                       /* transposed direct form II */
            float in = x[i], y = b0 * in + z1;
            z1 = b1 * in - a1 * y + z2;
            z2 = b0 * in - a2 * y;
            x[i] = y;
        }
        o->z[k][0] = z1;
        o->z[k][1] = z2;
    }
}

static void crunch(struct fstate *st, float **ch, int n, float rate)
{
    float step = rate / FS, phase = st->phase;
    float held0 = st->held[0], held1 = st->held[1];
    for (int i = 0; i < n; i++) {
        phase += step;
        if (phase >= 1.0f) {
            phase -= 1.0f;
            held0 = quantize12(ch[0][i]);
            if (ch[1])
                held1 = quantize12(ch[1][i]);
        }
        ch[0][i] = held0;
        if (ch[1])
            ch[1][i] = held1;
    }
    st->phase = phase;
    st->held[0] = held0;
    st->held[1] = held1;
}

/* Soft clip, unity gain at zero, flat at |x| = 1.5 t, ceiling t. */
static inline __attribute__((always_inline)) float soft(float x, float inv_t, float t)
{
    float u = x * inv_t;
    u = u > 1.5f ? 1.5f : u < -1.5f ? -1.5f : u;
    return t * u * (1.0f - 0.148148f * u * u);
}

#define SVF_LOOP(OUT, NEXT_S1)                                                                                     \
    for (int i = 0; i < n; i++) {                                                                                  \
        float hp = (x[i] - rg * s1 - s2) * h;                                                                      \
        float bp = g * hp + s1;                                                                                    \
        s1 = NEXT_S1;                                                                                              \
        float lp = g * bp + s2;                                                                                    \
        s2 = g * bp + lp;                                                                                          \
        x[i] = OUT;                                                                                                \
    }

static void svf(float *x, int n, float g, float r, float *s1p, float *s2p, int highpass, float limit)
{
    float h = 1.0f / (1.0f + r * g + g * g), rg = r + g, s1 = *s1p, s2 = *s2p;
    if (limit > 0.0f) {
        float inv = 1.0f / limit;
        if (highpass)
            SVF_LOOP(hp, soft(g * hp + bp, inv, limit))
        else
            SVF_LOOP(lp, soft(g * hp + bp, inv, limit))
    } else if (highpass) {
        SVF_LOOP(hp, g * hp + bp)
    } else {
        SVF_LOOP(lp, g * hp + bp)
    }
    *s1p = s1;
    *s2p = s2;
}

static void drive_in(float *x, int n, float amount)
{
    float pre = 1.0f + 3.0f * amount;
    for (int i = 0; i < n; i++)
        x[i] = soft(x[i] * pre, 1.0f, 1.0f);
}

/* The pad's Interp setting, from the app's record of the pad (what the screen shows and presets save): the engine's
   own copy (pad + 0x564) is zeroed by its pad reset. */
static unsigned pad_interp(const uint8_t *pad)
{
    return (unsigned)pad_setting(pad, P_INTERP);
}

static const struct machine *pad_machine(const uint8_t *pad)
{
    unsigned interp = pad_interp(pad);
    return interp >= FIRST_MACHINE && interp < FIRST_MACHINE + MACHINES ? &machines[interp - FIRST_MACHINE] : 0;
}

/* Replaces the per-voice filter call. pad = the pad object the voice belongs to (thunks in filter_thunk.S). */
void filter_process(uint8_t *obj, void *buf, const uint8_t *pad)
{
    if (fw_buf_silent(buf))
        return;
    struct fstate *st = (struct fstate *)(obj + 4);
    if (st->magic != MAGIC) {
        uint32_t *w = (uint32_t *)st;
        for (unsigned i = 0; i < sizeof *st / 4; i++)
            w[i] = 0;
        st->magic = MAGIC;
    }
    unsigned interp = pad_interp(pad);
    int crunching = interp >= STOCK_INTERP && interp < FIDELITIES;
    uint8_t *params = *(uint8_t **)(obj + OBJ_PARAMS);
    float knob = params ? fw_param(params + 8) : 0.0f;
    if (knob == 0.0f) {
        st->on = 0;
        if (!crunching)
            return;
    }

    float *ch[2] = {0, 0};
    int n = fw_buf_frames(buf);
    fw_buf_chans(buf, &ch[0], &ch[1]);
    if (!ch[0] || n <= 0)
        return;
    if (interp >= FIRST_MACHINE && interp < FIRST_MACHINE + MACHINES) {
        const struct machine *m = &machines[interp - FIRST_MACHINE];
        if (m->hold) {
            crunch(st, ch, n, m->grid);
        } else {
            for (int k = 0; k < 2; k++)
                if (ch[k])
                    for (int i = 0; i < n; i++)
                        ch[k][i] = quantize12(ch[k][i]);
        }
        if (!m->raw)
            out_stage(obj, ch, n, m->out);
    } else if (crunching) {
        crunch(st, ch, n, crunch_rate[interp - FIRST_CRUNCH]);
    }
    if (knob == 0.0f)
        return;

    float hz = fw_cutoff_hz(knob < 0.0f ? knob + 1.0f : knob);
    float res = fw_param(params + 0x44);
    float q = fw_res_q(res);
    float drive = (res - 0.5f) * 2.0f;                      /* 0 up to the default Res, 1 at full */
    drive = drive < 0.0f ? 0.0f : drive > 1.0f ? 1.0f : drive * drive;
    if (hz < 10.0f)
        hz = 10.0f;
    if (hz > 0.45f * FS)
        hz = 0.45f * FS;
    if (!(q > 0.1f))
        q = 0.1f;
    if (q > 40.0f)
        q = 40.0f;
    float g = tan_approx(PI_F * hz / FS), r = 1.0f / q;
    if (!st->on) {
        st->g = g;
        st->r = r;
        st->drive = drive;
        for (int k = 0; k < 2; k++)
            st->s1[k][0] = st->s1[k][1] = st->s2[k][0] = st->s2[k][1] = 0.0f;
        st->on = 1;
    } else {
        st->g += SMOOTH * (g - st->g);
        st->r += SMOOTH * (r - st->r);
        st->drive += SMOOTH * (drive - st->drive);
    }
    int hp = knob > 0.0f;
    float limit = st->drive > 0.001f ? 4.0f - 3.0f * st->drive : 0.0f;
    for (int c = 0; c < 2; c++) {
        if (!ch[c])
            continue;
        if (st->drive > 0.001f)
            drive_in(ch[c], n, st->drive);
        svf(ch[c], n, st->g, R_BUTTERWORTH, &st->s1[0][c], &st->s2[0][c], hp, 0.0f);
        svf(ch[c], n, st->g, st->r, &st->s1[1][c], &st->s2[1][c], hp, limit);
    }
}

/*
 * The voice reader. Sample voices read through FUN_080adc4c, which fetches the source into a scratch buffer and
 * resamples it with FUN_080a1400 (Normal) or FUN_080a1494 (HighQ), chosen by the engine's Interp copy. Both take
 * (rate s0, src r0, n_src r1, int pos r2, int *newpos r3, float *frac, float *dst, int n). voice_read parks the pad,
 * absolute source position and signed rate here so the machine grid is anchored on the sample itself.
 */
struct read_park {
    const uint8_t *pad;
    int32_t pos;
    float rate;
};
#define PARK ((volatile struct read_park *)(MOD_RAM + 0x0000u))

typedef void (*kernel_fn)(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst,
                          int n);
#define fw_kernel_normal ((kernel_fn)FN(0x080a1400))
#define fw_kernel_hq     ((kernel_fn)FN(0x080a1494))

static inline float floor_f(float x)
{
    int i = (int)x;
    return (float)(i - (x < (float)i));
}

static inline int round_i(float x)
{
    return (int)(x + (x >= 0.0f ? 0.5f : -0.5f));
}

static void machine_read(const struct machine *m, float rate, const float *src, int n_src, int pos, int *newpos,
                         float *frac, float *dst, int n)
{
    /* scratch index -> absolute source position. Forward: scratch[0] = source[P - 4]. Reverse: FUN_080adc4c fetched
       from round(P) - n_src + 4 and reversed the buffer, so scratch[j] = source[round(P) + 3 - j]. */
    int32_t base = PARK->pos - 4;
    float sgn = 1.0f;
    if (PARK->rate < 0.0f) {
        sgn = -1.0f;
        base = PARK->pos + 3;
    }
    double gd = 48000.0 / (double)m->grid;
    double kb = (double)(int32_t)((double)base / gd);
    if (kb * gd > (double)base)
        kb -= 1.0;
    float a0 = (float)((double)base - kb * gd);      /* 0 <= a0 < g: where the scratch sits on the grid */
    float g = (float)gd, inv_g = m->grid * (1.0f / 48000.0f);
    const float *h = m->fir;
    int hi = n_src - 3;
    float f = *frac;
    int idx = pos;
    for (int i = 0; i < n; i++) {
        float gp = (a0 + sgn * ((float)idx + f)) * inv_g, k0 = floor_f(gp);
        int j0 = round_i(sgn * (k0 * g - a0));
        j0 = j0 < 2 ? 2 : j0 > hi ? hi : j0;
        const float *s = src + j0;
        float v = h[0] * s[-2] + h[1] * s[-1] + h[2] * s[0] + h[3] * s[1] + h[4] * s[2];
        if (m->linear) {
            int j1 = round_i(sgn * ((k0 + 1.0f) * g - a0));
            j1 = j1 < 2 ? 2 : j1 > hi ? hi : j1;
            s = src + j1;
            float w = h[0] * s[-2] + h[1] * s[-1] + h[2] * s[0] + h[3] * s[1] + h[4] * s[2];
            v += (gp - k0) * (w - v);
        }
        dst[i] = v;
        float adv = rate + f;
        int step = (int)adv;
        idx += step;
        f = adv - (float)step;
    }
    *frac = f;
    *newpos = idx;
}

typedef int (*voice_read_fn)(float frac, float rate, const uint8_t *pad, void *wave, int pos, int a6, int frames,
                             int offset, void *scratch, void *out);
#define fw_voice_read ((voice_read_fn)FN(0x080adc4c))

/* Replaces the calls to FUN_080adc4c (0x080aee92, 0x080af0d8, 0x080af19a). At exactly the original pitch the stock
   reader copies without a kernel; in a machine mode the rate goes in as the next float above 1.0 so those voices
   still read through the machine's grid. */
int voice_read(float frac, float rate, const uint8_t *pad, void *wave, int pos, int a6, int frames, int offset,
               void *scratch, void *out)
{
    PARK->pad = pad;
    PARK->pos = pos;
    PARK->rate = rate;
    if (rate == 1.0f && pad_machine(pad))
        rate = 1.00000012f;
    return fw_voice_read(frac, rate, pad, wave, pos, a6, frames, offset, scratch, out);
}

/* The kernel calls in FUN_080adc4c: Normal @0x080adf00 / 0x080adf24 / 0x080adf48, HighQ @0x080add4c / 0x080addd8 /
   0x080addfc. */
void read_normal(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst, int n)
{
    const struct machine *m = pad_machine(PARK->pad);
    if (m)
        machine_read(m, rate, src, n_src, pos, newpos, frac, dst, n);
    else
        fw_kernel_normal(rate, src, n_src, pos, newpos, frac, dst, n);
}

void read_hq(float rate, const float *src, int n_src, int pos, int *newpos, float *frac, float *dst, int n)
{
    const struct machine *m = pad_machine(PARK->pad);
    if (m)
        machine_read(m, rate, src, n_src, pos, newpos, frac, dst, n);
    else
        fw_kernel_hq(rate, src, n_src, pos, newpos, frac, dst, n);
}
