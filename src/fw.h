/*
 * Stock bitbox micro 2.3.4 functions and data the cave code calls or reads. Every address here was located in the
 * stock image (see the technical notes in README.md); none of them are 1010music code, only where it lives.
 */
#ifndef FW_H
#define FW_H
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

/* Audio buffer {int max; int frames (0 = max); float *L; float *R; u8 silent; u8 stereo} */
typedef int (*buf_int_fn)(void *buf);
typedef int (*buf_chans_fn)(void *buf, float **left, float **right);
#define fw_buf_frames ((buf_int_fn)FN(0x080a31e0))
#define fw_buf_silent ((buf_int_fn)FN(0x080a31ec))
#define fw_buf_chans  ((buf_chans_fn)FN(0x080a3228))     /* R = 0 when the buffer is mono */

/* Modulated parameter value (an engine param block entry) */
typedef float (*param_fn)(void *param);
#define fw_param ((param_fn)FN(0x080a19f4))

/* Filter curves: knob 0..1 -> Hz, Res 0..1 -> Q */
typedef float (*curve_fn)(float x);
#define fw_cutoff_hz ((curve_fn)FN(0x080a01bc))
#define fw_res_q     ((curve_fn)FN(0x080a0240))

/* Parameter registry: list registration (type 5) and numeric registration */
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max,
                                const char *xml);
#define fw_register_list ((register_list_fn)FN(0x08069e7c))
#define fw_register_num  ((register_num_fn)FN(0x08069ed4))

/* App settings stores: {vtable; entries {u16 id; int value}[]; ...; u16 count @+10; u16 cap @+12} */
typedef int (*store_get_fn)(const void *store, unsigned param);
typedef void (*store_add_fn)(void *store, unsigned param, int value);
#define fw_store_get ((store_get_fn)FN(0x080894d0))
#define fw_store_add ((store_add_fn)FN(0x0808951e))

#define APP        0x24013cb0u              /* the app object */
#define APP_PADS   (APP + 0x1840u)          /* pad settings: + row * 0xf0 + col * 0x30 (FUN_08076d54) */
#define APP_REC    (APP + 0x7fd0u)          /* global recording settings */
#define APP_GLOBAL (APP + 0x8008u)          /* global settings */

/* SDRAM bump allocator (permanent; used by the engine at boot) */
typedef void *(*alloc_fn)(unsigned size);
#define fw_sdram_alloc ((alloc_fn)FN(0x08042dc0))

/* Engine pad id (node + 0x18) = bank << 16 | row << 8 | col */
static inline int pad_ptr_ok(const void *p)
{
    uint32_t a = (uint32_t)p;
    return (a >= 0x20000000u && a < 0x20020000u) || (a >= 0x24000000u && a < 0x24080000u) ||
           (a >= 0xc0000000u && a < 0xc4000000u);
}

static inline const void *pad_store(const uint8_t *pad)
{
    if (!pad_ptr_ok(pad))
        return 0;
    uint32_t id = *(const uint32_t *)(pad + 0x18);
    unsigned row = (id >> 8) & 0xff, col = id & 0xff;
    if (row >= 4 || col >= 5)
        return 0;
    return (const void *)(APP_PADS + row * 0xf0u + col * 0x30u);
}

static inline int pad_setting(const uint8_t *pad, unsigned param)
{
    const void *s = pad_store(pad);
    return s ? fw_store_get(s, param) : 0;
}

/* Mod state in SRAM4 (D3, 64 KB at 0x38000000): nothing in the stock image uses it. */
#define MOD_RAM 0x38000000u

#endif
