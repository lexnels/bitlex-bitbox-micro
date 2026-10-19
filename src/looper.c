/*
 * Live Loop: a pad that keeps recording. bitbox micro, firmware 2.3.4.
 *
 * A new pad setting, Live Loop (Off / Replace / Overdub), on the pad's settings page. With it on, the pad captures
 * its recording source (Rec Input: In 1/2, In 1, In 2 or Resam, at the recording Gain) into a loop of the recording
 * Length (1/4 .. 128 bars, Custom counts as 1 bar), locked to the tempo and the bar grid, all the time. Whatever was
 * captured during one pass is what the pad plays during the next one:
 *   Replace  each pass replaces the loop: the pad always plays the last bar(s) you played into it.
 *   Overdub  each pass adds to the loop.
 * Playback never stops for recording; the loop is written just behind the point the pad is playing.
 *
 * How it plays: the pad's voice (started as usual: tap, MIDI, sequence) plays the loop instead of its sample, through
 * the pad's own envelope, filter, level, pan, mute and sends. The pad needs a sample for its voice to start, so the
 * usual way in is to record the pad once (stock recording, with RecToPlay on): the first pass plays that recording,
 * and live looping carries on from there. Whenever the pad's sample changes, the loop restarts from it.
 *
 * Timing: the loop position is computed every block from the transport's tempo map (anchor ticks / samples / tempo,
 * 960 ticks per quarter), so a loop of N bars always starts on a multiple of N bars and follows tempo changes (a tempo
 * or Length change restarts the loop from the pad's sample).
 *
 * Memory: four loops at a time, 16-bit stereo, in one 4 MB block (5.4 s per loop: 1 bar down to 45 BPM, 2 bars down
 * to 89 BPM) taken the first time a pad needs a loop, from the SDRAM the stock firmware leaves free (see take_arena). Nothing is written to the SD card: the loop lives in RAM; the pad's sample file stays as recorded.
 *
 * Hooks: engine_block (in front of the engine's block process, mod.c) runs looper_block before the graph, which
 * reads the loop for this block into a play buffer and then writes the input over it; loop_voice_render (in place of
 * the per-voice render FUN_080aec34) outputs that play buffer through the voice's own stage FUN_080ad870.
 */
#include "fw.h"
#include "mod.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")

#define P_LIVELOOP 0x17c
#define P_LENGTH   0x79           /* recpresetlen: Custom, 1/4, 1/2, 1 bar .. 128 bars */
#define P_RECINPUT 0x7c           /* In 1/2, In 1, In 2, Resam */
#define P_GAIN     0xba           /* ingain, mdB */
#define P_RECCONF  0xc2           /* RecConfig: Global / Per Pad */

#define SLOTS      4
#define ARENA_MAX  (4u << 20)
#define PADS       20             /* 4 rows x 5 columns of app pad records */

typedef void (*voice_render_fn)(uint8_t *pad, uint8_t *voice, void *scratch, void *tmp, void *out, void *block);
typedef void (*voice_stage_fn)(uint8_t *pad, uint8_t *voice, void *out, void *block);
typedef void (*voice_mod_fn)(void *mod, int frames);
typedef int (*wave_len_fn)(void *wave);
typedef int (*wave_read1_fn)(void *wave, float *dst, int n, int pos, int chan);
typedef int (*wave_read2_fn)(void *wave, float *l, float *r, int n, int pos);
typedef int (*buf_stereo_fn)(void *buf, float **l, float **r);
typedef float (*db_fn)(float db);
#define fw_voice_render ((voice_render_fn)FN(0x080aec34))
#define fw_voice_stage  ((voice_stage_fn)FN(0x080ad870))
#define fw_voice_mod    ((voice_mod_fn)FN(0x080ba3e4))
#define fw_wave_len     ((wave_len_fn)FN(0x080a45ac))
#define fw_wave_read1   ((wave_read1_fn)FN(0x080a4500))
#define fw_wave_read2   ((wave_read2_fn)FN(0x080a44c8))
#define fw_buf_stereo   ((buf_stereo_fn)FN(0x080a32d4))
#define fw_db_to_gain   ((db_fn)FN(0x0809f5b4))
typedef void (*clip_render_fn)(uint8_t *pad, int a2, uint8_t *voice, int a4, uint8_t *flag, void *out, void *block);
typedef void (*buf_limit_fn)(void *buf, int n);
#define fw_clip_render  ((clip_render_fn)FN(0x080b5aa8))
#define fw_buf_limit    ((buf_limit_fn)FN(0x080a31c8))        /* frames = n, if n fits */

