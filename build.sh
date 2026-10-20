#!/bin/sh
# Compile src/ into the code cave: out/cave.elf + out/cave.bin (appended after the stock image by patches/cave.py).
# The cave is code and constants only: the linker script discards .data / .bss, so a writable static would silently
# vanish; this script fails the build if any object has one. Mod state lives in SRAM4 at fixed addresses (src/mod.h).
set -e
cd "$(dirname "$0")"
mkdir -p out/obj
CFLAGS="-mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16 -Os -ffreestanding -nostdlib -fno-builtin -Wall -Wextra -Werror"
SRCS="src/mod.c src/filter.c src/filter_thunk.S src/looper.c src/grain.c src/bringup.c"
OBJS=""
for s in $SRCS; do
  o="out/obj/$(basename "$s" | sed 's/\.[cS]$/.o/')"
  arm-none-eabi-gcc $CFLAGS -c -o "$o" "$s"
  if arm-none-eabi-size -A "$o" | awk '$1 ~ /^\.(data|bss)/ && $2 > 0 {bad=1} END {exit !bad}'; then
    echo "error: $s has writable static data (.data/.bss); keep state in MOD_RAM" >&2
    exit 1
  fi
  OBJS="$OBJS $o"
done
arm-none-eabi-gcc $CFLAGS -T src/cave.ld -Wl,-e,0 -o out/cave.elf $OBJS -lgcc
arm-none-eabi-objcopy -O binary -j .cave out/cave.elf out/cave.bin
arm-none-eabi-size -A out/cave.elf | grep -E 'cave'
