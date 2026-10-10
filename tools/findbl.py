"""List every BL/B.W call site to a target in the stock image: python3 tools/findbl.py <hex target> [image]"""
import struct
import sys

BASE = 0x08040000


def bl_target(h1, h2, at):
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xD000) not in (0xD000, 0x9000):
        return None
    s = (h1 >> 10) & 1
    i1 = 1 - (((h2 >> 13) & 1) ^ s)
    i2 = 1 - (((h2 >> 11) & 1) ^ s)
    imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    if s:
        imm -= 1 << 25
    return at + 4 + imm


def sites(data, target):
    out = []
    for o in range(0, len(data) - 4, 2):
        h1, h2 = struct.unpack_from("<HH", data, o)
        if bl_target(h1, h2, BASE + o) == target & ~1:
            out.append((BASE + o, "bl" if h2 & 0x4000 else "b.w"))
    return out


if __name__ == "__main__":
    img = sys.argv[2] if len(sys.argv) > 2 else "firmware/MICRO.bin"
    for at, kind in sites(open(img, "rb").read(), int(sys.argv[1], 16)):
        print(f"{at:#010x} {kind}")
