/*
 * Granular controls: Shape, Grain Sync / Sync Rate and Position, added to the granular pad page (after Speed).
 *
 *   Shape     the grain envelope, 0..100 %: 0 plucky (no attack, short release), 50 the stock smooth (Hann) window,
 *             100 a swell (long attack, no decay); in between it morphs.
 *   Grain Sync Free (stock: grains follow Density) or Beat: each new grain starts on the next free step of the Sync
 *             Rate grid (1/64 .. 4 bars, default 1/16), locked to the song position, one grain per step.
 *   Position  where the window starts in the sample, 0..100 %: added to the stock read position (which moves with
 *             Speed) and wraps around the sample.
 *
 * Hooks (patches/grain.py): the grain render FUN_080af8b4 reads its window from a table through a literal
 * (0x080afae8, 8192 floats, the Hann window at 0x080cac00); the literal now points to GTABLE in MOD_RAM, refilled for
 * the pad being rendered when its Shape differs from the table's (loop_grain_render calls grain_prepare). A grain that
 * ends spawns the next one in its slot with FUN_080af5a0 (bl at 0x080afac8): grain_spawn moves the new grain's start
 * onto the grid when the pad syncs. Position goes in through the grain's sample read (loop_grain_read).
 */
#include "fw.h"
#include "mod.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")

#define P_GSHAPE 0x17d
#define P_GSYNC  0x17e
#define P_GRATE  0x17f
#define P_GPOS   0x180

#define WIN_N     8192
#define STOCK_WIN ((const float *)0x080cac00u)
#define GTABLE    ((float *)(MOD_RAM + 0x8000u))                 /* 32 KB, the window the grain render reads */
#define GT_SHAPE  (*(volatile int32_t *)(MOD_RAM + 0x3890u))     /* Shape GTABLE holds, -1 none */
#define CLK_SONG  (*(volatile double *)(MOD_RAM + 0x3898u))      /* song position (samples) at this block's start */
#define CLK_SPQ   (*(volatile float *)(MOD_RAM + 0x38a0u))       /* samples per quarter, 0 no valid tempo */
#define CLK_TP    (*(volatile double *)(MOD_RAM + 0x38a8u))      /* the transport's song position last block */
#define CLK_OK    (*(volatile uint32_t *)(MOD_RAM + 0x38b0u))
#define GMAGIC    0x4752414eu                                     /* "GRAN" */
#define LAST_AT   ((volatile double *)(MOD_RAM + 0x3900u))       /* per pad: song time of its last grid grain, -1 */

static const char *const sync_names[2] = {"Free", "Beat"};
static const char *const rate_names[9] = {"1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1 bar", "2 bars", "4 bars"};
static const float rate_quarters[9] = {0.0625f, 0.125f, 0.25f, 0.5f, 1, 2, 4, 8, 16};

/* A pad's setting, or `def` when its store has none (presets from before the mod, other pad types). */
static int setting(const uint8_t *pad, unsigned id, int def)
{
    const uint8_t *s = pad_store(pad);
    if (!s)
        return def;
    const uint8_t *e = *(const uint8_t *const *)(s + 4);
    unsigned n = *(const uint16_t *)(s + 10);
    if (!e || n > 64)
        return def;
    for (unsigned i = 0; i < n; i++)
        if (*(const uint16_t *)(e + i * 8) == id)
            return *(const int32_t *)(e + i * 8 + 4);
    return def;
}

/* Grain envelopes, x in [0, 1): a 1 % ramp at the hard edge keeps them from clicking. */
static inline float pluck(float x)
{
    float a = x < 0.01f ? x * 100.0f : 1.0f;
    float d = 1.0f - x;
    return a * d * d * d * d;
}

static inline float swell(float x)
{
    float r = x > 0.99f ? (1.0f - x) * 100.0f : 1.0f;
    return r * x * x;
}

static void fill_table(int shape)
{
    float m = (float)(shape - 500) * (1.0f / 500.0f);         /* -1 pluck .. 0 stock .. +1 swell */
    float k = m < 0.0f ? -m : m;
    float *t = GTABLE;
    for (int i = 0; i < WIN_N; i++) {
        float x = (float)i * (1.0f / WIN_N);
        float target = m < 0.0f ? pluck(x) : swell(x);
        t[i] = STOCK_WIN[i] * (1.0f - k) + target * k;
    }
    GT_SHAPE = shape;
}

