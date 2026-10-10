"""Bring-up test 7: Fidelity + the loop memory allocation at boot (16 MB SDRAM, pointers in SRAM4). Nothing else."""
from thumb import hooker, symbols

hook = hooker(symbols())

PATCHES = [
    hook(0x0806B34A, 0x08069E7C, "bring_reg_boot"),
]
