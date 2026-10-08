"""Unicorn harness: run functions of a (stock or patched) MICRO.bin against fake objects.

The image is mapped at 0x08040000 with the STM32H7 RAM regions around it. Firmware functions can be stubbed by
address; `malloc` gets a bump allocator in AXI SRAM so constructors can run.
"""
import os
import struct
import subprocess

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import (UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                               UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_CPU_ARM_MAX)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x08040000
STOCK = os.path.join(ROOT, "firmware", "MICRO.bin")
STACK, RET = 0x2407F000, 0x081FFFF0
HEAP = 0x30000000                     # SRAM1..3 used as a scratch heap in the emulator only
ARGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
REGIONS = [(0x00000000, 0x10000), (0x20000000, 0x20000), (0x24000000, 0x80000), (0x30000000, 0x48000),
           (0x38000000, 0x10000), (0x38800000, 0x1000), (0x40000000, 0x100000), (0x58000000, 0x100000),
           (0xC0000000, 0x2000000), (0xE0000000, 0x100000)]
MALLOC = 0x08042DC0                   # FUN_08042dc0(size, ?) -> ptr


class Emu:
    def __init__(self, image=STOCK, elf=None):
        self.sym = {}
        if elf:
            out = subprocess.run(["arm-none-eabi-nm", elf], capture_output=True, text=True, check=True).stdout
            self.sym = {l.split()[2]: int(l.split()[0], 16) for l in out.splitlines() if len(l.split()) == 3}
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.ctl_set_cpu_model(UC_CPU_ARM_MAX)          # FPv5 (vfma, vsel) like the Cortex-M7
        uc.mem_map(0x08000000, 0x200000)
        self.image = open(image, "rb").read()
        uc.mem_write(BASE, self.image)
        for base, size in REGIONS:
            uc.mem_map(base, size)
        uc.mem_write(RET, b"\x00\xbf\x00\xbf")
        uc.reg_write(UC_ARM_REG_C1_C0_2, 0xF << 20)   # FPU on
        uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.hooked, self.handlers, self.calls = set(), {}, []
        self.heap = HEAP
        self.stub(MALLOC, lambda: self.ret(self.malloc(self.arg(0))))

    # ---- stubs
    def _hook(self, addr):
        if addr not in self.hooked:
            self.hooked.add(addr)
            self.uc.hook_add(UC_HOOK_CODE, lambda uc, a, size, _: self.handlers[a]() if a in self.handlers else None,
                             begin=addr, end=addr)

    def stub(self, addr, fn=None, value=None):
        """Replace the firmware function at addr. fn() runs instead; it may call self.ret(v) itself."""
        addr &= ~1
        self._hook(addr)

        def run():
            if fn:
                r = fn()
                if r == "keep":           # observe only: let the real function run
                    return
            if self.uc.reg_read(UC_ARM_REG_PC) == addr:
                self.ret(value)
        self.handlers[addr] = run

    def malloc(self, n):
        p = self.heap
        self.heap = (self.heap + n + 7) & ~7
        self.uc.mem_write(p, bytes(n))
        return p

    def arg(self, n):
        if n < 4:
            return self.uc.reg_read(ARGS[n])
        return self.r32(self.uc.reg_read(UC_ARM_REG_SP) + 4 * (n - 4), signed=False)

    def ret(self, value=None):
        if value is not None:
            self.uc.reg_write(UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.uc.reg_write(UC_ARM_REG_PC, self.uc.reg_read(UC_ARM_REG_LR))

    def call(self, target, *args, count=50_000_000, stack_args=()):
        addr = self.sym[target] if isinstance(target, str) else target
        for reg, v in zip(ARGS, args):
            self.uc.reg_write(reg, v & 0xFFFFFFFF)
        sp = STACK - 4 * len(stack_args)
        for i, v in enumerate(stack_args):
            self.w32(sp + 4 * i, v)
        self.uc.reg_write(UC_ARM_REG_SP, sp)
        self.uc.reg_write(UC_ARM_REG_LR, RET | 1)
        self.uc.emu_start(addr | 1, RET, count=count)
        pc = self.uc.reg_read(UC_ARM_REG_PC)
        assert pc == RET, f"did not return from {target if isinstance(target, str) else hex(target)} (pc {pc:#x})"
        return self.uc.reg_read(UC_ARM_REG_R0)

    # ---- memory
    def rd(self, a, n):
        return bytes(self.uc.mem_read(a, n))

    def wr(self, a, b):
        self.uc.mem_write(a, bytes(b))

    def r8(self, a):
        return self.rd(a, 1)[0]

    def r16(self, a):
        return struct.unpack("<H", self.rd(a, 2))[0]

    def r32(self, a, signed=True):
        return struct.unpack("<i" if signed else "<I", self.rd(a, 4))[0]

    def rf(self, a):
        return struct.unpack("<f", self.rd(a, 4))[0]

    def w8(self, a, v):
        self.wr(a, bytes([v & 0xFF]))

    def w16(self, a, v):
        self.wr(a, struct.pack("<H", v & 0xFFFF))

    def w32(self, a, v):
        self.wr(a, struct.pack("<I", v & 0xFFFFFFFF))

    def wf(self, a, v):
        self.wr(a, struct.pack("<f", v))

    def cstr(self, a, n=64):
        if not a:
            return None
        try:
            return self.rd(a, n).split(b"\0")[0].decode("latin1")
        except Exception:
            return f"<{a:#x}>"
