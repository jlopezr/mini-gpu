"""Lado Python del motor Codon de `sim-sys --backend codon`.

El motor (`engine.codon`) ejecuta los núcleos compilados. Esto es lo que no se
compila: la línea de órdenes, la carga del programa, los periféricos con su
ventana y terminal, y el informe final. Para todo ello hay aquí un
`CpuGpuSystem` de Python, construido con `cpu_gpu_sim.build_system` como en el
backend Python, que hace de espejo:

- su RAM es la del motor nativo (una vista sin copia), así que la ventana y los
  volcados ven lo que escriben los núcleos compilados;
- sus periféricos son los mismos objetos que usan los proxies nativos
  (`tools/sim_devices.codon`);
- al acabar, el motor le copia su estado con `set` y se cierra con el mismo
  `finish_run` que el backend Python.
"""
import ctypes
import json
import os
from pathlib import Path
import sys

# CPython embebido: sys.executable es el binario del motor, y gui_python() lo
# usaría para abrir la ventana. El lanzador pasa el Python de verdad.
sys.executable = os.environ.get("MINIGPU_CODON_GUI_PYTHON") or sys.executable

ROOT = Path(__file__).resolve().parents[2]
for _folder in (ROOT / "32.cpu-gpu-func-sim", ROOT):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))
import cpu_gpu_sim as sim  # noqa: E402
from tools import sim_peripherals  # noqa: E402


def create(argv):
    """El anfitrión, o None si la línea de órdenes o el programa no valen (ya avisado)."""
    try:
        return Host(list(argv))
    except (OSError, ValueError) as exc:
        print(f"Simulador: {exc}", file=sys.stderr)
    except SystemExit:
        pass                    # argparse ya ha escrito el error
    return None


def valid(host):
    return host is not None


class Host:
    def __init__(self, argv):
        self.args = sim.parse_arguments(argv)
        self.system = sim.build_system(self.args)
        self.exit_status = 0
        self._buffer = None

    # -- configuración que lee el motor -------------------------------------

    def memory_size(self):
        return len(self.system.memory)

    def num_warps(self):
        return self.system.gpu.num_warps

    def warp_size(self):
        return self.system.gpu.num_lanes

    def cpu_steps(self):
        return self.system.cpu_steps

    def gpu_steps(self):
        return self.system.gpu_steps

    def start_pc(self):
        return self.system.cpu.pc

    def limits(self):
        """`--run-limit`, `--cpu-run-limit` y `--gpu-run-limit` como (hay límite, valor)."""
        a = self.args
        return [(v is not None, v or 0) for v in (a.run_limit, a.cpu_run_limit, a.gpu_run_limit)]

    def has_device(self, name):
        return getattr(self.system, name) is not None

    def device(self, name):
        return getattr(self.system, name)

    # -- durante la ejecución ----------------------------------------------

    def bind_memory(self, address, size):
        """La RAM del motor pasa a ser la del espejo, con la imagen ya cargada."""
        self._buffer = (ctypes.c_ubyte * size).from_address(address)
        view = memoryview(self._buffer).cast("B")
        s = self.system
        view[:] = s.memory
        s.memory = s.cpu.memory = s.gpu.system.memory = view
        sm = s.gpu.system.streaming_multiprocessor
        sm.memory = view
        for warp in sm.warps:
            warp.memory = view
            for lane in warp.processors:
                lane.memory = view
        sim_peripherals.start_display(s)

    def stop_requested(self):
        """Si la ventana, F12 o Ctrl+C han pedido parar (`stop_machine` sobre el espejo)."""
        s = self.system
        requested = s.cpu.halted or s.gpu.halted_by_control
        s.cpu.halted = False
        s.gpu.system.peripheral_halted = False
        return requested

    # -- al acabar -----------------------------------------------------------

    def set(self, target, index, name, value):
        """Copia un campo del motor nativo en el objeto equivalente del espejo."""
        s = self.system
        obj = {"system": s, "cpu": s.cpu, "gpu": s.gpu, "gpu.system": s.gpu.system,
               "sm": s.gpu.system.streaming_multiprocessor}.get(target)
        if target == "warp":
            obj = s.gpu.warps[index]
        elif target == "lane":
            warp, lane = divmod(index, sim.MAX_LANES)
            obj = s.gpu.warps[warp].processors[lane]
        gpu_sim = sim.gpu_sim
        if name == "region_stack":
            value = [gpu_sim.SimtRegion(*r) for r in value]
        elif name == "path_stack":
            value = [gpu_sim.SimtPath(*p) for p in value]
        elif name == "fault" and value is not None:
            value = gpu_sim.Fault(*value)
        elif name == "barrier_key" and value is not None:
            value = tuple(value)
        elif name == "descriptors":
            value = [dict(d) for d in value]
        setattr(obj, name, value)

    def finish(self, status, limited):
        """`status` de `run` ("halt"/"stalled"), o "" con el mensaje del límite."""
        stalled = sim.STALLED if status == "stalled" else None
        target = os.environ.get("MINIGPU_CODON_STATE")
        if target:
            from tools.codon_backend import snapshot
            Path(target).write_text(json.dumps(snapshot(self.system), sort_keys=True))
        try:
            sim_peripherals.write_outputs(self.args, self.system)
            self.exit_status = sim.finish_run(self.args, self.system,
                                              limited=limited or None, stalled=stalled)
        except (OSError, ValueError) as exc:
            print(f"Simulador: {exc}", file=sys.stderr)
            self.exit_status = 2

    def fail(self, message):
        print(f"Simulador: {message}", file=sys.stderr)
        sim_peripherals.finish_display(self.system)
        self.exit_status = 2

    def result(self):
        return self.exit_status
