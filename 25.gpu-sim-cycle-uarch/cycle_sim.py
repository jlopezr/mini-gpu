#!/usr/bin/env python3
"""Executable microarchitectural contract for the next MiniGPU SM."""
from __future__ import annotations

from copy import copy
from dataclasses import replace, asdict
from isa import (ISAError, MEMORY, SPECIAL, NAMES, Result, MASK,
                 decode, execute, check_access, signed)
from resources import Config, Packet, Counters, execution_cycles, transaction_count
from simt import (functional, needs_reconvergence, normalize_one,
                  control_result, publish_control)

STAGES = tuple('SFIDXW')


class CycleLimitExceeded(RuntimeError):
    pass


class Pipeline:
    def __init__(self, system, config=None, trace=None):
        self.system = system
        self.config = config or Config()
        self.warps = system.streaming_multiprocessor.warps
        self.stages = dict.fromkeys(STAGES)
        self.lsu = ()
        self.in_flight = set()
        self.cursor = 0
        self.counters = Counters()
        self.trace = trace
        self.cache = {}
        self.last_retired = {'W': -1, 'LSU': -1}

    def event(self, event, packet=None, **extra):
        if self.trace is None: return
        record = {'cycle': self.counters.cycles, 'event': event, **extra}
        if packet is not None:
            record.update(serial=packet.serial, warp=packet.warp, pc=packet.pc,
                          instruction=packet.word, mask=packet.mask)
        self.trace(record)

    def fault(self, exc, packet, lane=None):
        return functional.Fault(exc.code, packet.pc, packet.warp, lane, exc.address)

    def prepare(self, packet):
        if packet.fault: return packet
        try:
            d = decode(packet.word, packet.pc)
            if d.op == 0x3e:
                raise ISAError(3)
            w = self.warps[packet.warp]
            operands = tuple((p.core_id, tuple(p.regs)) for p in w.processors
                             if packet.mask & (1 << p.core_id))
            latency = execution_cycles(d, operands, self.config)
            return replace(packet, decoded=d, operands=operands,
                           latency=latency, remaining=latency)
        except ISAError as exc:
            return replace(packet, fault=self.fault(exc, packet))

    def evaluate(self, packet):
        if packet.fault: return packet
        results = []
        for lane, regs in packet.operands:
            try:
                result = execute(packet.decoded, regs,
                                 packet.warp * len(self.warps[packet.warp].processors) + lane)
                if result.access:
                    address, size, value, _ = result.access
                    device = self.system.device_for(address)
                    if device is None:
                        check_access(len(self.system.memory), address, size)
                    elif size != 4 or address & 3:
                        raise ISAError(2, address)
                    else:
                        try:
                            device.validate(address - device.BASE, writing=value is not None)
                        except RuntimeError as exc:
                            raise ISAError(2, address) from exc
                results.append((lane, result))
            except ISAError as exc:
                return replace(packet, fault=self.fault(exc, packet, lane))
        return replace(packet, results=tuple(results))

    def fetch(self, packet):
        """F samples a hit once; an outstanding miss retains its response."""
        cfg = self.config
        if packet.fetch_started:
            if packet.remaining > 1:
                return replace(packet, remaining=packet.remaining - 1), False
            if packet.word is None and not packet.fault:
                line = packet.pc // 16
                data = bytes(self.system.memory[line * 16:line * 16 + 16])
                self.cache[line % cfg.imem_lines] = (line, data)
                offset = packet.pc % 16
                packet = replace(packet, word=int.from_bytes(data[offset:offset + 4], 'little'))
            return replace(packet, remaining=0), True
        try:
            check_access(len(self.system.memory), packet.pc, 4)
        except ISAError as exc:
            return replace(packet, fetch_started=True, fault=self.fault(exc, packet)), True
        line = packet.pc // 16
        cached = self.cache.get(line % cfg.imem_lines) if cfg.imem_lines else None
        if not cfg.imem_lines or cached and cached[0] == line:
            self.counters.imem_hits += 1
            data = cached[1] if cached else self.system.memory[line * 16:line * 16 + 16]
            offset = packet.pc % 16
            self.event('fetch_hit', packet)
            return replace(packet, fetch_started=True,
                           word=int.from_bytes(data[offset:offset + 4], 'little')), True
        self.counters.imem_misses += 1
        self.event('fetch_miss', packet)
        return replace(packet, fetch_started=True, remaining=cfg.imem_miss_cycles), False

    def maintenance(self):
        """Compute independent control updates from pre-edge state."""
        changes = {}
        for group in {w.workgroup_id for w in self.warps}:
            participants = [w for w in self.warps if w.workgroup_id == group and w.live_mask]
            if participants and all(w.state == 'WAIT_BAR' for w in participants):
                for w in participants:
                    n = copy(w)
                    n.state, n.pc = 'READY', (w.pc + 4) & MASK
                    n.barrier_generation += 1
                    changes[w.warp_id] = n
        for w in self.warps:
            if w.warp_id not in self.in_flight and needs_reconvergence(w):
                n = copy(w)
                n.region_stack, n.path_stack = w.region_stack.copy(), w.path_stack.copy()
                normalize_one(n)
                changes[w.warp_id] = n
        return changes

    def complete(self, packet, source):
        """The single architectural commit point. Failed warps have no partial effects."""
        if packet.fault:
            self.system.stop_with_error(packet.fault)
            self.event('fault', packet, fault=asdict(packet.fault), source=source)
            return
        w = self.warps[packet.warp]
        results, stores = [], []
        # Requests were validated in D and load data was captured when the
        # response arrived, even if RF writeback has since been stalled.
        for lane, result in packet.results:
            if result.access:
                address, size, value, sign = result.access
                if value is None:
                    # Los registros con efectos (UART DATA) se leen solo al
                    # commit, nunca al llegar una respuesta especulativa.
                    device = self.system.device_for(address)
                    if device is None:
                        raise AssertionError('load committed before capturing response')
                    value = device.read(address - device.BASE) & MASK
                    result = Result(result.next_pc,
                                    (packet.decoded.rd, value) if packet.decoded.rd else None)
                else:
                    stores.append((address, (value & ((1 << (size * 8)) - 1)).to_bytes(size, 'little')))
            results.append((lane, result))
        try:
            n = control_result(w, packet.decoded, results, self.warps, len(self.system.memory))
        except ISAError as exc:
            fault = self.fault(exc, packet)
            self.system.stop_with_error(fault)
            self.event('fault', packet, fault=asdict(fault), source=source)
            return
        assert packet.serial > self.last_retired[source], 'out-of-order resource retirement'
        self.last_retired[source] = packet.serial
        publish_control(w, n)
        writes = []
        for lane, result in results:
            if result.write:
                register, value = result.write
                w.processors[lane].regs[register] = value
                writes.append([lane, register, value])
        for address, data in stores:
            device = self.system.device_for(address)
            if device is not None:
                device.write(address - device.BASE, int.from_bytes(data, 'little'))
            else:
                self.system.memory[address:address + len(data)] = data
        w.instructions_executed += 1
        self.in_flight.remove(packet.warp)
        c = self.counters
        c.retired += 1
        c.lane_ops += packet.mask.bit_count()
        c.instructions[NAMES[packet.decoded.op]] += 1
        self.event('retire', packet, source=source, next_pc=w.pc,
                   active_mask=w.active_mask, live_mask=w.live_mask,
                   writes=writes, stores=[[a, b.hex()] for a, b in stores])
        self.system.tick_devices()

    def check_invariants(self):
        # Python -O disables assertions; skip their supporting scans as well.
        if not __debug__:
            return
        packets = [p for p in self.stages.values() if p is not None] + list(self.lsu)
        owners = [p.warp for p in packets]
        assert len(owners) == len(set(owners)), 'more than one instruction per warp'
        assert set(owners) == self.in_flight, 'lost or duplicated instruction ownership'
        assert len({p.serial for p in packets}) == len(packets)
        assert self.counters.issued == self.counters.retired + self.counters.cancelled + len(packets)
        assert len(self.lsu) <= self.config.lsu_slots
        assert all(a.serial < b.serial for a, b in zip(self.lsu, self.lsu[1:]))
        for w in self.warps:
            assert not w.active_mask & ~w.live_mask
            assert all(p.regs[0] == 0 for p in w.processors)
            assert len(w.region_stack) <= self.system.simt_region_depth
            assert len(w.path_stack) <= self.system.simt_path_depth
            assert all(r.path_base <= len(w.path_stack) for r in w.region_stack)
        for p in packets:
            assert p.pc == self.warps[p.warp].pc, 'PC changed before completion'

    def cycle(self):
        if self.system.halted: return
        self.check_invariants()
        c, old = self.counters, self.stages
        # No architectural mutation before all stage, scheduler and maintenance
        # decisions have been evaluated against this pre-edge state.
        changes = self.maintenance()
        eligible = [w.warp_id for w in self.warps if w.live_mask and w.state == 'READY'
                    and w.warp_id not in self.in_flight and not needs_reconvergence(w)]
        if self.trace:
            def brief(p):
                return None if p is None else {key: getattr(p, key) for key in
                    ('serial', 'warp', 'pc', 'word', 'mask', 'remaining')}
            self.event('snapshot', stages={s: brief(old[s]) for s in STAGES},
                       lsu=[brief(p) for p in self.lsu], in_flight=sorted(self.in_flight),
                       wait_mem=[p.warp for p in self.lsu],
                       wait_bar=[w.warp_id for w in self.warps if w.state == 'WAIT_BAR'],
                       eligible=eligible)
        for s, packet in old.items():
            if packet is not None: c.occupancy[s] += 1
        c.lsu_occupancy += len(self.lsu)
        c.wait_mem_cycles += bool(self.lsu)
        if old['X']:
            opcode = NAMES[old['X'].decoded.op] if old['X'].decoded else 'FAULT'
            c.x_cycles_by_opcode[opcode] += 1
            if old['X'].latency > 1:
                c.multicycle[opcode] += 1

        nxt = old.copy()
        queue = list(self.lsu)
        response = None
        if queue and queue[0].remaining <= 1:
            response = queue[0]
            if not response.response_ready:
                results = []
                for lane, result in response.results:
                    address, size, value, sign = result.access
                    if value is None and self.system.device_for(address) is None:
                        value = int.from_bytes(self.system.memory[address:address + size], 'little')
                        value = (signed(value, size * 8) if sign else value) & MASK
                        result = Result(result.next_pc,
                                        (response.decoded.rd, value) if response.decoded.rd else None)
                    results.append((lane, result))
                response = replace(response, results=tuple(results), response_ready=True)
                queue[0] = response
                self.event('lsu_response', response,
                           results=[{'lane': lane, **asdict(result)} for lane, result in results])
        completions = self.completion_choice(response)
        sources = {source for _, source in completions}
        if 'W' in sources: nxt['W'] = None
        if 'LSU' in sources: queue.pop(0)
        if self.lsu:
            head = self.lsu[0]
            if not head.response_ready:
                c.lsu_busy += 1
                if not head.fault and head.remaining % self.config.memory_cycles == 0:
                    c.lsu_transactions += 1
                    self.event('memory_transaction', head)
            if head.remaining > 1:
                queue[0] = replace(head, remaining=head.remaining - 1)
            elif 'LSU' not in sources:
                c.stall_writeback += 1

        packet = old['X']
        if packet:
            if packet.remaining > 1:
                nxt['X'] = replace(packet, remaining=packet.remaining - 1)
            elif nxt['W'] is None:
                nxt['W'], nxt['X'] = self.evaluate(packet), None
                self.event('advance', packet, source='X', destination='W')

        packet = old['D']
        if packet:
            if packet.decoded is None and packet.fault is None:
                packet = self.prepare(packet)
                nxt['D'] = packet
            op = packet.decoded.op if packet.decoded else None
            if op in MEMORY:
                # Capacity is deliberately sampled before the edge: no LSU
                # response-to-request combinational bypass.
                if len(self.lsu) < self.config.lsu_slots:
                    request = self.evaluate(packet)
                    transactions = 0 if request.fault else transaction_count(request.results)
                    request = replace(request, remaining=max(1, transactions * self.config.memory_cycles))
                    queue.append(request)
                    nxt['D'] = None
                    self.event('lsu_issue', request, transactions=transactions)
                else:
                    c.stall_lsu_full += 1
                    self.event('stall', packet, reason='lsu_full')
            elif op in SPECIAL:
                # Specials bypass the lane datapath but never an older X token.
                if old['X'] is None and nxt['W'] is None:
                    nxt['W'], nxt['D'] = packet, None
                    self.event('advance', packet, source='D', destination='W')
                else:
                    c.stall_x += 1
            elif nxt['X'] is None:
                nxt['X'], nxt['D'] = packet, None
                self.event('advance', packet, source='D', destination='X')
            else:
                c.stall_x += 1
                self.event('stall', packet, reason='x_busy')

        if old['I'] and nxt['D'] is None:
            nxt['D'], nxt['I'] = old['I'], None
            self.event('advance', old['I'], source='I', destination='D')
        if old['F']:
            fetched, ready = self.fetch(old['F'])
            nxt['F'] = fetched
            if ready and nxt['I'] is None:
                nxt['I'], nxt['F'] = fetched, None
                self.event('advance', fetched, source='F', destination='I')
            elif not ready:
                c.stall_fetch += 1
        if old['S'] and nxt['F'] is None:
            nxt['F'], nxt['S'] = old['S'], None
            self.event('advance', old['S'], source='S', destination='F')
        selected = None
        if nxt['S'] is None:
            for offset in range(len(self.warps)):
                wid = (self.cursor + offset) % len(self.warps)
                if wid in eligible:
                    w = self.warps[wid]
                    selected = Packet(c.issued, wid, w.pc, w.active_mask)
                    nxt['S'] = selected
                    break
            if selected is None: c.stall_no_warp += 1

        # Publish this edge. No later stage reads any of these new values.
        self.stages, self.lsu = nxt, tuple(queue)
        if selected:
            self.in_flight.add(selected.warp)
            self.cursor = (selected.warp + 1) % len(self.warps)
            c.issued += 1
            self.event('issue', selected)
        retired_before = c.retired
        for completion, source in completions:
            if not self.system.error and not self.system.peripheral_halted:
                self.complete(completion, source)
        if c.retired - retired_before == 2: c.simultaneous_completions += 1
        if not self.system.error and not self.system.peripheral_halted:
            for wid, state in changes.items():
                old_state = self.warps[wid].state
                publish_control(self.warps[wid], state)
                if old_state == 'WAIT_BAR':
                    c.barrier_releases += 1
                    self.event('barrier_release', warp=wid, next_pc=state.pc)
                else:
                    c.reconvergence += 1
                    self.event('reconverge', warp=wid, next_pc=state.pc, active_mask=state.active_mask)
        else:
            # Global first-observed fault. Cancel every uncommitted token,
            # including the faulting one, with no speculative side effects.
            c.cancelled = c.issued - c.retired
            self.stages = dict.fromkeys(STAGES)
            self.lsu = ()
            self.in_flight.clear()
        c.cycles += 1
        self.check_invariants()

    def completion_choice(self, memory):
        """Fixed W priority on the single vector RF write port.

        Independent control-only/store completions can share the edge. A held
        LSU response continues owning its slot and warp until RF commit.
        """
        w = self.stages['W']
        completions = [(w, 'W')] if w else []
        w_writes = bool(w and not w.fault and any(r.write for _, r in w.results))
        mem_writes = bool(memory and not memory.fault and any(
            r.write or (r.access and r.access[2] is None and memory.decoded.rd)
            for _, r in memory.results))
        if w_writes and mem_writes:
            self.counters.writeback_collisions += 1
            if not self.lsu[0].response_ready:
                self.counters.response_arrival_collisions += 1
            self.event('stall', memory, reason='rf_port_collision', winner=w.serial)
        elif memory:
            completions.append((memory, 'LSU'))
        return completions

    def run(self, max_cycles=10_000_000, max_instructions=None):
        if max_cycles < 0 or max_instructions is not None and max_instructions < 0:
            raise ValueError('limits must be nonnegative')
        while not self.system.halted:
            if self.counters.cycles >= max_cycles:
                raise CycleLimitExceeded(f'cycle limit {max_cycles}; stages={self.stages}; LSU={self.lsu}')
            if max_instructions is not None and self.counters.retired >= max_instructions:
                raise functional.InstructionLimitExceeded(f'instruction limit {max_instructions}')
            self.cycle()
        return self.counters.report()
