"""Leitura do controle direto de /dev/input, sem exclusividade.

Segue as regras de entrada do contrato:
  - nunca usa EVIOCGRAB (o a11yd precisa ver os mesmos botões);
  - descarta Fn e tudo que for apertado enquanto Fn está pressionado;
  - descarta volume, Power e qualquer código fora do contrato.
"""
import glob
import os
import struct

from .buttons import AXIS_CODES, BUTTON_CODES, DOWN, FN_CODE, UP

EV_KEY = 0x01
EV_ABS = 0x03

# struct input_event: timeval (2 x long), type, code, value.
EVENT = struct.Struct("llHHi")
# struct input_absinfo: value, minimum, maximum, fuzz, flat, resolution.
ABSINFO = struct.Struct("6i")


def _eviocgabs(axis):
    # _IOR('E', 0x40 + axis, struct input_absinfo)
    return (2 << 30) | (ABSINFO.size << 16) | (ord("E") << 8) | (0x40 + axis)


class InputState:
    """Transforma eventos crus do kernel em eventos do contrato.

    Separado da leitura dos arquivos para poder ser testado no PC.
    """

    def __init__(self, deadzone=0.2):
        self.deadzone = deadzone
        self.fn_held = False
        self.suppressed = set()   # botões apertados junto com Fn
        self.held = set()         # botões entregues ao jogo e ainda apertados
        self.axis_range = {}      # código -> (mínimo, máximo)
        self.axis_value = {}      # nome -> último valor entregue
        self.suppressed_axes = set()

    def set_axis_range(self, code, minimum, maximum):
        self.axis_range[code] = (minimum, maximum)

    def feed(self, ev_type, code, value, ms):
        """Recebe um evento cru e devolve a lista de eventos para o jogo.

        Botão: ("button", nome, "down" | "up", ms)
        Eixo:  ("axis", nome, valor de -1 a 1, ms)
        """
        if ev_type == EV_KEY:
            return self._key(code, value, ms)
        if ev_type == EV_ABS:
            return self._abs(code, value, ms)
        return []

    def _key(self, code, value, ms):
        if code == FN_CODE:
            self.fn_held = value != 0
            return []
        name = BUTTON_CODES.get(code)
        if name is None or value == 2:   # fora do contrato, ou auto-repeat do kernel
            return []
        if value == 1:
            if self.fn_held:
                self.suppressed.add(name)
                return []
            self.held.add(name)
            return [("button", name, DOWN, ms)]
        # soltou
        if name in self.suppressed:
            self.suppressed.discard(name)
            return []
        if name not in self.held:
            return []
        self.held.discard(name)
        return [("button", name, UP, ms)]

    def _abs(self, code, raw, ms):
        name = AXIS_CODES.get(code)
        if name is None:
            return []
        lo, hi = self.axis_range.get(code, (-1800, 1800))
        center = (lo + hi) / 2.0
        half = (hi - lo) / 2.0 or 1.0
        v = max(-1.0, min(1.0, (raw - center) / half))
        if abs(v) < self.deadzone:
            v = 0.0
        else:
            # reescala para começar em 0 logo depois da zona morta
            v = (abs(v) - self.deadzone) / (1.0 - self.deadzone) * (1 if v > 0 else -1)
        if self.fn_held:
            if v:
                self.suppressed_axes.add(name)
            return []
        if name in self.suppressed_axes:
            if v:
                return []
            self.suppressed_axes.discard(name)
        last = self.axis_value.get(name, 0.0)
        if v == last or (v != 0.0 and abs(v - last) < 0.02):
            return []
        self.axis_value[name] = v
        return [("axis", name, v, ms)]


class GamepadReader:
    """Abre os dispositivos de entrada do console e alimenta um InputState."""

    def __init__(self, state, clock_offset):
        self.state = state
        self.clock_offset = clock_offset  # segundos de época no início do jogo
        import fcntl  # só existe no Linux

        self.files = []
        self.pending = {}
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                f = open(path, "rb", buffering=0)
            except OSError:
                continue
            os.set_blocking(f.fileno(), False)
            self.files.append(f)
            self.pending[f.fileno()] = b""
            for code in AXIS_CODES:
                try:
                    buf = fcntl.ioctl(f.fileno(), _eviocgabs(code), bytes(ABSINFO.size))
                except OSError:
                    continue
                _, lo, hi, _, _, _ = ABSINFO.unpack(buf)
                if hi > lo:
                    state.set_axis_range(code, lo, hi)

    def fileno_list(self):
        return [f.fileno() for f in self.files]

    def read(self, fd):
        f = next((x for x in self.files if x.fileno() == fd), None)
        if f is None:
            return []
        out = []
        while True:
            try:
                data = f.read(EVENT.size * 64)
            except BlockingIOError:
                break
            except OSError:
                self.files.remove(f)
                f.close()
                break
            if not data:
                break
            data = self.pending.get(fd, b"") + data
            complete = len(data) // EVENT.size * EVENT.size
            self.pending[fd] = data[complete:]
            for i in range(0, complete, EVENT.size):
                sec, usec, ev_type, code, value = EVENT.unpack_from(data, i)
                ms = int((sec + usec / 1e6 - self.clock_offset) * 1000)
                out.extend(self.state.feed(ev_type, code, value, ms))
        return out

    def close(self):
        for f in self.files:
            f.close()
        self.files = []
        self.pending.clear()
