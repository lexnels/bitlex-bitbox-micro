#!/bin/sh
# Compile src/ into the code cave: out/cave.elf + out/cave.bin (appended after the stock image by patches/cave.py)
set -e
cd "$(dirname "$0")"
mkdir -p out
CFLAGS="-mcpu=cortex-m7 -mthumb -mfloat-abi=hard -mfpu=fpv5-d16 -Os -ffreestanding -nostdlib -fno-builtin -Wall -Wextra -Werror"
arm-none-eabi-gcc $CFLAGS -T src/cave.ld -Wl,-e,0 -o out/cave.elf \
  src/filter.c src/filter_thunk.S
arm-none-eabi-objcopy -O binary -j .cave out/cave.elf out/cave.bin
arm-none-eabi-size -A out/cave.elf | grep -E 'cave|data|bss'
