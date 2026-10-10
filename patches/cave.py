"""The compiled code cave (./build.sh), appended after the stock image, plus the mod's version string."""
import os

from thumb import ROOT

STOCK_END = 0x080E3E90
VERSION = b"2.3.4-L1"  # shown where stock shows 2.3.4; bump the number with each release

PATCHES = [
    (0x080C5770, b"2.3.4\0\0\0\0", VERSION + b"\0"),
    (STOCK_END, b"", open(os.path.join(ROOT, "out", "cave.bin"), "rb").read()),
]
