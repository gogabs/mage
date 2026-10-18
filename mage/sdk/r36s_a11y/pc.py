"""Bastidores para rodar o jogo no PC com Windows, sem o console.

O jogo não muda nada: a biblioteca troca a origem dos eventos e a voz.

  - Teclado: lido do console ou, se o jogo abrir a tela, da janela do jogo
    (a janela precisa estar em foco).
  - Controle de Xbox (ou compatível com XInput): botões e analógicos.
  - Fala: voz do Windows (SAPI) por um processo do PowerShell.

Teclado e controle viram os mesmos códigos evdev do R36S e passam pelo mesmo
InputState do console, então a regra do Fn vale igual: Ctrl faz o papel do
Fn, e o que for apertado com ele não chega ao jogo.
"""
import base64
import ctypes
import os
import queue
import subprocess
import sys
import threading

from .buttons import FN_CODE
from .input import EV_ABS, EV_KEY
from .speech import _user_voice

# --- teclado ----------------------------------------------------------------

# Tecla virtual do Windows -> código evdev do botão no R36S.
KEYMAP = {
    0x26: 0x220,  # seta para cima -> up
    0x28: 0x221,  # seta para baixo -> down
    0x25: 0x222,  # seta para a esquerda -> left
    0x27: 0x223,  # seta para a direita -> right
    0x0D: 0x130,  # Enter -> b (confirmar)
    ord("Z"): 0x130,
    0x08: 0x131,  # Backspace -> a (voltar)
    ord("X"): 0x131,
    ord("S"): 0x133,  # x (de cima)
    ord("A"): 0x134,  # y (da esquerda)
    ord("Q"): 0x136,  # l1
    ord("W"): 0x137,  # r1
    ord("1"): 0x138,  # l2
    ord("2"): 0x139,  # r2
    ord("3"): 0x2C2,  # l3
    ord("4"): 0x2C3,  # r3
    0x1B: 0x2C1,  # Esc -> start (pausa)
    0x09: 0x2C0,  # Tab -> select (repetir)
    0x11: FN_CODE,  # Ctrl -> Fn
}


def key_event(vk, down, pressed):
    """Traduz uma tecla em evento evdev cru (tipo, código, valor) ou None.

    pressed guarda as teclas virtuais seguradas, para marcar a repetição do
    teclado como valor 2 (auto-repeat), que o InputState descarta.
    """
    code = KEYMAP.get(vk)
    if code is None:
        return None
    if down:
        value = 2 if vk in pressed else 1
        pressed.add(vk)
    else:
        if vk not in pressed:
            return None
        pressed.discard(vk)
        value = 0
    return (EV_KEY, code, value)


# --- controle (XInput) ------------------------------------------------------

# Bit do XInput -> código evdev. A posição física manda: o de baixo do Xbox
# (A) é o "b" do R36S, o da direita (B) é o "a".
XINPUT_BUTTONS = (
    (0x0001, 0x220),  # direcional para cima
    (0x0002, 0x221),
    (0x0004, 0x222),
    (0x0008, 0x223),
    (0x0010, 0x2C1),  # Start (Menu) -> start
    (0x0020, 0x2C0),  # Back (View) -> select
    (0x0040, 0x2C2),  # analógico esquerdo apertado -> l3
    (0x0080, 0x2C3),  # analógico direito apertado -> r3
    (0x0100, 0x136),  # LB -> l1
    (0x0200, 0x137),  # RB -> r1
    (0x1000, 0x130),  # A (de baixo) -> b
    (0x2000, 0x131),  # B (da direita) -> a
    (0x4000, 0x134),  # X (da esquerda) -> y
    (0x8000, 0x133),  # Y (de cima) -> x
)
XINPUT_GUIDE = 0x0400  # botão Xbox -> Fn (só pelo XInputGetStateEx)
TRIGGER_THRESHOLD = 30  # XINPUT_GAMEPAD_TRIGGER_THRESHOLD
L2_BIT, R2_BIT = 0x10000, 0x20000  # gatilhos viram bits extras
AXIS_RANGE = (-32768, 32767)


def pad_buttons(buttons, left_trigger, right_trigger):
    """Junta botões e gatilhos (analógicos no Xbox, botões no R36S) numa máscara."""
    if left_trigger > TRIGGER_THRESHOLD:
        buttons |= L2_BIT
    if right_trigger > TRIGGER_THRESHOLD:
        buttons |= R2_BIT
    return buttons


