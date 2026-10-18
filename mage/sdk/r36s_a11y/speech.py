"""Fala pelo Speech Dispatcher (protocolo SSIP direto no socket Unix).

Regras do contrato:
  - usa a voz do usuário (seção "voice" de /roms/a11y/config.json), nunca
    valores próprios;
  - fala interrompe a anterior por padrão; fila é opcional.

Sem Speech Dispatcher (no PC, por exemplo), a fala vai para o terminal.
"""
import os
import socket
import sys

CONFIG = "/roms/a11y/config.json"
LEGACY_VOICE_CONF = "/opt/a11y/etc/voz.conf"  # antes do config.json


def _voice_conf():
    path = os.environ.get("A11Y_VOZ_CONF")
    if path:
        return path
    return CONFIG if os.path.exists(CONFIG) else LEGACY_VOICE_CONF


def _conf_line(line):
    """(chave, valor) de uma linha "KEY": valor, do JSON ou KEY=valor."""
    line = line.strip().rstrip(",")
    if line.startswith('"') and '":' in line:
        key, _, val = line[1:].partition('":')
    else:
        key, _, val = line.partition("=")
    return key.strip(), val.strip().strip("'\"")


def _socket_path():
    address = os.environ.get("SPEECHD_ADDRESS", "")
    if address.startswith("unix_socket:"):
        return address[len("unix_socket:"):]
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    return os.path.join(runtime, "speech-dispatcher", "speechd.sock")


def _user_voice():
    """Lê a voz do usuário: RATE, PITCH e VOLUME (0 a 100, convertidos para
    -100..100 do SSIP) e VOICE_MODULE / VOICE (texto, pode vir entre aspas)."""
    values = {}
    try:
        with open(_voice_conf(), encoding="utf-8") as f:
            for line in f:
                key, val = _conf_line(line)
                if key in ("VOICE_MODULE", "VOICE"):
                    if val:
                        values[key] = val
                elif key in ("RATE", "PITCH", "VOLUME"):
                    try:
                        values[key] = max(0, min(100, int(val))) * 2 - 100
                    except ValueError:
                        pass
    except OSError:
        pass
    return values


def escape_text(text):
    """Formata o texto para o comando SPEAK do SSIP."""
    lines = []
    for line in text.replace("\r", "").split("\n"):
        # Linha começando com "." precisa ser dobrada no SSIP.
        lines.append("." + line if line.startswith(".") else line)
    return "\r\n".join(lines) + "\r\n.\r\n"