static const float length_quarters[11] = {4, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512};   /* Custom counts as 1 bar */
/*
 * Status, shown in the setting's own value: "Replace REC" while the pad records and plays its loop, otherwise a short
 * reason it doesn't (the first Live Loop pad's): "?" no pad with Live Loop on seen yet, "tempo" no valid tempo, "mem"
 * no memory for loops, "full" four loops in use, "len" the Length is too long (or too short) for a loop, "play" the pad
 * isn't playing; when the pad plays its sample anyway, why its voice skipped the loop: "nohook" the voice render the
 * mod hooks didn't run at all, "p012>12" it ran but never for this pad (bank, row, column it saw > the Live Loop pad's row, column), "sync" the loop wasn't ready that block, "size"
 * the voice block is a different size from the engine block, "voice" the voice was idle. The value names live in RAM so they can change; the screen shows the new text when it next redraws.
 */
enum { ST_NONE, ST_TEMPO, ST_MEM, ST_FULL, ST_LEN, ST_PLAY, ST_REC, ST_NOHOOK, ST_PAD, ST_SYNC, ST_SIZE, ST_VOICE };
static const char *const status_text[] = {"?", "tempo", "mem", "full", "len", "play", "REC",
                                          "nohook", "pad", "sync", "size", "voice"};
#define NAMES  ((const char **)(MOD_RAM + 0x3800u))   /* Off, Replace .., Overdub .. */
#define NAME_R ((char *)(MOD_RAM + 0x3840u))   /* 32 bytes each */
#define NAME_O ((char *)(MOD_RAM + 0x3860u))
#define STATUS (*(volatile uint8_t *)(MOD_RAM + 0x3830u))
#define SEEN_ID    (*(volatile uint32_t *)(MOD_RAM + 0x3838u))   /* pad id (+0x18) of the last active voice rendered */
#define WANT_PAD   (*(volatile uint8_t *)(MOD_RAM + 0x383cu))    /* the Live Loop pad the status is about */
#define HOOK_CALLS (*(volatile uint32_t *)(MOD_RAM + 0x3834u))   /* loop_voice_render calls since the last block */

static void name_set(char *dst, const char *mode, const char *st)
{
    while (*mode)
        *dst++ = *mode++;
    *dst++ = ' ';
    while (*st)
        *dst++ = *st++;
    *dst = 0;
}

/* "pad" status, short enough for the screen: "p<bank><row><col the render saw>><row><col of the Live Loop pad>" */
static void pad_text(char *t)
{
    uint32_t id = SEEN_ID;
    *t++ = 'p';
    *t++ = (char)('0' + ((id >> 16) & 15));
    *t++ = (char)('0' + ((id >> 8) & 15));
    *t++ = (char)('0' + (id & 15));
    *t++ = '>';
    *t++ = (char)('0' + WANT_PAD / 5);
    *t++ = (char)('0' + WANT_PAD % 5);
    *t = 0;
}

static void status_show(unsigned st)
{
    if (st == STATUS && st != ST_PAD && NAMES[1] == NAME_R)
        return;
    STATUS = (uint8_t)st;
    char t[16];
    const char *txt = status_text[st];
    if (st == ST_PAD) {
        pad_text(t);
        txt = t;
    }
    name_set(NAME_R, "Replace", txt);
    name_set(NAME_O, "Overdub", txt);
    NAMES[0] = "Off";
    NAMES[1] = NAME_R;
    NAMES[2] = NAME_O;
}

struct slot {
    int8_t pad;                   /* app pad index (row * 5 + col), -1 free */
    uint8_t mode;
    uint8_t why;                  /* why its voice last skipped the loop (ST_SYNC ..), 0 if it never got there */
    uint8_t unused;
    int32_t len;                  /* loop length in frames */
    int32_t prefill;              /* frames of the first pass still to come from the pad's sample */
    void *wave;                   /* the pad's sample, as last seen by its voice */
    uint32_t played;              /* block number the play buffer was output in */
    int16_t *l, *r;               /* the loop (SDRAM), 16 bit */
    uint32_t ready;               /* block number the play buffer was filled for */
};