def pad_events(prev, cur):
    """Eventos evdev crus entre dois estados do controle.

    prev e cur são (máscara de botões, lx, ly, rx, ry), com eixos do XInput
    (para cima é positivo). Fn é apertado antes e solto depois dos outros,
    como acontece no console.
    """
    events = []
    pb, cb = prev[0], cur[0]
    if cb & XINPUT_GUIDE and not pb & XINPUT_GUIDE:
        events.append((EV_KEY, FN_CODE, 1))
    for bit, code in XINPUT_BUTTONS + ((L2_BIT, 0x138), (R2_BIT, 0x139)):
        if (pb ^ cb) & bit:
            events.append((EV_KEY, code, 1 if cb & bit else 0))
    if pb & XINPUT_GUIDE and not cb & XINPUT_GUIDE:
        events.append((EV_KEY, FN_CODE, 0))
    # lx, ly, rx, ry -> ABS_X, ABS_Y, ABS_RX, ABS_RY; Y invertido (no evdev, cima é negativo)
    for i, (code, sign) in enumerate(((0x00, 1), (0x01, -1), (0x03, 1), (0x04, -1)), 1):
        if prev[i] != cur[i]:
            events.append((EV_ABS, code, max(AXIS_RANGE[0], min(AXIS_RANGE[1], sign * cur[i]))))
    return events


class _Gamepad(ctypes.Structure):
    _fields_ = [("buttons", ctypes.c_ushort), ("left_trigger", ctypes.c_ubyte),
                ("right_trigger", ctypes.c_ubyte), ("lx", ctypes.c_short),
                ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]


class _XInputState(ctypes.Structure):
    _fields_ = [("packet", ctypes.c_uint32), ("pad", _Gamepad)]


class _XInput:
    RETRY = 2.0  # segundos entre procuras de controle desconectado

    def __init__(self):
        self.lib = None
        self.get_state = None
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self.lib = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        if self.lib is None:
            return
        try:
            self.get_state = self.lib[100]  # XInputGetStateEx: inclui o botão Xbox
        except (AttributeError, OSError):
            self.get_state = self.lib.XInputGetState
        self.get_state.argtypes = [ctypes.c_uint32, ctypes.POINTER(_XInputState)]
        self.get_state.restype = ctypes.c_uint32
        self.index = None
        self.next_search = 0.0
        self.prev = (0, 0, 0, 0, 0)
        self.state = _XInputState()

    def poll(self, now):
        if self.get_state is None:
            return []
        if self.index is None:
            if now < self.next_search:
                return []
            self.next_search = now + self.RETRY
            for i in range(4):
                if self.get_state(i, ctypes.byref(self.state)) == 0:
                    self.index = i
                    break
            else:
                return []
        elif self.get_state(self.index, ctypes.byref(self.state)) != 0:
            self.index = None  # desconectou: solta tudo
            cur = (0, 0, 0, 0, 0)
            events, self.prev = pad_events(self.prev, cur), cur
            return events
        p = self.state.pad
        cur = (pad_buttons(p.buttons, p.left_trigger, p.right_trigger), p.lx, p.ly, p.rx, p.ry)
        events, self.prev = pad_events(self.prev, cur), cur
        return events

    @property
    def connected(self):
        return self.get_state is not None and self.index is not None


# --- console do Windows -----------------------------------------------------

class _KeyEventRecord(ctypes.Structure):
    _fields_ = [("key_down", ctypes.c_int32), ("repeat", ctypes.c_ushort),
                ("vk", ctypes.c_ushort), ("scan", ctypes.c_ushort),
                ("char", ctypes.c_wchar), ("control", ctypes.c_uint32)]


class _EventUnion(ctypes.Union):
    _fields_ = [("key", _KeyEventRecord), ("raw", ctypes.c_byte * 16)]


class _InputRecord(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ushort), ("event", _EventUnion)]


KEY_EVENT = 0x0001
STD_INPUT_HANDLE = -10


