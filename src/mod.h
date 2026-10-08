/* Shared declarations between the mod's source files, and the layout of its state in SRAM4 (MOD_RAM). */
#ifndef MOD_H
#define MOD_H
#include <stdint.h>

/* MOD_RAM (0x38000000, 64 KB, unused by the stock firmware; not cleared at boot, so every user checks a magic):
 *   0x0000  filter.c   voice-reader park (12 bytes)
 *   0x0040  looper.c   loop buffer pointers (16 bytes)
 *   0x0100  looper.c   looper state
 *   0x1000  looper.c   play buffers, 4 x (L 1 KB, R 1 KB)
 *   0x3000  looper.c   Resam source, L 1 KB, R 1 KB
 */

void interp_register(void *table, int param, const char *label, const char *const *names, int count, const char *xml);
void looper_register(void *table);
void looper_boot(void);
void looper_block(uint8_t *ctx, int n);
void looper_after(uint8_t *ctx, int n);

#endif
