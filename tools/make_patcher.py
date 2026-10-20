"""Write a standalone patcher for a release: one Python file that turns the stock firmware into the modded one.

  python3 patch.py all && python3 tools/make_patcher.py v0.1     # -> out/release/bitlex-micro-v0.1-patcher.py

It carries only the bytes the mod changes (our code, appended after the stock image, and the small hooks), never
1010music's firmware: every run of bytes that differs from the stock image, with no stock bytes in between, plus the
appended code cave. The stock file is checked by its SHA-256 before patching and the result by its SHA-256 after.
"""
import base64, hashlib, os, struct, sys, zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
version = sys.argv[1]
stock = open(os.path.join(ROOT, "firmware", "MICRO-2.3.4.bin"), "rb").read()
mod = open(os.path.join(ROOT, "out", "mod", "MICRO.bin"), "rb").read()
assert len(mod) >= len(stock)

runs, i = [], 0
while i < len(stock):
    if mod[i] == stock[i]:
        i += 1
        continue
    j = i
    while j < len(stock) and mod[j] != stock[j]:
        j += 1
    runs.append((i, mod[i:j]))
    i = j
if len(mod) > len(stock):
    runs.append((len(stock), mod[len(stock):]))
blob = b"".join(struct.pack("<II", o, len(b)) + b for o, b in runs)
payload = base64.b64encode(zlib.compress(blob, 9)).decode()
lines = "\n".join(payload[k:k + 100] for k in range(0, len(payload), 100))
name = f"bitlex-micro-{version}-patcher.py"

script = f'''#!/usr/bin/env python3
"""BitLex - 1010 bitbox micro modded firmware {version}: https://github.com/lexnels/bitlex-bitbox-micro

Turns the stock 1010music firmware file into the modded one. Needs Python 3, nothing else.

  python3 {name} <stock firmware file> [output file]

The output defaults to modded/MICRO.bin next to this script (your stock file keeps its name). This file holds only the
mod's changes, not 1010music's firmware: you need your own copy of the stock file (bitbox micro 2.3.4,
SHA-256 {hashlib.sha256(stock).hexdigest()}).
"""
import base64, hashlib, os, struct, sys, zlib

STOCK_SHA256 = "{hashlib.sha256(stock).hexdigest()}"
MOD_SHA256 = "{hashlib.sha256(mod).hexdigest()}"
PATCH = """
{lines}
"""

if len(sys.argv) < 2:
    sys.exit(__doc__)
data = bytearray(open(sys.argv[1], "rb").read())
if hashlib.sha256(data).hexdigest() != STOCK_SHA256:
    sys.exit("That isn't the stock firmware this mod was built for (SHA-256 mismatch). Nothing written.")
blob, at = zlib.decompress(base64.b64decode("".join(PATCH.split()))), 0
while at < len(blob):
    ofs, n = struct.unpack_from("<II", blob, at)
    data[ofs:ofs + n] = blob[at + 8:at + 8 + n]   # the last run starts at the end of the stock file and extends it
    at += 8 + n
assert hashlib.sha256(data).hexdigest() == MOD_SHA256, "patched result doesn't match; nothing written"
# the stock file is also called MICRO.bin, so by default write into a "modded" folder next to this script
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "modded", "MICRO.bin")
if os.path.exists(out) and os.path.samefile(out, sys.argv[1]):
    sys.exit("The output would overwrite your stock file. Give a different output path. Nothing written.")
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
open(out, "wb").write(data)
print("wrote", out, "- copy it to the root of the microSD card and install it like a 1010music firmware update.")
'''
os.makedirs(os.path.join(ROOT, "out", "release"), exist_ok=True)
path = os.path.join(ROOT, "out", "release", name)
open(path, "w").write(script)
print(f"{path}: {len(runs)} changed runs, {sum(len(b) for _, b in runs)} bytes")
