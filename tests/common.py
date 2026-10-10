"""Shared helpers for the Unicorn tests. Run them from the repository root: python3 tests/test_<name>.py"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.chdir(ROOT)
IMAGE = os.environ.get("IMAGE", os.path.join(ROOT, "out", "mod", "MICRO.bin"))
BASE = 0x08040000


def f2u(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def u2f(u):
    return struct.unpack("<f", struct.pack("<I", u & 0xFFFFFFFF))[0]


def bl_target(img, at):
    h1, h2 = struct.unpack_from("<HH", img, at - BASE)
    s = (h1 >> 10) & 1
    i1 = 1 - (((h2 >> 13) & 1) ^ s)
    i2 = 1 - (((h2 >> 11) & 1) ^ s)
    imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    return at + 4 + (imm - (1 << 25) if s else imm)


class Checker:
    def __init__(self):
        self.fails = 0

    def check(self, label, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond and detail != "" else ""))
        self.fails += not cond

    def done(self):
        print("all passed" if not self.fails else f"{self.fails} failed")
        return 1 if self.fails else 0
