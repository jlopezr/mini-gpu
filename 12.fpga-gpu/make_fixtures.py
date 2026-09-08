"""Generate RTL reference vectors with the independent functional simulator."""
from pathlib import Path
import json
import random
import struct
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT.parent / '1.isa'), str(ROOT.parent / '11.gpu-sim-func')]
from miniisa_asm import assemble
from minigpu_sim import System

cases = []
def case(name, source, config=None):
    cases.append((name, source, config))

case('vector', '''
GETTID R1
MOVI R2, 4
MUL R3, R1, R2
ADDI R3, R3, 4096
ADDI R4, R1, 100
STORE R4, R3, 0
LOAD R5, R3, 0
BAR
HALT
''')
case('nested', '''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY join
BLT R1, R2, low
MOVI R3, 30
BRA join
low:
MOVI R2, 2
SSY inner
BLT R1, R2, lowest
MOVI R3, 20
BRA inner
lowest:
MOVI R3, 10
inner:
ADDI R3, R3, 1
join:
ADDI R3, R3, 1
BAR
EXIT
''')
case('loop', '''
GETTID R1
ANDI R1, R1, 7
loop:
SSY done
BEQ R1, R0, done
ADDI R1, R1, -1
ADDI R3, R3, 1
BRA loop
done:
BAR
EXIT
''')
for name, first, second in [('exit_first','EXIT','MOVI R3, 7'),
                            ('exit_second','MOVI R3, 7','EXIT'),
                            ('exit_both','HALT','EXIT')]:
    case(name, f'''
GETTID R1
ANDI R1, R1, 7
MOVI R2, 4
SSY join
BLT R1, R2, low
{first}
BRA join
low:
{second}
join:
ADDI R3, R3, 1
BAR
EXIT
''')
case('groups', 'BAR\nMOVI R3, 7\nBAR\nEXIT\nBAR\nMOVI R4, 9\nBAR\nEXIT',
     {'warps':[dict(id=w, pc=0 if w<4 else 16, active_mask=0x55 if w%2 else 0xff,
                    workgroup_id=w//4) for w in range(8)]})
case('finished_participant', 'BAR\nMOVI R3, 8\nEXIT',
     {'warps':[dict(id=0),dict(id=1,pc=8)]})
case('bank_conflicts', '''
GETTID R1
MOVI R2, 32
MUL R3, R1, R2
ADDI R3, R3, 4096
ADDI R4, R1, 123
STORE R4, R3, 0
LOAD R5, R3, 0
BAR
EXIT
''')
case('barrier_visibility', '''
GETTID R1
MOVI R2, 4
MUL R3, R1, R2
ADDI R3, R3, 4096
STORE R1, R3, 0
BAR
XORI R4, R1, 63
MUL R4, R4, R2
ADDI R4, R4, 4096
LOAD R5, R4, 0
BAR
HALT
''')
rng=random.Random(1288)
lines=['GETTID R1', 'MOVI R0, -17', 'MOVI R2, -3', 'MOVHI R3, 0x8000',
       'MOVI R4, 1', 'DIV R5, R3, R2', 'MOVI R2, -1', 'DIV R6, R3, R2',
       'MULFX R7, R0, R3', 'MOVHI R8, 0xffff', 'ORI R8, R8, 0x8001',
       'MULFX R9, R8, R8', 'NOP']
for op in ['ADD','SUB','MUL','MULFX','DIV','AND','OR','XOR','SHL','SHR','SAR']*3:
    # Divisor R4 is preserved and nonzero. Exercise R0 as a normal writable register.
    lines.append(f'{op} R{rng.randrange(10,32)}, R{rng.randrange(10)}, R{4 if op=="DIV" else rng.randrange(10)}')
lines += ['ANDI R10, R0, 0xff', 'XORI R11, R10, 0xffff', 'HALT']
case('arithmetic', '\n'.join(lines))
for op in ['BEQ','BNE','BLT','BGE','BLTU','BGEU']:
    case('branch_'+op.lower(), f'''
GETTID R1
ANDI R1, R1, 7
ADDI R1, R1, -4
SSY join
{op} R1, R0, taken
MOVI R3, 3
BRA join
taken:
MOVI R3, 7
join:
HALT
''')

case('unified_code', '''
LOAD R2, R0, 0
MOVHI R4, 0x40e0
ORI R4, R4, 123
STORE R4, R0, 64
BAR
BRA modified
NOP
NOP
NOP
NOP
NOP
NOP
NOP
NOP
NOP
NOP
modified:
HALT
HALT
''')
case('last_word', '''
MOVHI R1, 1
ORI R1, R1, 0xfffc
MOVI R2, 77
STORE R2, R1, 0
BAR
LOAD R3, R1, 0
HALT
''')
case('early_halt_unwind', '''
SSY outer
SSY inner
HALT
NOP
inner:
NOP
NOP
outer:
MOVI R3, 99
HALT
''')

out=ROOT/'fixtures'
out.mkdir(exist_ok=True)
metadata=[]
for index,(name,source,config) in enumerate(cases):
    words=assemble(source)
    binary=struct.pack('<'+'I'*len(words),*words)
    gpu=System(128*1024,8,8)
    gpu.load_program(binary)
    if config is not None: gpu.configure_warps(config)
    initial=[(w.pc,w.active_mask,w.workgroup_id) for w in gpu.streaming_multiprocessor.warps]
    gpu.run(10000)
    assert not gpu.error, (name,gpu.fault)
    prefix=out/f'{index:02d}'
    prefix.with_suffix('.asm').write_text(source.strip()+'\n')
    prefix.with_suffix('.bin').write_bytes(binary)
    def hexfile(suffix, values):
        prefix.with_suffix(suffix).write_text(''.join(f'{v:08x}\n' for v in values))
    hexfile('.program.hex',words+[0]*(256-len(words)))
    hexfile('.regs.hex',[r for w in gpu.streaming_multiprocessor.warps for lane in w.processors for r in lane.regs])
    hexfile('.memory.hex',struct.unpack('<512I',gpu.memory[4096:6144]))
    hexfile('.config.hex',[v for row in initial for v in row])
    hexfile('.state.hex',[v for w in gpu.streaming_multiprocessor.warps for v in (w.pc,w.active_mask,w.live_mask)])
    metadata.append(dict(id=index,name=name,instructions=gpu.instructions_executed))
(out/'manifest.json').write_text(json.dumps(metadata,indent=2)+'\n')
(out/'count.vh').write_text(f'localparam CASES={len(cases)};\n')
print(f'Generated {len(cases)} differential cases')