struct looper {
    uint32_t magic;
    uint32_t block;               /* block counter */
    int32_t frames;               /* frames in the current block */
    int8_t pad_slot[PADS];
    struct slot slot[SLOTS];
};
#define LP ((struct looper *)(MOD_RAM + 0x100u))
#define LMAGIC 0x4c4f4f50u        /* "LOOP" */
#define PLAY_L(i) ((float *)(MOD_RAM + 0x1000u + (unsigned)(i) * 0x800u))
#define PLAY_R(i) ((float *)(MOD_RAM + 0x1400u + (unsigned)(i) * 0x800u))
#define RESAM_L   ((float *)(MOD_RAM + 0x3000u))
#define RESAM_R   ((float *)(MOD_RAM + 0x3400u))
#define MAX_BLOCK 256

/*
 * The loop memory. The bitbox micro sets aside nearly all of its 64 MB SDRAM for samples at startup and leaves about
 * 7 MB between the bump allocator (FUN_08042dc0, bottom up) and the top-down allocator (FUN_08042e58, which the
 * firmware uses at run time for preset files, names and lists). Both hang the unit when they meet ("No more extended
 * memory"): reserving 16 MB at boot did exactly that on a real unit. So the loops share one block of at most 4 MB,
 * taken from the bump allocator the first time a pad needs a loop, and only while MARGIN stays free for the firmware.
 * ARENA holds its address (0 = not taken yet), CAP the frames per loop.
 */
#define ARENA      (*(int16_t *volatile *)(MOD_RAM + 0x0040u))
#define CAP        (*(volatile uint32_t *)(MOD_RAM + 0x0044u))
#define SDRAM_LOW  (*(volatile uint32_t *)0x24000088u)    /* bump allocator: next free byte, bottom up */
#define SDRAM_HIGH (*(volatile uint32_t *)0x2400008cu)    /* top-down allocator: lowest used byte */
#define MARGIN     (3u << 20)

/* Free SDRAM between the two allocators, in bytes. */
static uint32_t sdram_free(void)
{
    uint32_t lo = SDRAM_LOW, hi = SDRAM_HIGH;
    return hi > lo ? hi - lo : 0;
}

/* Takes the loop memory if it isn't taken yet; 1 when the loops have memory. */
static int take_arena(void)
{
    if (ARENA)
        return 1;
    uint32_t free = sdram_free();
    if (free < MARGIN + (1u << 20))
        return 0;
    uint32_t bytes = free - MARGIN;
    if (bytes > ARENA_MAX)
        bytes = ARENA_MAX;
    bytes &= ~0xffffu;
    CAP = bytes / (SLOTS * 4u);                       /* 2 channels x 16 bit */
    ARENA = (int16_t *)fw_sdram_alloc(bytes);
    for (int i = 0; i < SLOTS; i++) {
        LP->slot[i].l = ARENA + (unsigned)i * 2u * CAP;
        LP->slot[i].r = LP->slot[i].l + CAP;
    }
    return 1;
}

/* Boot: no memory is taken here (see above), only the bookkeeping is reset. */
void looper_boot(void)
{
    ARENA = 0;
    CAP = 0;
    LP->magic = 0;
}

static void looper_init(void)
{
    for (int i = 0; i < PADS; i++)
        LP->pad_slot[i] = -1;
    for (int i = 0; i < SLOTS; i++) {
        struct slot *s = &LP->slot[i];
        s->pad = -1;
        s->mode = 0;
        s->len = 0;
        s->prefill = 0;
        s->wave = 0;
        s->played = 0;
        s->l = ARENA ? ARENA + (unsigned)i * 2u * CAP : 0;
        s->r = ARENA ? s->l + CAP : 0;
    }
    LP->block = 0;
    LP->magic = LMAGIC;
}

static int pad_index_of(const uint8_t *pad)
{
    if (!pad_ptr_ok(pad))
        return -1;
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    if (row >= 4 || col >= 5)
        return -1;
    return (int)(row * 5 + col);
}

static inline const void *store_of(int index)
{
    return (const void *)(APP_PADS + (unsigned)(index / 5) * 0xf0u + (unsigned)(index % 5) * 0x30u);
}

static inline int store_live(const void *store)
{
    return *(const uint16_t *)((const uint8_t *)store + 10) != 0 && *(void *const *)((const uint8_t *)store + 4) != 0;
}

