"""Disassemble the stock image: python3 tools/dis.py <addr> [count]"""
import os, struct, sys
import capstone
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x08040000
data = open(os.path.join(ROOT, "firmware", "MICRO.bin"), "rb").read()
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
md.detail = False


def u32(a):
    return struct.unpack_from("<I", data, a - BASE)[0]


def dis(a, n=40):
    return list(md.disasm(data[a - BASE:a - BASE + n * 4 + 8], a))[:n]


if __name__ == "__main__":
    a = int(sys.argv[1], 16)
    for i in dis(a, int(sys.argv[2]) if len(sys.argv) > 2 else 40):
        extra = ""
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm = int(i.op_str.split("#")[-1].rstrip("]"), 16)
                la = ((i.address + 4) & ~3) + imm
                extra = f"   ; ={u32(la):#x}"
            except Exception:
                pass
        print(f"{i.address:#010x}  {i.bytes.hex():10} {i.mnemonic:8} {i.op_str}{extra}")