/* Called before the granular voice render: the window for this pad's Shape, and its Position in frames. */
int grain_prepare(const uint8_t *pad, int wave_len)
{
    int shape = setting(pad, P_GSHAPE, 500);
    if (shape < 0 || shape > 1000)
        shape = 500;
    if (shape != GT_SHAPE)
        fill_table(shape);
    int pos = setting(pad, P_GPOS, 0);
    if (pos <= 0 || pos > 1000 || wave_len <= 0)
        return 0;
    return (int)((float)pos * (1.0f / 1000.0f) * (float)wave_len);
}

/*
 * The song clock for Beat sync, from the engine hook each block: it follows the transport's song position while the
 * transport runs on by one block at a time, and runs on by itself otherwise (stopped, jumping), like the Live Loop.
 */
void grain_clock(const uint8_t *transport, int n)
{
    float tempo = transport ? *(const float *)(transport + 0x18) : 0.0f;
    if (!(tempo >= 20.0f && tempo <= 400.0f)) {
        CLK_SPQ = 0.0f;
        return;
    }
    int64_t now = *(const int64_t *)transport;
    int64_t anchor_ticks = *(const int64_t *)(transport + 8);
    int64_t anchor_samples = *(const int64_t *)(transport + 0x10);
    double spt = 48000.0 * 60.0 / ((double)tempo * 960.0);
    double tp = (double)anchor_ticks * spt + (double)(now - anchor_samples);
    if (CLK_OK != GMAGIC) {
        CLK_OK = GMAGIC;
        CLK_SONG = tp;
        for (int i = 0; i < 20; i++)
            LAST_AT[i] = -1.0;
    } else {
        double moved = tp - CLK_TP, run = CLK_SONG + (double)n;
        CLK_SONG = moved > (double)n - 0.5 && moved < (double)n + 0.5 ? tp : run;
    }
    CLK_TP = tp;
    CLK_SPQ = (float)(48000.0 * 60.0 / (double)tempo);
}

static int pad_index(const uint8_t *pad)
{
    if (!pad_ptr_ok(pad))
        return -1;
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    return row < 4 && col < 5 ? (int)(row * 5 + col) : -1;
}

typedef void (*spawn_fn)(uint8_t *pad, void *now, uint8_t *voice, int a4, int a5, uint8_t *grain);
#define fw_grain_spawn ((spawn_fn)FN(0x080af5a0))

/* In place of the grain respawn in the grain render (bl at 0x080afac8). grain + 0x28: frames from this block's start
   until the grain starts. */
void grain_spawn(uint8_t *pad, void *now, uint8_t *voice, int a4, int a5, uint8_t *grain)
{
    fw_grain_spawn(pad, now, voice, a4, a5, grain);
    if (!grain[0] || CLK_OK != GMAGIC || CLK_SPQ <= 0.0f || setting(pad, P_GSYNC, 0) != 1)
        return;
    int p = pad_index(pad);
    if (p < 0)
        return;
    unsigned ri = (unsigned)setting(pad, P_GRATE, 2);
    float step = CLK_SPQ * rate_quarters[ri < 9 ? ri : 2];
    double song = CLK_SONG;
    int32_t d = *(int32_t *)(grain + 0x28);
    double at = song + (double)(d > 0 ? d : 0);
    double q = at / (double)step;
    int32_t k = (int32_t)q;
    if ((double)k < q)
        k++;                                                   /* the next step at or after its own start */
    double t = (double)k * (double)step, last = LAST_AT[p];
    if (last >= 0.0 && t < last + 1.0 && last - t < 64.0 * (double)step)
        t = ((double)(int32_t)(last / (double)step + 1e-6) + 1.0) * (double)step;   /* one grain per step */
    LAST_AT[p] = t;
    double wait = t - song;
    *(int32_t *)(grain + 0x28) = wait > 0.0 ? (int32_t)(wait + 0.5) : 0;
}

void grain_register(void *table)
{
    GT_SHAPE = -1;
    fill_table(500);
    CLK_OK = 0;
    fw_register_num(table, P_GSHAPE, 8, "Shape:", 0, 1000, "grainshape");
    fw_register_list(table, P_GSYNC, "Grain Sync:", sync_names, 2, "grainsync");
    fw_register_list(table, P_GRATE, "Sync Rate:", rate_names, 9, "grainrate");
    fw_register_num(table, P_GPOS, 8, "Position:", 0, 1000, "grainpos");
}

void grain_pad_store(void *store)
{
    fw_store_add(store, P_GSHAPE, 500);
    fw_store_add(store, P_GSYNC, 0);
    fw_store_add(store, P_GRATE, 2);
    fw_store_add(store, P_GPOS, 0);
}
