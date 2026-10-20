"""Second pass after import.py: create functions at every vtable slot (C++ virtuals are only reached through tables,
so auto-analysis misses many), re-analyse, and decompile everything again to ghidra/micro_all.c."""
import os, struct
import pyghidra
GHIDRA = os.environ.get("GHIDRA", "/opt/ghidra_11.4.2_PUBLIC")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data = open(os.path.join(ROOT, "firmware", "MICRO.bin"), "rb").read()
BASE, END = 0x08040000, 0x08040000 + len(data)
u = lambda a: struct.unpack_from("<I", data, a - BASE)[0]
code = lambda v: (v & 1) and BASE <= v < 0x080BF000
targets = set()
a = 0x080BF000
while a < END - 8:                     # vtables: two zero words, then >= 4 Thumb code pointers
    if u(a) == 0 and u(a + 4) == 0 and code(u(a + 8)):
        n = 0
        while a + 8 + 4 * n < END and code(u(a + 8 + 4 * n)):
            targets.add(u(a + 8 + 4 * n) & ~1); n += 1
        a += 8 + 4 * max(n, 1); continue
    a += 4
pyghidra.start(install_dir=GHIDRA)
from ghidra.base.project import GhidraProject
from ghidra.util.task import TaskMonitor
from ghidra.program.flatapi import FlatProgramAPI
from ghidra.app.decompiler import DecompInterface
project = GhidraProject.openProject(os.path.join(ROOT, "ghidra"), "micro", False)
program = project.openProgram("/", "micro", False)
api = FlatProgramAPI(program)
space = program.getAddressFactory().getDefaultAddressSpace()
tx = program.startTransaction("vtables")
n = 0
for t in sorted(targets):
    ad = space.getAddress(t)
    if api.getFunctionAt(ad) is None:
        api.disassemble(ad)
        if api.createFunction(ad, None) is not None:
            n += 1
program.endTransaction(tx, True)
print("created", n, "functions from", len(targets), "vtable slots")
project.analyze(program)
project.save(program)
print("functions:", program.getFunctionManager().getFunctionCount())
d = DecompInterface(); d.openProgram(program)
with open(os.path.join(ROOT, "ghidra", "micro_all.c"), "w") as f:
    for fn in program.getFunctionManager().getFunctions(True):
        r = d.decompileFunction(fn, 60, TaskMonitor.DUMMY)
        if r.decompileCompleted():
            f.write(f"// ===== {fn.getEntryPoint()} {fn.getName()}\n{r.getDecompiledFunction().getC()}\n")
project.close()