/* Loop position for the block starting at engine sample time `now`: the song position in samples, modulo the loop.
   Transport (ctx[0]): +0 now (64-bit samples), +8 anchor ticks, +0x10 anchor samples, +0x18 anchor tempo (BPM). */
static int32_t loop_phase(const uint8_t *transport, int64_t now, int32_t len, float tempo)
{
    int64_t anchor_ticks = *(const int64_t *)(transport + 8);
    int64_t anchor_samples = *(const int64_t *)(transport + 0x10);
    double spt = 48000.0 * 60.0 / ((double)tempo * 960.0);
    double song = (double)anchor_ticks * spt + (double)(now - anchor_samples);
    double turns = song / (double)len;
    int64_t whole = (int64_t)turns;
    if ((double)whole > turns)
        whole -= 1;
    int32_t ph = (int32_t)(song - (double)whole * (double)len + 0.5);
    if (ph >= len)
        ph -= len;
    if (ph < 0)
        ph += len;
    return ph;
}

static inline int16_t to16(float x)
{
    float v = x * 32768.0f;
    v = v > 32767.0f ? 32767.0f : v < -32768.0f ? -32768.0f : v;
    return (int16_t)(v + (v >= 0.0f ? 0.5f : -0.5f));
}

static void fetch_wave(void *wave, int pos, float *l, float *r, int n)
{
    int have = 0;
    if (wave) {
        int len = fw_wave_len(wave);
        have = len - pos;
        have = have < 0 ? 0 : have > n ? n : have;
        if (have > 0) {
            if (*((const uint8_t *)wave + 0x1c)) {
                if (!fw_wave_read2(wave, l, r, have, pos))
                    have = 0;
            } else {
                if (!fw_wave_read1(wave, l, have, pos, 0))
                    have = 0;
                for (int i = 0; i < have; i++)
                    r[i] = l[i];
            }
        }
    }
    for (int i = have; i < n; i++)
        l[i] = r[i] = 0.0f;
}

struct input {
    const float *l, *r;
    float gain;
};

static void bus_chans(const uint8_t *bus, const float **l, const float **r)
{
    if (bus[0x10]) {                                 /* silent */
        *l = *r = 0;
        return;
    }
    *l = *(float *const *)(bus + 8);
    *r = bus[0x11] ? *(float *const *)(bus + 12) : *l;
}

