"""SIMT control, independent of lane arithmetic and pipeline timing."""
from copy import copy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '11.gpu-sim-func'))
import minigpu_sim as functional
from isa import ISAError, check_access


def needs_reconvergence(w):
    return bool(w.live_mask and w.state == 'READY' and
                (not w.active_mask or (w.region_stack and w.pc == w.region_stack[-1].join_pc)))


def normalize_one(w):
    """One stack operation per clock, never a hidden zero-time while loop."""
    if not w.region_stack:
        raise ISAError(6)
    region = w.region_stack[-1]
    if len(w.path_stack) > region.path_base:
        path = w.path_stack.pop()
        w.pc, w.active_mask = path.pending_pc, path.pending_mask & w.live_mask
    else:
        w.region_stack.pop()
        w.pc, w.active_mask = region.join_pc, region.entry_mask & w.live_mask


def control_result(w, d, results, warps, memory_size):
    """Validate on a private copy. The caller publishes only on successful retire."""
    n = copy(w)
    n.region_stack, n.path_stack = w.region_stack.copy(), w.path_stack.copy()
    if d.op == 0x31:
        check_access(memory_size, d.target, 4)
        if n.region_stack and n.region_stack[-1].ssy_pc == w.pc:
            if n.region_stack[-1].join_pc != d.target: raise ISAError(6)
        else:
            if len(n.region_stack) >= w.sm.system.simt_region_depth: raise ISAError(6)
            n.region_stack.append(functional.SimtRegion(w.pc, d.target, w.active_mask, len(w.path_stack)))
        n.pc = d.seq
    elif d.op == 0x32:
        key = (w.pc, w.barrier_generation)
        if w.active_mask != w.live_mask or any(
                other.workgroup_id == w.workgroup_id and other.state == 'WAIT_BAR'
                and other.barrier_key != key for other in warps):
            raise ISAError(7)
        n.state, n.barrier_key = 'WAIT_BAR', key
    elif d.op in (0x33, 0x3f):
        n.live_mask &= ~w.active_mask
        n.active_mask = 0
        n.pc = d.seq
        if not n.live_mask:
            n.state = 'FINISHED'
            n.region_stack.clear()
            n.path_stack.clear()
    else:
        pcs = {result.next_pc for _, result in results}
        if len(pcs) == 1:
            n.pc = pcs.pop()
        else:
            if not n.region_stack: raise ISAError(6)
            region = n.region_stack[-1]
            taken = sum(1 << lane for lane, result in results if result.next_pc != d.seq)
            if d.target == region.join_pc:
                n.active_mask &= ~taken
                n.pc = d.seq
            elif d.seq == region.join_pc:
                n.active_mask = taken
                n.pc = d.target
            else:
                if len(n.path_stack) >= w.sm.system.simt_path_depth: raise ISAError(6)
                n.path_stack.append(functional.SimtPath(d.target, taken))
                n.active_mask &= ~taken
                n.pc = d.seq
    return n


def publish_control(w, n):
    for field in ('pc', 'active_mask', 'live_mask', 'state', 'barrier_key',
                  'barrier_generation', 'region_stack', 'path_stack'):
        setattr(w, field, getattr(n, field))