class _ConsoleKeyboard:
    def __init__(self):
        self.ok = False
        self.pressed = set()
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError:
            return
        self.k32 = k32
        k32.GetStdHandle.restype = ctypes.c_void_p
        k32.GetNumberOfConsoleInputEvents.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        k32.ReadConsoleInputW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_InputRecord),
                                          ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        k32.FlushConsoleInputBuffer.argtypes = [ctypes.c_void_p]
        self.handle = k32.GetStdHandle(STD_INPUT_HANDLE)
        count = ctypes.c_uint32()
        if not k32.GetNumberOfConsoleInputEvents(self.handle, ctypes.byref(count)):
            return  # entrada redirecionada: não é um console
        k32.FlushConsoleInputBuffer(self.handle)
        self.records = (_InputRecord * 64)()
        self.ok = True

    def poll(self):
        if not self.ok:
            return []
        count = ctypes.c_uint32()
        if not self.k32.GetNumberOfConsoleInputEvents(self.handle, ctypes.byref(count)) or not count.value:
            return []
        read = ctypes.c_uint32()
        if not self.k32.ReadConsoleInputW(self.handle, self.records, len(self.records), ctypes.byref(read)):
            return []
        events = []
        for rec in self.records[:read.value]:
            if rec.type != KEY_EVENT:
                continue
            ev = key_event(rec.event.key.vk, bool(rec.event.key.key_down), self.pressed)
            if ev is not None:
                events.append(ev)
        return events


# Scancode da SDL -> tecla virtual do Windows (as mesmas do KEYMAP).
SDL_SCANCODES = {
    82: 0x26, 81: 0x28, 80: 0x25, 79: 0x27,  # setas
    40: 0x0D, 29: ord("Z"), 42: 0x08, 27: ord("X"),
    22: ord("S"), 4: ord("A"), 20: ord("Q"), 26: ord("W"),
    30: ord("1"), 31: ord("2"), 32: ord("3"), 33: ord("4"),
    41: 0x1B, 43: 0x09, 224: 0x11, 228: 0x11,  # Esc, Tab, Ctrl esquerdo e direito
}


def sdl_key_events(keys, pressed):
    """Eventos evdev crus a partir do estado do teclado da SDL (lista de 0/1
    por scancode). A SDL não avisa repetição, só se a tecla está apertada."""
    down = set()
    for scancode, vk in SDL_SCANCODES.items():
        if scancode < len(keys) and keys[scancode]:
            down.add(vk)
    events = []
    # Ctrl (Fn) é apertado antes e solto depois dos outros, como no console
    for vk in sorted(down - pressed, key=lambda v: v != 0x11):
        events.append(key_event(vk, True, pressed))
    for vk in sorted(pressed - down, key=lambda v: v == 0x11):
        events.append(key_event(vk, False, pressed))
    return events


class _SdlKeyboard:
    """Teclado da janela da SDL, quando o jogo abre a tela: a janela fica com
    o foco e o console deixa de receber as teclas."""

    def __init__(self, gfx):
        self.sdl = gfx.sdl
        self.sdl.SDL_GetKeyboardState.restype = ctypes.POINTER(ctypes.c_uint8)
        self.sdl.SDL_GetKeyboardState.argtypes = [ctypes.POINTER(ctypes.c_int)]
        self.pressed = set()

    def poll(self):
        self.sdl.SDL_PumpEvents()
        n = ctypes.c_int()
        state = self.sdl.SDL_GetKeyboardState(ctypes.byref(n))
        return sdl_key_events(state[:min(n.value, 256)], self.pressed)


class WindowsInput:
    """Teclado (do console ou da janela do jogo) e controle XInput,
    entregues a um InputState."""

    def __init__(self, state, clock, graphics=lambda: None):
        self.state = state
        self.clock = clock  # função que devolve os ms desde o início do jogo
        self.graphics = graphics  # função que devolve a tela aberta, ou None
        self.window_keyboard = None
        self.keyboard = _ConsoleKeyboard()
        self.pad = _XInput()
        for code in (0x00, 0x01, 0x03, 0x04):
            state.set_axis_range(code, *AXIS_RANGE)
        self.pad.poll(0.0)

    def describe(self):
        parts = ["teclado" if self.keyboard.ok else "sem teclado (entrada não é um console)"]
        parts.append("controle conectado" if self.pad.connected else "sem controle")
        return ", ".join(parts)

    def poll(self, now):
        raw = self.keyboard.poll() + self.pad.poll(now)
        if self.window_keyboard is None:
            gfx = self.graphics()
            if gfx is not None and gfx.available:
                self.window_keyboard = _SdlKeyboard(gfx)
        if self.window_keyboard is not None:
            raw += self.window_keyboard.poll()
        if not raw:
            return []
        ms = self.clock()
        out = []
        for ev_type, code, value in raw:
            out.extend(self.state.feed(ev_type, code, value, ms))
        return out