/* Called before the engine processes a block (engine_block). ctx = engine + 0x127d8. */
void looper_block(uint8_t *ctx, int n)
{
    if (LP->magic != LMAGIC)
        looper_init();
    LP->block++;
    LP->frames = n;
    if (n <= 0 || n > MAX_BLOCK)
        return;
    const uint8_t *transport = *(const uint8_t **)ctx;
    float tempo = transport ? *(const float *)(transport + 0x18) : 0.0f;
    if (!(tempo >= 20.0f && tempo <= 400.0f)) {
        status_show(ST_TEMPO);
        return;
    }
    int64_t now = *(const int64_t *)transport;
    const void *rec = (const void *)APP_REC;
    int per_pad = fw_store_get(rec, P_RECCONF) != 0;

    /* inputs: bus 0 = In 1/2, bus 3 = what Resam records (the previous block's, kept by looper_after) */
    const float *in_l, *in_r;
    bus_chans(ctx + 0x1588c, &in_l, &in_r);
    float gain = fw_db_to_gain((float)fw_store_get(rec, P_GAIN) / 1000.0f);

    unsigned st = ST_NONE;
    int hooked = HOOK_CALLS != 0;
    HOOK_CALLS = 0;
#define STATUS_OF(x) do { if (st == ST_NONE) st = (x); } while (0)
    for (int p = 0; p < PADS; p++) {
        const void *store = store_of(p);
        int mode = store_live(store) ? fw_store_get(store, P_LIVELOOP) : 0;
        int si = LP->pad_slot[p];
        if (mode < 1 || mode > 2) {
            if (si >= 0) {
                LP->slot[si].pad = -1;
                LP->pad_slot[p] = -1;
            }
            continue;
        }
        if (si < 0) {
            if (!take_arena()) {
                STATUS_OF(ST_MEM);
                continue;                           /* no memory for loops: stock playback */
            }
            for (int i = 0; i < SLOTS; i++)
                if (LP->slot[i].pad < 0) {
                    si = i;
                    break;
                }
            if (si < 0) {
                STATUS_OF(ST_FULL);
                continue;                           /* all four loops in use */
            }
            struct slot *s = &LP->slot[si];
            s->pad = (int8_t)p;
            s->len = 0;
            s->wave = 0;
            LP->pad_slot[p] = (int8_t)si;
        }
        struct slot *s = &LP->slot[si];
        s->mode = (uint8_t)mode;
        const void *rs = per_pad ? store : rec;
        unsigned li = (unsigned)fw_store_get(rs, P_LENGTH);
        float q = li < 11 ? length_quarters[li] : 4.0f;
        int32_t len = (int32_t)(q * 48000.0f * 60.0f / tempo + 0.5f);
        if (len < n || (uint32_t)len > CAP) {
            s->len = 0;                             /* too short or too long for a loop buffer: stock playback */
            STATUS_OF(ST_LEN);
            continue;
        }
        if (s->played == LP->block - 1)         /* did its voice play the loop last block? */
            STATUS_OF(ST_REC);
        else {
            if (st == ST_NONE)
                WANT_PAD = (uint8_t)p;
            STATUS_OF(!hooked ? ST_NOHOOK : s->why ? s->why : ST_PAD);
        }
        s->why = 0;
        if (len != s->len) {
            s->len = len;
            s->prefill = len;
        }
        int source = fw_store_get(rs, P_RECINPUT);
        const float *sl = in_l, *sr = in_r;
        if (source == 1)
            sr = sl;
        else if (source == 2)
            sl = sr;
        else if (source == 3) {
            sl = RESAM_L;
            sr = RESAM_R;
        }
        float g = source == 3 ? 1.0f : gain;
        float *pl = PLAY_L(si), *pr = PLAY_R(si);
        int32_t ph = loop_phase(transport, now, len, tempo);
        int done = 0;
        while (done < n) {
            int k = n - done;
            if (k > len - ph)
                k = len - ph;
            if (s->prefill > 0 && k > s->prefill)
                k = s->prefill;                     /* the first pass ends mid-block */
            int16_t *bl = s->l + ph, *br = s->r + ph;
            float *ol = pl + done, *or_ = pr + done;
            if (s->prefill > 0) {                   /* first pass: the pad's sample is the loop so far */
                fetch_wave(s->wave, ph, ol, or_, k);
                s->prefill -= k;
            } else {
                for (int i = 0; i < k; i++) {
                    ol[i] = (float)bl[i] * (1.0f / 32768.0f);
                    or_[i] = (float)br[i] * (1.0f / 32768.0f);
                }
            }
            for (int i = 0; i < k; i++) {
                float x = sl ? sl[done + i] * g : 0.0f, y = sr ? sr[done + i] * g : 0.0f;
                if (mode == 2) {
                    x += ol[i];
                    y += or_[i];
                }
                bl[i] = to16(x);
                br[i] = to16(y);
            }
            done += k;
            ph += k;
            if (ph >= len)
                ph = 0;
        }
        s->played = LP->block - 1;                 /* play buffer ready, not output yet */
        s->ready = LP->block;
    }
    status_show(st);
}

/* After the engine's block: keep the Resam source (bus 3) for the next block. */
void looper_after(uint8_t *ctx, int n)
{
    if (n <= 0 || n > MAX_BLOCK)
        return;
    const float *l, *r;
    bus_chans(ctx + 0x158c8, &l, &r);
    for (int i = 0; i < n; i++) {
        RESAM_L[i] = l ? l[i] : 0.0f;
        RESAM_R[i] = r ? r[i] : 0.0f;
    }
}

