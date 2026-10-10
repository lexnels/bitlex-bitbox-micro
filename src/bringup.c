/*
 * Hardware bring-up: registration variants for bisecting a boot failure (patches/bring_*.py). Not part of the mod.
 */
#include "fw.h"
#include "mod.h"

/* Fidelity + Live Loop parameter, no memory */
void bring_reg_live(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    interp_register(table, param, label, names, count, xml);
    looper_register(table);
}

/* Fidelity + the loop memory (SDRAM), no parameter */
void bring_reg_boot(void *table, int param, const char *label, const char *const *names, int count, const char *xml)
{
    interp_register(table, param, label, names, count, xml);
    looper_boot();
}
