"""Apply byte patches to the stock bitbox micro firmware and write an SD-card-ready MICRO.bin.

  python3 patch.py <patchset> [...]     e.g. python3 patch.py version

Each patchset in patches/ defines PATCHES = [(addr, old_bytes, new_bytes), ...]. Every patch checks the stock bytes
first, so a patch built for another firmware version fails instead of writing garbage. A patch at the end of the image
with empty old bytes appends (the code cave).
"""
import hashlib, importlib, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
STOCK = os.path.join(ROOT, "firmware", "MICRO-2.3.4.bin")
STOCK_SHA256 = "54ecc3e5c09b9aed7ad8e2d9d1c9f8ee63e06a8351c857304c3ff21fcb9c4365"
BASE = 0x08040000
ALL = ["mod", "filter", "looper", "grain", "cave"]           # the full mod, in order; `python3 patch.py all` -> out/mod/MICRO.bin


def build(names, stock=STOCK, verbose=True):
    data = bytearray(open(stock, "rb").read())
    assert hashlib.sha256(data).hexdigest() == STOCK_SHA256, "stock firmware hash mismatch (needs bitbox micro 2.3.4)"
    sys.path.insert(0, os.path.join(ROOT, "patches"))
    for name in names:
        for addr, old, new in importlib.import_module(name).PATCHES:
            o = addr - BASE
            if o == len(data):
                assert old == b"", f"{name}: append at {addr:#x} must have empty old bytes"
                data += new
                if verbose:
                    print(f"{name}: {addr:#010x} {len(new):6d} bytes appended")
                continue
            assert len(old) == len(new), f"{name}: size change at {addr:#x}"
            assert o + len(new) <= len(data), f"{name}: past end of image at {addr:#x}"
            assert data[o:o + len(old)] == old, f"{name}: stock bytes differ at {addr:#x}"
            data[o:o + len(new)] = new
            if verbose:
                print(f"{name}: {addr:#010x} {len(new):6d} bytes" + (f"  {old.hex()} -> {new.hex()}" if len(new) <= 8 else ""))
    return data


if __name__ == "__main__":
    names = sys.argv[1:]
    full = names == ["all"]
    if full:
        names = ALL
    data = build(names)
    out_dir = os.path.join(ROOT, "out", "mod" if full else "+".join(names))
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "MICRO.bin")
    open(out, "wb").write(data)
    print(f"wrote {out} ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()[:16]})")