/* In place of the per-voice render (bl at 0x080b25d6). */
void loop_voice_render(uint8_t *pad, uint8_t *voice, void *scratch, void *tmp, void *out, void *block)
{
    int p = LP->magic == LMAGIC ? pad_index_of(pad) : -1;
    int si = p >= 0 ? LP->pad_slot[p] : -1;
    struct slot *s = si >= 0 ? &LP->slot[si] : 0;
    HOOK_CALLS++;
    if (voice[0])
        SEEN_ID = pad_ptr_ok(pad) ? *(const uint32_t *)(pad + 0x18) : 0xeeeeeeu;
    if (s && s->len && (voice[0] || !s->why))     /* an idle voice of the pad doesn't hide an active one's reason */
        s->why = !voice[0] ? ST_VOICE : s->ready != LP->block ? ST_SYNC : fw_buf_frames(block) != LP->frames ? ST_SIZE : 0;
    if (!s || s->len == 0 || s->ready != LP->block || !voice[0]) {
        fw_voice_render(pad, voice, scratch, tmp, out, block);
        return;
    }
    void *wave = *(void **)(voice + 0xc);
    if (wave != s->wave) {                          /* new sample on the pad: the loop restarts from it */
        s->wave = wave;
        s->prefill = s->len;
    }
    int n = fw_buf_frames(block);
    if (n != LP->frames) {
        fw_voice_render(pad, voice, scratch, tmp, out, block);
        return;
    }
    fw_voice_mod(voice + 0x4e0, n);
    float *l, *r;
    fw_buf_stereo(out, &l, &r);
    const float *pl = PLAY_L(si), *pr = PLAY_R(si);
    int first = s->played != LP->block;            /* one voice per pad plays the loop; others stay silent */
    s->played = LP->block;
    for (int i = 0; i < n; i++) {
        l[i] = first ? pl[i] : 0.0f;
        r[i] = first ? pr[i] : 0.0f;
    }
    fw_voice_stage(pad, voice, out, block);
}

/*
 * Clip and slicer pads render through FUN_080b5aa8(pad, a2, voice, a4, flag, out, block) instead (bl at 0x080b7dce,
 * 0x080b7dec, 0x080b7fb0: voice A at pad + 0x260, B at + 0x670 for crossfades). It fills block temp 1 from the sample,
 * takes its channels (bl FUN_080a3228 at 0x080b5cb4), runs the envelope and filter on them and adds them to out. For a
 * Live Loop pad the stock render runs as usual (so the voice starts, stops and crossfades as stock), and the loop
 * takes the sample's place when it takes the channels: the play buffer for the pad's first active voice, silence for
 * the other.
 */
#define CLIP_PARK (*(volatile int32_t *)(MOD_RAM + 0x3880u))   /* 1 + slot for the voice in render, -1 silence, 0 */

void loop_clip_render(uint8_t *pad, int a2, uint8_t *voice, int a4, uint8_t *flag, void *out, void *block)
{
    int p = LP->magic == LMAGIC ? pad_index_of(pad) : -1;
    int si = p >= 0 ? LP->pad_slot[p] : -1;
    struct slot *s = si >= 0 ? &LP->slot[si] : 0;
    HOOK_CALLS++;
    if (voice[0])
        SEEN_ID = pad_ptr_ok(pad) ? *(const uint32_t *)(pad + 0x18) : 0xeeeeeeu;
    int n = fw_buf_frames(out);
    if (s && s->len && (voice[0] || !s->why))
        s->why = !voice[0] ? ST_VOICE : s->ready != LP->block ? ST_SYNC : n != LP->frames ? ST_SIZE : 0;
    CLIP_PARK = 0;
    if (s && s->len && s->ready == LP->block && voice[0] && !voice[0x148] && n == LP->frames) {
        void *wave = *(void **)(pad + 0x24);
        if (wave != s->wave) {                      /* new sample on the pad: the loop restarts from it */
            s->wave = wave;
            s->prefill = s->len;
        }
        CLIP_PARK = s->played != LP->block ? si + 1 : -1;
        s->played = LP->block;
    }
    fw_clip_render(pad, a2, voice, a4, flag, out, block);
    CLIP_PARK = 0;
}

int loop_clip_chans(void *buf, float **l, float **r)
{
    int park = CLIP_PARK;
    if (!park)
        return fw_buf_chans(buf, l, r);
    int n = fw_buf_frames(buf);
    fw_buf_stereo(buf, l, r);
    fw_buf_limit(buf, n);
    const float *pl = park > 0 ? PLAY_L(park - 1) : 0, *pr = park > 0 ? PLAY_R(park - 1) : 0;
    for (int i = 0; i < n; i++) {
        (*l)[i] = pl ? pl[i] : 0.0f;
        (*r)[i] = pr ? pr[i] : 0.0f;
    }
    return 1;
}

/* Registration: Live Loop list, id 0x17c, xml "liveloop" (called from mod_register). */
void looper_register(void *table)
{
    STATUS = 0xff;
    status_show(ST_NONE);
    fw_register_list(table, P_LIVELOOP, "Live Loop:", NAMES, 3, "liveloop");
}
