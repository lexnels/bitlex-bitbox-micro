"""Query the analysed Ghidra project (after ghidra/import.py).

  python3 ghidra/gq.py refs 0x24070000 0x24080000     # code that references addresses in [lo, hi)
  python3 ghidra/gq.py callers 0x08069e7c             # call sites of a function
  python3 ghidra/gq.py decomp 0x08069f00 [...]        # decompile functions
  python3 ghidra/gq.py func 0x0804c123                # function containing an address
"""
import os, sys
import pyghidra
GHIDRA = os.environ.get("GHIDRA", "/opt/ghidra_11.4.2_PUBLIC")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pyghidra.start(install_dir=GHIDRA)
from ghidra.base.project import GhidraProject
from ghidra.util.task import TaskMonitor
from ghidra.app.decompiler import DecompInterface
project = GhidraProject.openProject(os.path.join(ROOT, "ghidra"), "micro", True)
program = project.openProgram("/", "micro", True)
space = program.getAddressFactory().getDefaultAddressSpace()
fm, rm, listing = program.getFunctionManager(), program.getReferenceManager(), program.getListing()
A = lambda x: space.getAddress(int(x, 16) if isinstance(x, str) else x)
cmd, args = sys.argv[1], sys.argv[2:]

def fname(a):
    f = fm.getFunctionContaining(a)
    return f"{f.getName()}@{f.getEntryPoint()}" if f else "?"

if cmd == "refs":
    lo, hi = int(args[0], 16), int(args[1], 16)
    it = rm.getReferenceDestinationIterator(A(lo), True)
    while it.hasNext():
        d = it.next()
        if d.getOffset() >= hi:
            break
        for r in rm.getReferencesTo(d):
            print(f"{d} <- {r.getFromAddress()} {r.getReferenceType()} in {fname(r.getFromAddress())}")
elif cmd == "callers":
    for x in args:
        for r in rm.getReferencesTo(A(x)):
            print(f"{x} <- {r.getFromAddress()} {r.getReferenceType()} in {fname(r.getFromAddress())}")
elif cmd == "func":
    for x in args:
        print(x, fname(A(x)))
elif cmd == "decomp":
    d = DecompInterface(); d.openProgram(program)
    for x in args:
        f = fm.getFunctionContaining(A(x))
        r = d.decompileFunction(f, 120, TaskMonitor.DUMMY)
        print(f"// ===== {f.getEntryPoint()} {f.getName()}\n" + r.getDecompiledFunction().getC())
project.close()