# --- fala (SAPI) ------------------------------------------------------------

# Programa em C# compilado pelo PowerShell (Windows PowerShell 5.1, que tem o
# System.Speech). Lê comandos no stdin e avisa no stdout quando cada fala
# termina ("E <id> 1") ou é cortada ("E <id> 0").
_SAPI_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
Add-Type -ReferencedAssemblies System.Speech -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Speech.Synthesis;
using System.Text;
public static class A11yFala {
    static readonly object Lock = new object();
    static readonly Dictionary<Prompt, string> Ids = new Dictionary<Prompt, string>();
    static void Out(string s) { lock (Lock) { Console.Out.WriteLine(s); Console.Out.Flush(); } }
    static string Text(string b64) { return Encoding.UTF8.GetString(Convert.FromBase64String(b64)); }
    public static void Run(string lang, int rate, int volume, string voice) {
        var synth = new SpeechSynthesizer();
        synth.SetOutputToDefaultAudioDevice();
        voice = Text(voice);
        try {
            if (voice.Length > 0) synth.SelectVoice(voice);
            else foreach (var v in synth.GetInstalledVoices())
                if (v.Enabled && v.VoiceInfo.Culture.Name.Equals(lang, StringComparison.OrdinalIgnoreCase)) {
                    synth.SelectVoice(v.VoiceInfo.Name);
                    break;
                }
        } catch (Exception) { }
        synth.Rate = rate;
        synth.Volume = volume;
        synth.SpeakCompleted += (s, e) => {
            string id;
            lock (Lock) {
                if (!Ids.TryGetValue(e.Prompt, out id)) return;
                Ids.Remove(e.Prompt);
            }
            Out("E " + id + (e.Cancelled ? " 0" : " 1"));
        };
        Out("OK " + synth.Voice.Name);
        string line;
        while ((line = Console.In.ReadLine()) != null) {
            if (line == "H") { synth.SpeakAsyncCancelAll(); continue; }
            var p = line.Split(new[] { ' ' }, 3);  // S|Q <id> <texto em base64>
            if (p.Length < 3) continue;
            if (p[0] == "S") synth.SpeakAsyncCancelAll();
            var prompt = new Prompt(Text(p[2]));
            lock (Lock) Ids[prompt] = p[1];
            synth.SpeakAsync(prompt);
        }
    }
}
'@
[A11yFala]::Run('%(lang)s', %(rate)d, %(volume)d, '%(voice)s')
"""


def sapi_settings(voice):
    """Converte a voz do usuário (SSIP, -100..100) para a SAPI: velocidade
    -10..10 e volume 0..100."""
    rate = int(round(voice.get("RATE", 0) / 10.0))
    volume = int(round((voice.get("VOLUME", 100) + 100) / 2.0))
    return max(-10, min(10, rate)), max(0, min(100, volume))


class WindowsSpeech:
    """Mesma interface do Speech, falando pela voz do Windows.

    A voz é a do idioma do jogo (pt-BR, por exemplo) quando instalada; a
    variável A11Y_VOZ escolhe outra pelo nome ("Microsoft Maria Desktop").
    """

    def __init__(self, client="jogo", language="pt-BR"):
        self.client = client
        self.language = language
        self.proc = None
        self.available = True
        self.lines = queue.Queue()
        self.callbacks = {}
        self.events = []
        self.next_id = 0

    def _start(self):
        rate, volume = sapi_settings(_user_voice())
        voice = os.environ.get("A11Y_VOZ", "")
        script = _SAPI_SCRIPT % {
            "lang": "".join(c for c in self.language if c.isalnum() or c == "-"),
            "rate": rate, "volume": volume,
            "voice": base64.b64encode(voice.encode("utf-8")).decode("ascii"),
        }
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        self.proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._read, args=(self.proc.stdout,), daemon=True).start()

    def _read(self, stream):
        for raw in stream:
            self.lines.put(raw.decode("utf-8", "replace").strip())
        self.lines.put(None)

    def _ensure(self):
        if self.proc is None and self.available:
            try:
                self._start()
            except OSError:
                self.available = False
        return self.proc is not None

    def _send(self, line):
        try:
            self.proc.stdin.write(line.encode("ascii") + b"\n")
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError):
            self.close()
            self.available = False
            return False

    def fileno(self):
        return None

    def say(self, text, queue=False, on_done=None):
        if self._ensure():
            self.next_id += 1
            msg_id = str(self.next_id)
            b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
            if on_done is not None:
                self.callbacks[msg_id] = on_done
            if self._send("%s %s %s" % ("Q" if queue else "S", msg_id, b64)):
                return
            self.callbacks.pop(msg_id, None)
        print("[fala] " + text, file=sys.stderr)
        if on_done is not None:
            self.events.append((on_done, True))

    def hush(self):
        if self._ensure():
            self._send("H")

    def poll(self):
        while True:
            try:
                line = self.lines.get_nowait()
            except queue.Empty:
                break
            if line is None:  # o PowerShell saiu
                self.close()
                self.available = False
                for fn in self.callbacks.values():
                    self.events.append((fn, False))
                self.callbacks.clear()
                break
            parts = line.split()
            if len(parts) == 3 and parts[0] == "E":
                fn = self.callbacks.pop(parts[1], None)
                if fn is not None:
                    self.events.append((fn, parts[2] == "1"))
            elif parts[:1] == ["OK"]:
                print("[r36s_a11y] voz do Windows: %s" % line[3:], file=sys.stderr)
        ready, self.events = self.events, []
        return ready

    def close(self):
        if self.proc is not None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.proc = None


# --- fala pelo NVDA -----------------------------------------------------------

def nvda_estimate(text):
    """Segundos que o NVDA leva para falar o texto (ele não avisa quando
    termina): uns 15 caracteres por segundo, mais uma pausa."""
    return 0.4 + len(text) / 15.0


def load_nvda():
    """O cliente do NVDA (nvdaControllerClient), se o NVDA estiver aberto."""
    from . import native
    try:
        lib = native.load(["nvdaControllerClient64.dll", "nvdaControllerClient.dll"],
                          loader=ctypes.WinDLL)
    except (OSError, AttributeError):
        return None
    for name in ("nvdaController_speakText", "nvdaController_brailleMessage"):
        getattr(lib, name).argtypes = [ctypes.c_wchar_p]
    for name in ("nvdaController_speakText", "nvdaController_brailleMessage",
                 "nvdaController_cancelSpeech", "nvdaController_testIfRunning"):
        getattr(lib, name).restype = ctypes.c_ulong
    if lib.nvdaController_testIfRunning() != 0:
        return None
    return lib


class NvdaSpeech:
    """Mesma interface do Speech, falando pelo NVDA com a voz, a velocidade
    e o braille que o jogador escolheu nele.

    O NVDA não avisa quando termina de falar: on_done é chamado depois de
    um tempo estimado (nvda_estimate), ou com False se a fala for cortada.
    """

    def __init__(self, lib, clock=None):
        import time
        self.lib = lib
        self.clock = clock or time.monotonic
        self.available = True
        self.pending = []    # [quando termina, on_done]
        self.busy_until = 0.0
        self.events = []

    def fileno(self):
        return None

    def say(self, text, queue=False, on_done=None):
        now = self.clock()
        if not queue:
            self.hush()
        start = max(now, self.busy_until) if queue else now
        self.busy_until = start + nvda_estimate(text)
        if self.lib.nvdaController_speakText(text) != 0:   # o NVDA foi fechado
            self.available = False
            print("[fala] " + text, file=sys.stderr)
        self.lib.nvdaController_brailleMessage(text)
        if on_done is not None:
            self.pending.append([self.busy_until, on_done])

    def hush(self):
        self.lib.nvdaController_cancelSpeech()
        self.busy_until = 0.0
        for _, fn in self.pending:
            self.events.append((fn, False))
        self.pending = []

    def poll(self):
        now = self.clock()
        done = [p for p in self.pending if p[0] <= now]
        if done:
            self.pending = [p for p in self.pending if p[0] > now]
            self.events.extend((fn, True) for _, fn in done)
        ready, self.events = self.events, []
        return ready

    def close(self):
        self.pending = []
