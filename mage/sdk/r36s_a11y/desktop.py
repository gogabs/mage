"""Entrada no PC pela janela da SDL: teclado, texto, mouse e controles.

Cada tecla ou botão vira duas coisas:
  - o botão do R36S que fica no mesmo lugar (Enter e Z são o b, o botão de
    baixo do controle também), para on_button e os menus continuarem
    funcionando como no console;
  - o controle de verdade ("key", "space"), ("pad", "a"), ("mouse", "left"),
    para as ações do jogo (veja actions.py) e para on_key.

Ctrl faz o papel do Fn, como no modo antigo: o que for apertado com ele não
chega aos botões nem às ações. No controle, o botão Xbox/PS/Home é o Fn.
F11 e Alt + Enter alternam a tela cheia; Ctrl + C e fechar a janela saem.
"""
import ctypes
import struct

from .actions import KEY_TO_R36S, NINTENDO, PAD_TO_R36S, PLAYSTATION, XBOX
from .buttons import BUTTON_CODES, FN_CODE
from .input import EV_ABS, EV_KEY

CODES = {name: code for code, name in BUTTON_CODES.items()}  # nome do R36S -> código evdev

SDL_INIT_JOYSTICK = 0x200
SDL_INIT_GAMECONTROLLER = 0x2000
EVENT_SIZE = 64  # SDL_Event tem 56 bytes; folga de sobra

SDL_QUIT = 0x100
SDL_WINDOWEVENT = 0x200
SDL_KEYDOWN, SDL_KEYUP, SDL_TEXTINPUT = 0x300, 0x301, 0x303
SDL_MOUSEMOTION, SDL_MOUSEBUTTONDOWN, SDL_MOUSEBUTTONUP, SDL_MOUSEWHEEL = 0x400, 0x401, 0x402, 0x403
SDL_CONTROLLERAXISMOTION = 0x650
SDL_CONTROLLERBUTTONDOWN, SDL_CONTROLLERBUTTONUP = 0x651, 0x652
SDL_CONTROLLERDEVICEADDED, SDL_CONTROLLERDEVICEREMOVED = 0x653, 0x654
WINDOW_FOCUS_GAINED, WINDOW_FOCUS_LOST = 12, 13
KMOD_ALT = 0x0300

# Teclas: código da SDL (SDL_Keycode) -> nome usado nas ações.
SCANCODE_MASK = 1 << 30
SCANCODE_NAMES = {
    57: "capslock", 70: "printscreen", 71: "scrolllock", 72: "pause", 73: "insert",
    74: "home", 75: "pageup", 77: "end", 78: "pagedown", 79: "right", 80: "left",
    81: "down", 82: "up", 83: "numlock", 84: "kp/", 85: "kp*", 86: "kp-", 87: "kp+",
    88: "kp enter", 98: "kp0", 99: "kp.", 101: "menu",
    224: "lctrl", 225: "lshift", 226: "lalt", 227: "lgui",
    228: "rctrl", 229: "rshift", 230: "ralt", 231: "rgui",
}
SCANCODE_NAMES.update({58 + i: "f%d" % (i + 1) for i in range(12)})
SCANCODE_NAMES.update({89 + i: "kp%d" % (i + 1) for i in range(9)})
CHAR_NAMES = {8: "backspace", 9: "tab", 13: "return", 27: "escape", 32: "space", 127: "delete"}

PAD_NAMES = ("a", "b", "x", "y", "back", "guide", "start", "leftstick", "rightstick",
             "leftshoulder", "rightshoulder", "dpup", "dpdown", "dpleft", "dpright")
PAD_GUIDE = 5
AXIS_TRIGGERS = {4: "lefttrigger", 5: "righttrigger"}
AXIS_STICKS = {0: 0x00, 1: 0x01, 2: 0x03, 3: 0x04}  # eixo da SDL -> ABS_X, ABS_Y, ABS_RX, ABS_RY
TRIGGER_DOWN, TRIGGER_UP = 12000, 6000  # com folga, para o gatilho não "tremer"
MOUSE_NAMES = {1: "left", 2: "middle", 3: "right"}