class Speech:
    def __init__(self, client="jogo", language="pt-BR"):
        self.client = client
        self.language = language
        self.sock = None
        self.buf = b""
        self.callbacks = {}   # id da mensagem -> função(done)
        self.events = []      # (função, done) prontos para chamar no laço
        self.available = True
        self.voice_values = None

    # --- conexão -------------------------------------------------------
    def _connect(self):
        if not hasattr(socket, "AF_UNIX"):
            raise OSError("sem socket Unix")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(_socket_path())
        self.sock, self.buf = s, b""
        user = os.environ.get("USER", "ark")
        self._cmd("SET SELF CLIENT_NAME %s:a11y:%s" % (user, self.client))
        voice = _user_voice()
        self._apply_voice(voice)
        self._cmd("SET SELF NOTIFICATION END on")
        self._cmd("SET SELF NOTIFICATION CANCEL on")

    def _apply_voice(self, voice):
        applied = dict(voice)
        module = applied.get("VOICE_MODULE")
        base = {"pt-BR": "pt-br", "en-US": "en-us", "es-ES": "es", "fr-FR": "fr"}.get(self.language, self.language.lower())
        if module == "rhvoice" and not self.language.lower().startswith("pt"):
            applied["VOICE_MODULE"], applied["VOICE"] = "espeak-ng", base
        elif module == "espeak-ng":
            configured = applied.get("VOICE", "")
            variant = "+" + configured.split("+", 1)[1] if "+" in configured else ""
            applied["VOICE"] = base + variant
        # módulo antes do idioma, e voz depois: trocar o idioma pode trocar a voz
        if "VOICE_MODULE" in applied:
            self._cmd("SET SELF OUTPUT_MODULE %s" % applied["VOICE_MODULE"])
        self._cmd("SET SELF LANGUAGE %s" % self.language)
        if "VOICE" in applied:
            self._cmd("SET SELF SYNTHESIS_VOICE %s" % applied["VOICE"])
        for key in ("RATE", "PITCH", "VOLUME"):
            if key in voice:
                self._cmd("SET SELF %s %d" % (key, voice[key]))
        self._cmd("SET SELF SSML_MODE off")
        self.voice_values = voice

    def _ensure(self):
        if self.sock is None and self.available:
            try:
                self._connect()
            except OSError:
                self.close()
        return self.sock is not None

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def fileno(self):
        return self.sock.fileno() if self.sock is not None else None

    # --- leitura de respostas e eventos --------------------------------
    def _readline(self):
        while b"\r\n" not in self.buf:
            data = self.sock.recv(4096)
            if not data:
                raise ConnectionError("speech-dispatcher fechou a conexão")
            self.buf += data
        line, _, self.buf = self.buf.partition(b"\r\n")
        return line.decode("utf-8", "replace")

    def _read_block(self):
        """Lê um bloco de linhas "NNN-..." terminado por "NNN ..."."""
        lines = []
        while True:
            line = self._readline()
            lines.append(line)
            if len(line) >= 4 and line[3] == " ":
                return lines

    def _handle_event(self, lines):
        # 7xx-msg_id / 7xx-client_id / 7xx END|CANCEL
        code = lines[-1][:3]
        msg_id = lines[0][4:] if len(lines) >= 3 else None
        fn = self.callbacks.pop(msg_id, None)
        if fn is not None:
            self.events.append((fn, code == "702"))   # 702 = END, 703 = CANCEL

    def _reply(self):
        while True:
            lines = self._read_block()
            if lines[-1].startswith("7"):
                self._handle_event(lines)
                continue
            return lines

    def _cmd(self, command):
        self.sock.sendall(command.encode("utf-8") + b"\r\n")
        return self._reply()

    def poll(self):
        """Lê eventos pendentes sem bloquear e devolve os callbacks prontos."""
        if self.sock is not None:
            self.sock.setblocking(False)
            try:
                while True:
                    data = self.sock.recv(4096)
                    if not data:
                        self.close()
                        break
                    self.buf += data
            except (BlockingIOError, InterruptedError):
                pass
            except OSError:
                self.close()
            finally:
                if self.sock is not None:
                    self.sock.settimeout(5)
            try:
                while b"\r\n" in self.buf and self._block_complete():
                    lines = self._read_block()
                    if lines[-1].startswith("7"):
                        self._handle_event(lines)
            except (OSError, ConnectionError):
                self.close()
        ready, self.events = self.events, []
        return ready

    def _block_complete(self):
        for line in self.buf.split(b"\r\n")[:-1]:
            if len(line) >= 4 and line[3:4] == b" ":
                return True
        return False

    # --- API -----------------------------------------------------------
    def set_language(self, language):
        if not language or any(c in language for c in "\r\n"):
            raise ValueError("Invalid speech language")
        if language != self.language:
            self.language = language
            self.voice_values = None

    def say(self, text, queue=False, on_done=None):
        """Fala o texto. on_done(done) é chamado ao terminar (done=False se cortada)."""
        for attempt in (1, 2):
            if not self._ensure():
                print("[fala] " + text, file=sys.stderr)
                if on_done is not None:
                    self.events.append((on_done, True))
                return
            try:
                voice = _user_voice()
                if voice != self.voice_values:
                    self._apply_voice(voice)
                if not queue:
                    self._cmd("STOP SELF")
                self._cmd("SPEAK")
                self.sock.sendall(escape_text(text).encode("utf-8"))
                lines = self._reply()
                if on_done is not None:
                    # 225-<id da mensagem> / 225 OK MESSAGE QUEUED
                    msg_id = lines[0][4:] if len(lines) > 1 else None
                    self.callbacks[msg_id] = on_done
                return
            except (OSError, ConnectionError):
                self.close()

    def hush(self):
        if self._ensure():
            try:
                self._cmd("STOP SELF")
            except (OSError, ConnectionError):
                self.close()
