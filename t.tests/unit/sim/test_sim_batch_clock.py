"""`advance(n)` equivale a `n` llamadas a `tick()` (reloj por lotes de sim_devices).

El motor Codon avanza los periféricos Python por lotes, hasta el siguiente tick
que hace algo (`ticks_until_event`). Aquí se comparan dos copias de cada
dispositivo: una avanza tick a tick y la otra a saltos aleatorios que no pasan del
límite; tras cada salto el estado y las llamadas al anfitrión deben coincidir.
"""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.input_script import Action  # noqa: E402
from tools.sim_devices import InputDevice, SerialDevice, VideoDevice  # noqa: E402


class Recorder:
    """Terminal o anfitrión de pega: anota en qué tick le llaman."""

    def __init__(self, clock):
        self.clock = clock
        self.calls = []

    def poll(self, device):
        self.calls.append(("poll", self.clock()))

    def write(self, data):
        self.calls.append(("write", self.clock(), bytes(data)))


def state(device):
    return {key: (bytes(value) if isinstance(value, bytearray) else value)
            for key, value in vars(device).items()
            if key not in ("tty", "host", "script")}


class BatchClockTest(unittest.TestCase):
    def compare(self, make, steps=3000, seed=0):
        rng = random.Random(seed)
        one, batch = make(), make()
        done = 0
        while done < steps:
            limit = batch.ticks_until_event()
            self.assertGreaterEqual(limit, 1)
            n = rng.randint(1, min(limit, 97))
            for _ in range(n):
                one.tick()
            batch.advance(n)
            done += n
            self.assertEqual(state(one), state(batch), f"tras {done} ticks")
            for a, b in ((getattr(one, "tty", None), getattr(batch, "tty", None)),
                         (getattr(one, "host", None), getattr(batch, "host", None))):
                if a is not None:
                    self.assertEqual(a.calls, b.calls, f"tras {done} ticks")
        return one

    def test_video_frames_swaps_and_halt_at(self):
        def make():
            video = VideoDevice(frame_instructions=37)
            video.write(video.HALT_AT, 3)
            video.write(video.SWAP, 1)
            return video
        video = self.compare(make)
        self.assertGreater(video.frame_count, 50)
        # Sin nada pendiente, las fronteras de frame no son eventos...
        self.assertGreater(video.ticks_until_event(), 1 << 40)
        # ...y con un intercambio pendiente, la siguiente sí.
        video.write(video.SWAP, 1)
        self.assertEqual(video.ticks_until_event(), 37 - video._since_frame)

    def test_video_idle_frames_in_one_jump(self):
        one, batch = VideoDevice(frame_instructions=37), VideoDevice(frame_instructions=37)
        for _ in range(10_000):
            one.tick()
        batch.advance(10_000)
        self.assertEqual(state(one), state(batch))

    def test_serial_host_and_tty(self):
        for with_tty in (False, True):
            def make():
                serial = SerialDevice(stdin=b"hola")
                serial.tx.extend(b"x" * 600)
                if with_tty:
                    serial.attach_tty(Recorder(lambda: serial._tty_ticks), every=45)
                else:
                    serial.attach_host()
                return serial
            with self.subTest(tty=with_tty):
                serial = self.compare(make)
                self.assertEqual(len(serial.host_output), 600)

    def test_serial_without_host_never_needs_a_tick(self):
        self.assertGreater(SerialDevice().ticks_until_event(), 1 << 40)

    def test_input_script_and_host(self):
        def make():
            device = InputDevice()
            presses = []
            device.attach_script([Action(at, 0, lambda d, at=at: presses.append(at), "")
                                  for at in (0, 5, 5, 6, 200, 1999)])
            device.attach_host(Recorder(lambda: device.ticks), every=113)
            device.presses = presses
            return device
        device = self.compare(make)
        self.assertEqual(device.presses, [0, 5, 5, 6, 200, 1999])


if __name__ == "__main__":
    unittest.main()