# SDL_GameControllerType -> família, para dizer o nome certo dos botões.
PAD_TYPES = {3: PLAYSTATION, 4: PLAYSTATION, 7: PLAYSTATION,
             5: NINTENDO, 11: NINTENDO, 12: NINTENDO, 13: NINTENDO}


def key_name(sym, scancode=0):
    """Nome da tecla: "space", "return", "a", "ç", "f1", "up", "lshift"."""
    if sym & SCANCODE_MASK:
        return SCANCODE_NAMES.get(sym & ~SCANCODE_MASK, "tecla %d" % scancode)
    if sym in CHAR_NAMES:
        return CHAR_NAMES[sym]
    if 32 < sym < 0x110000:
        return chr(sym).lower()
    return "tecla %d" % scancode


def parse_event(buf):
    """Traduz os bytes de um SDL_Event numa tupla simples (ou None)."""
    etype = struct.unpack_from("<I", buf, 0)[0]
    if etype == SDL_QUIT:
        return ("quit",)
    if etype == SDL_WINDOWEVENT:
        event = buf[12]
        if event in (WINDOW_FOCUS_GAINED, WINDOW_FOCUS_LOST):
            return ("focus", event == WINDOW_FOCUS_GAINED)
        return None
    if etype in (SDL_KEYDOWN, SDL_KEYUP):
        scancode, sym, mod = struct.unpack_from("<iiH", buf, 16)
        return ("key", etype == SDL_KEYDOWN, bool(buf[13]), scancode, sym, mod)
    if etype == SDL_TEXTINPUT:
        return ("text", bytes(buf[12:44]).split(b"\0", 1)[0].decode("utf-8", "replace"))
    if etype == SDL_MOUSEMOTION:
        x, y = struct.unpack_from("<ii", buf, 20)
        return ("motion", x, y)
    if etype in (SDL_MOUSEBUTTONDOWN, SDL_MOUSEBUTTONUP):
        x, y = struct.unpack_from("<ii", buf, 20)
        return ("mousebutton", etype == SDL_MOUSEBUTTONDOWN, buf[16], x, y)
    if etype == SDL_MOUSEWHEEL:
        _, dy, flipped = struct.unpack_from("<iiI", buf, 16)
        return ("wheel", -dy if flipped else dy)
    if etype == SDL_CONTROLLERAXISMOTION:
        which, axis, value = struct.unpack_from("<iB3xh", buf, 8)
        return ("padaxis", which, axis, value)
    if etype in (SDL_CONTROLLERBUTTONDOWN, SDL_CONTROLLERBUTTONUP):
        which, button = struct.unpack_from("<iB", buf, 8)
        return ("padbutton", etype == SDL_CONTROLLERBUTTONDOWN, which, button)
    if etype == SDL_CONTROLLERDEVICEADDED:
        return ("padadded", struct.unpack_from("<i", buf, 8)[0])
    if etype == SDL_CONTROLLERDEVICEREMOVED:
        return ("padremoved", struct.unpack_from("<i", buf, 8)[0])
    return None


def _signatures(sdl):
    vp, ci = ctypes.c_void_p, ctypes.c_int
    for name, res, args in [
        ("SDL_InitSubSystem", ci, [ctypes.c_uint32]),
        ("SDL_PollEvent", ci, [ctypes.c_void_p]),
        ("SDL_GameControllerOpen", vp, [ci]),
        ("SDL_GameControllerClose", None, [vp]),
        ("SDL_GameControllerName", ctypes.c_char_p, [vp]),
        ("SDL_GameControllerGetJoystick", vp, [vp]),
        ("SDL_JoystickInstanceID", ci, [vp]),
        ("SDL_IsGameController", ci, [ci]),
    ]:
        f = getattr(sdl, name)
        f.restype, f.argtypes = res, args
    for name, res, args in [  # mais novas que a SDL 2.0.10
        ("SDL_GameControllerGetType", ci, [vp]),
        ("SDL_GameControllerRumble", ci, [vp, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32]),
    ]:
        f = getattr(sdl, name, None)
        if f is not None:
            f.restype, f.argtypes = res, args


