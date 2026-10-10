/* Code cave: appended directly after the stock image (which ends at 0x080E3E90). */
MEMORY { CAVE (rx) : ORIGIN = 0x080E3E90, LENGTH = 0x18000 }
SECTIONS {
  .cave : { *(.text .text.* .rodata .rodata.*) } > CAVE
  /DISCARD/ : { *(.data .data.* .bss .bss.* COMMON .ARM.exidx* .comment) }
}
