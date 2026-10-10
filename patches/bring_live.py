"""Bring-up test 5: Fidelity + the Live Loop parameter and its pad store entries. No memory, no engine hook."""
from thumb import hooker, symbols

hook = hooker(symbols())

PATCHES = [
    hook(0x0806B34A, 0x08069E7C, "bring_reg_live"),
    hook(0x08089740, 0x0808951E, "mod_pad_store"),
    hook(0x08089960, 0x0808951E, "mod_pad_store"),
]