class Pad:
    def __init__(self, handle, name, family):
        self.handle, self.name, self.family = handle, name, family
        self.down = set()         # botões da SDL apertados
        self.triggers = set()     # gatilhos apertados


class DesktopInput:
    """Lê os eventos da janela da SDL e os entrega como eventos do Game."""

    def __init__(self, gfx, state, clock):
        self.gfx = gfx
        self.sdl = gfx.sdl
        self.state = state        # InputState: regra do Fn e eixos
        self.clock = clock        # ms desde o início do jogo
        _signatures(self.sdl)
        self.sdl.SDL_InitSubSystem(SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER)
        for code in AXIS_STICKS.values():
            state.set_axis_range(code, -32768, 32767)
        self.pads = {}            # id da SDL -> Pad
        self.last_pad = None
        self.keys_down = {}       # nome da tecla -> entregue às ações (False se foi com Fn)
        self.mouse_down = set()
        self.buf = ctypes.create_string_buffer(EVENT_SIZE)
        self.first_poll = True

    def describe(self):
        pads = ", ".join(p.name for p in self.pads.values())
        return "janela da SDL: teclado, mouse" + (", " + pads if pads else ", sem controle")

    def poll(self):
        out = []
        ms = self.clock()
        while self.sdl.SDL_PollEvent(self.buf):
            ev = parse_event(self.buf.raw)
            if ev is not None:
                out.extend(self._handle(ev, ms))
        self.first_poll = False
        return out

    # --- tradução ------------------------------------------------------------
    def _raw(self, code, value, ms):
        return self.state.feed(EV_KEY, code, value, ms)

    def _handle(self, ev, ms):
        kind = ev[0]
        if kind == "quit":
            return [("quit",)]
        if kind == "focus":
            return ([("focus", True)] if ev[1] else self.release_all(ms) + [("focus", False)])
        if kind == "key":
            return self._key(ev[1], ev[2], ev[3], ev[4], ev[5], ms)
        if kind == "text":
            return [("text", ev[1])]
        if kind == "motion":
            return [("mouse", "move", ev[1], ev[2], 0)]
        if kind == "mousebutton":
            name = MOUSE_NAMES.get(ev[2])
            out = [("mouse", "down" if ev[1] else "up", ev[3], ev[4], name or ev[2])]
            if name is not None:
                if ev[1]:
                    self.mouse_down.add(name)
                    out.append(("control", "mouse", name, "down", ms))
                elif name in self.mouse_down:
                    self.mouse_down.discard(name)
                    out.append(("control", "mouse", name, "up", ms))
            return out
        if kind == "wheel":
            return [("mouse", "wheel", 0, 0, ev[1])]
        if kind == "padadded":
            return self._pad_added(ev[1])
        if kind == "padremoved":
            return self._pad_removed(ev[1], ms)
        if kind == "padbutton":
            return self._pad_button(ev[2], ev[3], ev[1], ms)
        if kind == "padaxis":
            return self._pad_axis(ev[1], ev[2], ev[3], ms)
        return []

    def _key(self, down, repeat, scancode, sym, mod, ms):
        name = key_name(sym, scancode)
        out = [("key", name, ("repeat" if repeat else "down") if down else "up", ms)]
        if repeat:
            return out                   # a repetição do SDK vem de Game(repeat=True)
        if name in ("lctrl", "rctrl"):
            out.extend(self._raw(FN_CODE, 1 if down else 0, ms))
            return out
        if down and (name == "f11" or (name == "return" and mod & KMOD_ALT)):
            self.gfx.toggle_fullscreen()
            return out
        if down and name == "c" and self.state.fn_held:
            return out + [("quit",)]     # Ctrl + C, como no terminal
        button = KEY_TO_R36S.get(name)
        if button is not None:
            out.extend(self._raw(CODES[button], 1 if down else 0, ms))
        if down:
            self.keys_down[name] = not self.state.fn_held
            if self.keys_down[name]:
                out.append(("control", "key", name, "down", ms))
        elif self.keys_down.pop(name, False):
            out.append(("control", "key", name, "up", ms))
        return out

    def _pad_added(self, index):
        handle = self.sdl.SDL_GameControllerOpen(index)
        if not handle:
            return []
        joystick = self.sdl.SDL_GameControllerGetJoystick(handle)
        instance = self.sdl.SDL_JoystickInstanceID(joystick)
        if instance in self.pads:        # a SDL avisa duas vezes no começo
            self.sdl.SDL_GameControllerClose(handle)
            return []
        name = (self.sdl.SDL_GameControllerName(handle) or b"controle").decode("utf-8", "replace")
        family = XBOX
        get_type = getattr(self.sdl, "SDL_GameControllerGetType", None)
        if get_type is not None:
            family = PAD_TYPES.get(get_type(handle), XBOX)
        elif any(s in name for s in ("PS3", "PS4", "PS5", "DualShock", "DualSense")):
            family = PLAYSTATION
        self.pads[instance] = Pad(handle, name, family)
        return [("device", "added", family, name, self.first_poll)]

    def _pad_removed(self, instance, ms):
        pad = self.pads.pop(instance, None)
        if pad is None:
            return []
        out = self._release_pad(pad, ms)
        self.sdl.SDL_GameControllerClose(pad.handle)
        if self.last_pad is pad:
            self.last_pad = None
        return out + [("device", "removed", pad.family, pad.name, False)]

    def _pad_button(self, instance, button, down, ms):
        pad = self.pads.get(instance)
        if pad is None or button >= len(PAD_NAMES):
            return []
        self.last_pad = pad
        if button == PAD_GUIDE:
            return self._raw(FN_CODE, 1 if down else 0, ms)
        return self._pad_control(pad, PAD_NAMES[button], down, ms)

    def _pad_control(self, pad, name, down, ms):
        out = [("pad", pad.family)]      # o Game passa a falar os nomes deste controle
        out.extend(self._raw(CODES[PAD_TO_R36S[name]], 1 if down else 0, ms))
        if down:
            if not self.state.fn_held:
                pad.down.add(name)
                out.append(("control", "pad", name, "down", ms))
        elif name in pad.down:
            pad.down.discard(name)
            out.append(("control", "pad", name, "up", ms))
        return out

    def _pad_axis(self, instance, axis, value, ms):
        pad = self.pads.get(instance)
        if pad is None:
            return []
        if axis in AXIS_TRIGGERS:
            name = AXIS_TRIGGERS[axis]
            if value > TRIGGER_DOWN and name not in pad.triggers:
                pad.triggers.add(name)
                self.last_pad = pad
                return self._pad_control(pad, name, True, ms)
            if value < TRIGGER_UP and name in pad.triggers:
                pad.triggers.discard(name)
                return self._pad_control(pad, name, False, ms)
            return []
        if axis in AXIS_STICKS:
            return self.state.feed(EV_ABS, AXIS_STICKS[axis], value, ms)
        return []

    def _release_pad(self, pad, ms):
        out = []
        for name in list(pad.down) + list(pad.triggers):
            pad.triggers.discard(name)
            out.extend(self._pad_control(pad, name, False, ms))
        pad.down.clear()
        return out

    def release_all(self, ms):
        """Solta tudo o que está apertado (a janela perdeu o foco)."""
        out = []
        for name in list(self.keys_down):
            button = KEY_TO_R36S.get(name)
            if button is not None:
                out.extend(self._raw(CODES[button], 0, ms))
            if self.keys_down.pop(name):
                out.append(("control", "key", name, "up", ms))
        for name in list(self.mouse_down):
            out.append(("control", "mouse", name, "up", ms))
        self.mouse_down.clear()
        for pad in self.pads.values():
            out.extend(self._release_pad(pad, ms))
        out.extend(self._raw(FN_CODE, 0, ms))
        return out

    # --- saída -------------------------------------------------------------------
    def rumble(self, strength, seconds):
        fn = getattr(self.sdl, "SDL_GameControllerRumble", None)
        if fn is None or self.last_pad is None:
            return False
        level = int(max(0.0, min(1.0, strength)) * 0xFFFF)
        return fn(self.last_pad.handle, level, level, int(seconds * 1000)) == 0

    def close(self):
        for pad in self.pads.values():
            self.sdl.SDL_GameControllerClose(pad.handle)
        self.pads.clear()
