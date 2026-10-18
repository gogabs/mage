"""Laço do jogo: entrada, fala, áudio, tempo e ciclo de vida."""
import json
import os
import select
import signal
import sys
import time

from .actions import KEYBOARD, R36S, Actions, button_label
from .audio import Audio
from .buttons import DOWN, REPEAT, UP
from .graphics import Graphics
from .input import GamepadReader, InputState
from . import speech_history
from .speech import Speech

REPEAT_DELAY = 0.4
REPEAT_INTERVAL = 0.1
PC_POLL = 0.004  # no PC, teclado e controle são consultados, não esperados


def _game_dir():
    env = os.environ.get("A11Y_GAME_DIR")
    if env:
        return env
    main = getattr(sys.modules.get("__main__"), "__file__", None)
    return os.path.dirname(os.path.abspath(main)) if main else os.getcwd()


def _manifest(game_dir):
    try:
        with open(os.path.join(game_dir, "game.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _is_pc():
    """No PC (janela, teclado, mouse, controles) ou no console (/dev/input)?

    Windows é sempre PC; no Linux, A11Y_PLATAFORMA=pc liga o modo PC.
    """
    choice = os.environ.get("A11Y_PLATAFORMA", "")
    if choice:
        return choice == "pc"
    return sys.platform == "win32"


def _speech(client, lang):
    """Speech Dispatcher no console; no Windows, o NVDA se estiver aberto e,
    senão, a voz do Windows.

    A11Y_FALA escolhe outra: "nvda", "sapi" (voz do Windows), "speechd" ou
    "terminal" (só escreve no terminal, para o leitor de tela do PC ler).
    """
    choice = os.environ.get("A11Y_FALA") or ("auto" if sys.platform == "win32" else "speechd")
    if choice in ("auto", "nvda"):
        from .pc import NvdaSpeech, load_nvda
        lib = load_nvda()
        if lib is not None:
            return NvdaSpeech(lib)
        if choice == "nvda":
            print("[r36s_a11y] NVDA não está aberto ou falta a nvdaControllerClient64.dll; "
                  "usando a voz do Windows", file=sys.stderr)
        choice = "sapi"
    if choice == "sapi":
        from .pc import WindowsSpeech
        return WindowsSpeech(client=client, language=lang)
    speech = Speech(client=client, language=lang)
    if choice == "terminal":
        speech.available = False
    return speech


class Game:
    """Um jogo acessível do R36S.

    Uso:
        game = Game()

        @game.on_button
        def botao(b, estado, ms): ...

        game.run()
    """

    def __init__(self, fps=60, repeat=False, axes=False, deadzone=0.2):
        self.dir = _game_dir()
        self.manifest = _manifest(self.dir)
        self.id = self.manifest.get("id") or os.path.basename(self.dir)
        self.name = self.manifest.get("name") or self.id
        self.lang = os.environ.get("A11Y_LANG", "pt-BR")
        self.save_dir = os.environ.get("A11Y_SAVE_DIR") or os.path.join(
            os.path.expanduser("~"), ".local", "share", "r36s-a11y", self.id)
        os.makedirs(self.save_dir, exist_ok=True)

        self.fps = fps
        self.repeat = repeat
        self.axes = axes
        self.speech = _speech(self.id, self.lang)
        self.sound = Audio(self.dir)
        self.input = InputState(deadzone=deadzone)
        self.pc = _is_pc()
        self.action_map = Actions()
        if isinstance(self.manifest.get("actions"), dict):  # ações escritas no game.json
            self.action_map.define(self.manifest["actions"])
        self.device = KEYBOARD if self.pc else R36S  # quem o jogador está usando

        self._handlers = {"button": [], "axis": [], "update": [], "quit": [], "start": [],
                          "draw": [], "action": [], "key": [], "text": [], "mouse": [],
                          "focus": [], "device": []}
        self._gfx = None
        self._desktop = None       # entrada pela janela da SDL, no PC
        self._actions_from_buttons = True  # no console, as ações vêm dos botões do R36S
        self._last_said = ""
        self._caption_fonts = None
        self._timers = []          # (quando, função)
        self._repeat_at = {}       # botão -> próximo repeat
        self._focus = []           # pilha de menus que recebem os botões antes do jogo
        self._running = False
        self.started_at = time.time()

    # --- registro de funções -------------------------------------------
    def on_button(self, fn):
        """fn(botão, estado, ms): estado é "down", "up" ou "repeat"."""
        self._handlers["button"].append(fn)
        return fn

    def on_axis(self, fn):
        """fn(eixo, valor, ms): só chamado com Game(axes=True)."""
        self._handlers["axis"].append(fn)
        return fn

    def on_update(self, fn):
        """fn(dt) chamado fps vezes por segundo."""
        self._handlers["update"].append(fn)
        return fn

    def on_draw(self, fn):
        """fn(gfx) desenha um quadro, logo depois dos on_update. Abre a tela."""
        self._handlers["draw"].append(fn)
        return fn

    @property
    def gfx(self):
        """Os gráficos (abre a tela no primeiro uso). Veja graphics.Graphics."""
        if self._gfx is None:
            self._gfx = Graphics(self.name, self.dir)
            self._gfx.open(desktop=self.pc)
        return self._gfx

    # --- ações e entrada do PC ------------------------------------------
    def actions(self, mapping):
        """Registra o mapa de ações do jogo. Veja actions.py.

        game.actions({"pular": {"key": "space", "r36s": "b"}})
        """
        self.action_map.define(mapping)

    def on_action(self, fn):
        """fn(ação, estado, ms): estado "down", "up" ou "repeat" (com repeat=True)."""
        self._handlers["action"].append(fn)
        return fn

    def label(self, action, device=None, every=False):
        """Nome do que aperta a ação no dispositivo em uso: "espaço" no
        teclado, "B" no R36S, "A" no Xbox, "xis" no PlayStation."""
        return self.action_map.label(action, device or self.device, every)

    def button_label(self, button, device=None):
        """Nome de um botão do R36S no dispositivo em uso: o b é "B" no R36S,
        "Enter" no teclado e "A" no Xbox (para textos de ajuda com on_button)."""
        return button_label(button, device or self.device)

    def held(self, action):
        """A ação está apertada agora?"""
        return self.action_map.is_held(action)

    def on_key(self, fn):
        """fn(tecla, estado, ms): toda tecla do PC, com o nome das ações
        ("space", "a", "f1"); estado "down", "up" ou "repeat" (do sistema)."""
        self._handlers["key"].append(fn)
        return fn

    def on_text(self, fn):
        """fn(texto): texto digitado no PC, com acentos (para nomes, chat...)."""
        self._handlers["text"].append(fn)
        return fn

    def on_mouse(self, fn):
        """fn(tipo, x, y, valor): tipo "move", "down", "up" (valor = "left",
        "middle", "right") ou "wheel" (valor = cliques da roda). x e y na área
        de 640x480."""
        self._handlers["mouse"].append(fn)
        return fn

    def on_focus(self, fn):
        """fn(com_foco): a janela do PC ganhou ou perdeu o foco."""
        self._handlers["focus"].append(fn)
        return fn

    def on_device(self, fn):
        """fn(evento, família, nome): controle "added" ou "removed". Sem esta
        função, o jogo fala "Controle conectado" e "Controle desconectado"."""
        self._handlers["device"].append(fn)
        return fn

    def rumble(self, strength=0.5, seconds=0.2):
        """Vibra o controle do PC (o R36S não vibra). Devolve se vibrou."""
        return bool(self._desktop and self._desktop.rumble(strength, seconds))

    def fullscreen(self, on=None):
        """Tela cheia no PC; on=None alterna (o jogador também tem F11)."""
        if self._gfx is not None:
            self._gfx.toggle_fullscreen(on)

    def on_start(self, fn):
        self._handlers["start"].append(fn)
        return fn

    def on_quit(self, fn):
        """fn() ao sair: hora de salvar."""
        self._handlers["quit"].append(fn)
        return fn

    # --- serviços ------------------------------------------------------
    def say(self, text, queue=False, on_done=None):
        speech_history.record(text)  # Fn + L1/R1 no console
        self._last_said = text        # legenda na janela do PC
        self.speech.say(text, queue=queue, on_done=on_done)

    def hush(self):
        self.speech.hush()

    def after(self, seconds, fn):
        """Chama fn() daqui a alguns segundos."""
        self._timers.append((time.monotonic() + seconds, fn))

    def ms(self):
        """Milissegundos desde o início do jogo, na mesma escala dos botões."""
        return int((time.time() - self.started_at) * 1000)

    def quit(self):
        self._running = False

    def push_focus(self, handler):
        self._focus.append(handler)

    def pop_focus(self, handler):
        if handler in self._focus:
            self._focus.remove(handler)

    # --- laço ----------------------------------------------------------
    def _dispatch_button(self, button, state, ms):
        if self._focus:
            self._focus[-1].handle_button(button, state, ms)
            return
        for fn in list(self._handlers["button"]):
            fn(button, state, ms)

    def _dispatch_action(self, action, state, ms):
        if self._focus:     # um menu aberto fica com a entrada
            return
        for fn in list(self._handlers["action"]):
            fn(action, state, ms)

    def _schedule_repeat(self, key, state):
        if self.repeat:
            if state == DOWN:
                self._repeat_at[key] = time.monotonic() + REPEAT_DELAY
            else:
                self._repeat_at.pop(key, None)

    def _actions(self, events):
        for _, action, state, ms in events:
            self._schedule_repeat(("action", action), state)
            self._dispatch_action(action, state, ms)

    def _dispatch(self, event):
        kind = event[0]
        if kind == "button":
            _, button, state, ms = event
            self._schedule_repeat(("button", button), state)
            self._dispatch_button(button, state, ms)
            if self._actions_from_buttons and state in (DOWN, UP):
                self._actions(self.action_map.feed("r36s", button, state, ms))
        elif kind == "axis" and self.axes:
            _, axis, value, ms = event
            for fn in list(self._handlers["axis"]):
                fn(axis, value, ms)
        elif kind == "control":    # tecla, botão do controle ou do mouse, no PC
            _, source, control, state, ms = event
            if source == "key":
                self.device = KEYBOARD
            self._actions(self.action_map.feed(source, control, state, ms))
        elif kind == "pad":
            self.device = event[1]
        elif kind in ("key", "text", "mouse", "focus"):
            for fn in list(self._handlers[kind]):
                fn(*event[1:])
        elif kind == "device":
            _, what, family, name, initial = event
            if self._handlers["device"]:
                for fn in list(self._handlers["device"]):
                    fn(what, family, name)
            elif not initial:
                self.say("Controle conectado" if what == "added" else "Controle desconectado",
                         queue=True)
        elif kind == "quit":
            self._running = False

    def _tick_repeat(self, now):
        if self.input.fn_held:
            return
        for key, when in list(self._repeat_at.items()):
            if now >= when:
                self._repeat_at[key] = when + REPEAT_INTERVAL
                kind, name = key
                if kind == "action":
                    self._dispatch_action(name, REPEAT, self.ms())
                else:
                    self._dispatch_button(name, REPEAT, self.ms())

    def _tick_timers(self, now):
        due = [t for t in self._timers if t[0] <= now]
        if due:
            self._timers = [t for t in self._timers if t[0] > now]
            for _, fn in sorted(due, key=lambda t: t[0]):
                fn()

    def run(self):
        reader = pc = None
        if self.pc:
            if self.gfx.available:   # no PC sempre há janela: é dela que vem o teclado
                from .desktop import DesktopInput
                self._desktop = DesktopInput(self._gfx, self.input, self.ms)
                self._actions_from_buttons = False
                print("[r36s_a11y] PC: " + self._desktop.describe(), file=sys.stderr)
            elif sys.platform == "win32":
                print("[r36s_a11y] sem a SDL2.dll: modo antigo, só com as teclas padrão "
                      "(rode tools/preparar_windows.py)", file=sys.stderr)
                from .pc import WindowsInput
                pc = WindowsInput(self.input, self.ms, lambda: self._gfx)
                print("[r36s_a11y] PC: " + pc.describe(), file=sys.stderr)
        elif sys.platform.startswith("linux"):
            reader = GamepadReader(self.input, self.started_at)
            if not reader.files:
                print("[r36s_a11y] nenhum controle encontrado em /dev/input", file=sys.stderr)
        elif sys.platform == "win32":
            from .pc import WindowsInput
            pc = WindowsInput(self.input, self.ms, lambda: self._gfx)
            print("[r36s_a11y] PC: " + pc.describe(), file=sys.stderr)

        def stop(signum, frame):
            self._running = False
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        if self._handlers["draw"]:
            self.gfx  # abre a tela antes do primeiro quadro
        self._running = True
        for fn in list(self._handlers["start"]):
            fn()

        step = 1.0 / self.fps
        last = time.monotonic()
        try:
            while self._running:
                fds = reader.fileno_list() if reader else []
                timeout = max(0.0, last + step - time.monotonic())
                if pc or self._desktop:
                    timeout = min(timeout, PC_POLL)
                events = pc.poll(time.monotonic()) if pc else []
                if self._desktop:
                    events += self._desktop.poll()
                for event in events:
                    self._dispatch(event)
                try:
                    ready = select.select(fds, [], [], timeout)[0] if fds else []
                    if not fds:
                        time.sleep(timeout)
                except InterruptedError:
                    ready = []
                for fd in ready:
                    for event in reader.read(fd):
                        self._dispatch(event)
                for fn, done in self.speech.poll():
                    fn(done)
                now = time.monotonic()
                self._tick_repeat(now)
                self._tick_timers(now)
                if now - last >= step:
                    dt, last = now - last, now
                    self.sound.update(dt)
                    for fn in list(self._handlers["update"]):
                        fn(dt)
                    draw = list(self._handlers["draw"]) or ([self._draw_caption] if self.pc else [])
                    if draw and self._gfx is not None and self._gfx.available:
                        self._gfx.begin()
                        for fn in draw:
                            fn(self._gfx)
                        self._gfx.end()
        finally:
            for fn in list(self._handlers["quit"]):
                try:
                    fn()
                except Exception as exc:  # salvar não pode impedir a saída
                    print("[r36s_a11y] erro ao sair: %s" % exc, file=sys.stderr)
            if reader:
                reader.close()
            if self._desktop:
                self._desktop.close()
            self.speech.close()
            self.sound.close()
            if self._gfx is not None:
                self._gfx.close()

    def _draw_caption(self, gfx):
        """Tela do PC para jogos só de áudio: o nome do jogo e a última fala,
        como legenda (ajuda quem enxerga pouco, quem não ouve e quem assiste)."""
        if self._caption_fonts is None:
            self._caption_fonts = (gfx.font(size=30), gfx.font(size=26))
        title_font, text_font = self._caption_fonts
        gfx.clear("#101820")
        gfx.text(self.name, WIDTH_HALF, 24, font=title_font, color="#8fb8ff", align="center")
        lines = wrap(self._last_said, lambda t: gfx.measure(t, text_font)[0], 580)
        line_h = max(1, gfx.measure("Ág", text_font)[1])
        y = 240 - len(lines) * line_h // 2
        for line in lines[-12:]:
            gfx.text(line, WIDTH_HALF, y, font=text_font, color="#ffffff", align="center")
            y += line_h


WIDTH_HALF = 320


def wrap(text, width_of, max_width):
    """Quebra o texto em linhas que caibam em max_width."""
    lines, line = [], ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if line and width_of(candidate) > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines
