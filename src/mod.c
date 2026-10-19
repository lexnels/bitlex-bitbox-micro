/*
 * Glue: the one-time boot hook (new parameters, memory), the per-block engine hook, and the pad settings stores.
 */
#include "fw.h"
#include "mod.h"

#define P_INTERP   0xd2
#define P_LIVELOOP 0x17c

/* Replaces the Interp list registration (bl at 0x0806b34a, inside the registry's one-time setup FUN_08069f00):
   Fidelity, then the mod's own parameters, then its memory. */
void mod_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    interp_register(table, param, label, names, count, xml);
    looper_register(table);
    grain_register(table);
    looper_boot();
}

/* Replaces the pad settings store's "Interp = Normal" entry (FUN_08089548, pad types 3 and 0x45): the entry, then
   the mod's per-pad settings. Stores hold 64 entries; these types use 56 and 37, the mod adds 5. */
void mod_pad_store(void *store, unsigned param, int value)
{
    fw_store_add(store, param, value);
    fw_store_add(store, P_LIVELOOP, 0);
    grain_pad_store(store);
}

typedef void (*engine_fn)(uint8_t *engine, void *out, void *events);
#define fw_engine_process ((engine_fn)FN(0x08096530))
#define CTX_OFF 0x127d8u          /* engine -> graph context (FUN_08093d44, FUN_08096530) */
#define BUS0    0x1588cu          /* ctx -> bus 0 (In 1/2) */

/* Replaces the engine's block process call in the audio task (bl at 0x0809418a). */
void engine_block(uint8_t *engine, void *out, void *events)
{
    uint8_t *ctx = engine + CTX_OFF;
    int n = fw_buf_frames(ctx + BUS0);
    grain_clock(*(const uint8_t **)ctx, n);
    looper_block(ctx, n);
    fw_engine_process(engine, out, events);
    looper_after(ctx, n);
}
