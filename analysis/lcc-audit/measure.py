#!/usr/bin/env python3
from __future__ import annotations

import csv, importlib.util, re, subprocess, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LCC = ROOT / "y.lcc"
RCC = LCC / "build" / "rcc.exe"
ASM = ROOT / "1.isa" / "mini_asm.py"
SIM = ROOT / "2.cpu-sim-func" / "minicpu_sim.py"
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "tools"))
from mini_opt import optimize

def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod
    assert spec and spec.loader; spec.loader.exec_module(mod); return mod

mini_asm = module("audit_asm", ASM)
mini_sim = module("audit_sim", SIM)

def run(cmd):
    p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if p.returncode: raise SystemExit(" ".join(map(str,cmd))+"\n"+p.stdout)

def measure(src: Path):
    OUT.mkdir(exist_ok=True)
    base=OUT/src.stem; pp=base.with_suffix(".i"); asm=base.with_suffix(".s"); binary=base.with_suffix(".bin")
    run(["cl","/nologo","/EP","/P",f"/I{LCC/'include/mini/none'}",f"/Fi:{pp}",str(src)])
    run([str(RCC),"-target=mini/none",str(pp),str(asm)])
    run([sys.executable,str(ASM),str(asm),"-o",str(binary)])
    text=asm.read_text(); lines,*_=mini_asm.first_pass(text)
    instructions=[x for x in lines if not mini_asm.is_directive(x.text)]
    op=Counter(re.split(r"[\s,]+",x.text.strip())[0].upper() for x in instructions)
    stack_static=sum(1 for x in instructions if re.match(r"^(LOAD|STORE|LOADB|LOADUB|LOADH|LOADUH|STOREB|STOREH)\b[^\n]*\bR30\b",x.text,re.I))
    frames=[int(x) for x in re.findall(r"^ADDI R30, R30, -(\d+)\s*$",text,re.M)]
    saves=len(re.findall(r"^STORE R(?:1[6-9]|2\d|3[01]), R30,",text,re.M))
    cpu=mini_sim.CPU(); cpu.load_program(binary.read_bytes()); dyn=Counter(); stack_dyn=0
    while not cpu.halted and cpu.instructions_executed < 1_000_000:
        instr=cpu.read_u32(cpu.pc); opcode=(instr>>26)&0x3f; dyn[opcode]+=1
        if opcode in {0x15,0x16,0x18,0x19,0x1a,0x1b,0x1c,0x1d} and ((instr>>16)&31)==30: stack_dyn+=1
        cpu.step()
    original_dynamic=cpu.instructions_executed
    optasm=base.with_suffix(".opt.s"); optbin=base.with_suffix(".opt.bin")
    optasm.write_text(optimize(text,path=str(asm)))
    run([sys.executable,str(ASM),str(optasm),"-o",str(optbin)])
    optlines,*_=mini_asm.first_pass(optasm.read_text())
    optstatic=sum(not mini_asm.is_directive(x.text) for x in optlines)
    cpu2=mini_sim.CPU(); cpu2.load_program(optbin.read_bytes()); cpu2.run(1_000_000)
    assert cpu2.regs[1] == cpu.regs[1]
    return dict(case=src.stem,static=len(instructions),opt_static=optstatic,
                dynamic=original_dynamic,opt_dynamic=cpu2.instructions_executed,
                mem_static=sum(op[k] for k in ('LOAD','STORE','LOADB','LOADUB','LOADH','LOADUH','STOREB','STOREH')),
                stack_static=stack_static,mem_dynamic=sum(dyn[k] for k in (0x15,0x16,0x18,0x19,0x1a,0x1b,0x1c,0x1d)),
                stack_dynamic=stack_dyn,max_frame=max(frames,default=0),callee_saves=saves,calls=op['JAL']+op['JALR'],result=f"0x{cpu.regs[1]:08x}")

rows=[measure(p) for p in sorted((HERE/'probes').glob('*.c'))]
with (HERE/'metrics.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rows[0]); w.writeheader(); w.writerows(rows)
for r in rows: print(r)
