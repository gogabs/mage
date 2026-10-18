"""Ações: o jogo pede "pular", e cada dispositivo diz qual tecla ou botão pula.

    game.actions({
        "pular":  {"key": "space", "r36s": "b"},            # no controle: pelo lugar do b
        "atirar": {"key": ["z", "x"], "r36s": "y", "pad": "x"},
    })

Origens de uma ligação:
  - "r36s": botão do R36S (up down left right a b x y l1 r1 l2 r2 l3 r3 start select);
  - "key": tecla do teclado ("space", "return", "a", "f1", "up", "lshift"...);
  - "pad": botão do controle, pelo nome do Xbox (a b x y back start leftshoulder
    rightshoulder lefttrigger righttrigger leftstick rightstick dpup dpdown
    dpleft dpright); o "a" é sempre o de baixo, seja qual for o controle;
  - "mouse": "left", "middle" ou "right".

Sem "key" ou "pad", a ação usa as teclas e o botão que correspondem ao seu
botão do R36S (o b do R36S é Enter e Z no teclado e o botão de baixo no
controle). label() devolve o nome que o jogador vê no dispositivo em uso.
"""

R36S_BUTTONS = ("up", "down", "left", "right", "a", "b", "x", "y", "l1", "r1",
                "l2", "r2", "l3", "r3", "start", "select")

PAD_BUTTONS = ("a", "b", "x", "y", "back", "guide", "start", "leftstick", "rightstick",
               "leftshoulder", "rightshoulder", "dpup", "dpdown", "dpleft", "dpright",
               "lefttrigger", "righttrigger")

MOUSE_BUTTONS = ("left", "middle", "right")

# Botão do R36S -> botão do controle no mesmo lugar.
R36S_TO_PAD = {
    "b": "a", "a": "b", "x": "y", "y": "x",
    "l1": "leftshoulder", "r1": "rightshoulder", "l2": "lefttrigger", "r2": "righttrigger",
    "l3": "leftstick", "r3": "rightstick", "start": "start", "select": "back",
    "up": "dpup", "down": "dpdown", "left": "dpleft", "right": "dpright",
}
PAD_TO_R36S = {v: k for k, v in R36S_TO_PAD.items()}

# Botão do R36S -> teclas padrão no PC (as mesmas do modo antigo).
R36S_TO_KEYS = {
    "up": ["up"], "down": ["down"], "left": ["left"], "right": ["right"],
    "b": ["return", "z", "kp enter"], "a": ["backspace", "x"], "x": ["s"], "y": ["a"],
    "l1": ["q"], "r1": ["w"], "l2": ["1"], "r2": ["2"], "l3": ["3"], "r3": ["4"],
    "start": ["escape"], "select": ["tab"],
}
KEY_TO_R36S = {k: b for b, keys in R36S_TO_KEYS.items() for k in keys}

PAD_ALIASES = {"lb": "leftshoulder", "rb": "rightshoulder", "lt": "lefttrigger",
               "rt": "righttrigger", "ls": "leftstick", "rs": "rightstick", "view": "back",
               "select": "back", "menu": "start", "up": "dpup", "down": "dpdown",
               "left": "dpleft", "right": "dpright"}
KEY_ALIASES = {"enter": "return", "esc": "escape", "espaço": "space", "espaco": "space",
               "kp_enter": "kp enter", "seta para cima": "up", "seta para baixo": "down",
               "seta para a esquerda": "left", "seta para a direita": "right"}
# Teclas dos dois lados: "shift" liga o esquerdo e o direito.
KEY_BOTH_SIDES = {"shift": ["lshift", "rshift"], "alt": ["lalt", "ralt"],
                  "ctrl": ["lctrl", "rctrl"]}

KEYBOARD, R36S = "keyboard", "r36s"
XBOX, PLAYSTATION, NINTENDO = "xbox", "playstation", "nintendo"

KEY_LABELS = {
    "space": "espaço", "return": "Enter", "kp enter": "Enter do teclado numérico",
    "escape": "Esc", "backspace": "Backspace", "tab": "Tab", "delete": "Delete",
    "insert": "Insert", "home": "Home", "end": "End", "pageup": "Page Up",
    "pagedown": "Page Down", "up": "seta para cima", "down": "seta para baixo",
    "left": "seta para a esquerda", "right": "seta para a direita",
    "lshift": "Shift esquerdo", "rshift": "Shift direito", "lalt": "Alt esquerdo",
    "ralt": "Alt direito", "lctrl": "Ctrl esquerdo", "rctrl": "Ctrl direito",
    "capslock": "Caps Lock", "numlock": "Num Lock", "menu": "tecla de menu",
}
R36S_LABELS = {
    "up": "direcional para cima", "down": "direcional para baixo",
    "left": "direcional para a esquerda", "right": "direcional para a direita",
    "start": "Start", "select": "Select",
}
_DPAD_LABELS = {"dpup": "direcional para cima", "dpdown": "direcional para baixo",
                "dpleft": "direcional para a esquerda", "dpright": "direcional para a direita"}
PAD_LABELS = {
    XBOX: dict(_DPAD_LABELS, a="A", b="B", x="X", y="Y", back="View", start="Menu",
               guide="botão Xbox", leftshoulder="LB", rightshoulder="RB",
               lefttrigger="LT", righttrigger="RT", leftstick="analógico esquerdo apertado",
               rightstick="analógico direito apertado"),
    PLAYSTATION: dict(_DPAD_LABELS, a="xis", b="bolinha", x="quadrado", y="triângulo",
                      back="Share", start="Options", guide="botão PS",
                      leftshoulder="L1", rightshoulder="R1", lefttrigger="L2",
                      righttrigger="R2", leftstick="L3", rightstick="R3"),
    # Botões pelo lugar: o de baixo do controle da Nintendo se chama B.
    NINTENDO: dict(_DPAD_LABELS, a="B", b="A", x="Y", y="X", back="menos", start="mais",
                   guide="Home", leftshoulder="L", rightshoulder="R", lefttrigger="ZL",
                   righttrigger="ZR", leftstick="analógico esquerdo apertado",
                   rightstick="analógico direito apertado"),
}
MOUSE_LABELS = {"left": "botão esquerdo do mouse", "middle": "botão do meio do mouse",
                "right": "botão direito do mouse"}

DOWN, UP = "down", "up"


def key_label(key):
    """Nome falado de uma tecla: "espaço", "Enter", "Z", "F1"."""
    if key in KEY_LABELS:
        return KEY_LABELS[key]
    if key.startswith("kp") and len(key) > 2:
        return "%s do teclado numérico" % key[2:].strip()
    return key.upper() if len(key) <= 3 else key


def _as_list(value):
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def _norm_key(key):
    key = key.strip().lower()
    key = KEY_ALIASES.get(key, key)
    return KEY_BOTH_SIDES.get(key, [key])


class Actions:
    """O mapa de ações de um jogo e o estado das ações apertadas."""

    def __init__(self):
        self.bindings = {}   # ação -> {"r36s": [...], "key": [...], "pad": [...], "mouse": [...]}
        self.held = {}       # ação -> {(origem, controle), ...}

    def define(self, mapping):
        """Acrescenta ou troca ações; veja o começo deste arquivo."""
        for name, spec in mapping.items():
            if isinstance(spec, str):          # "pular": "b" é o mesmo que {"r36s": "b"}
                spec = {"r36s": spec}
            unknown = set(spec) - {"r36s", "key", "pad", "mouse"}
            if unknown:
                raise ValueError("ação %r: origem desconhecida %s (use r36s, key, pad ou mouse)"
                                 % (name, ", ".join(sorted(unknown))))
            r36s = [b.lower() for b in _as_list(spec.get("r36s"))]
            for b in r36s:
                if b not in R36S_BUTTONS:
                    raise ValueError("ação %r: %r não é um botão do R36S" % (name, b))
            keys = []
            for k in _as_list(spec.get("key")):
                for key in _norm_key(k):
                    if key in ("lctrl", "rctrl"):
                        raise ValueError("ação %r: Ctrl é o Fn no PC e não chega ao jogo" % name)
                    keys.append(key)
            pads = []
            for p in _as_list(spec.get("pad")):
                p = PAD_ALIASES.get(p.lower(), p.lower())
                if p not in PAD_BUTTONS or p == "guide":
                    raise ValueError("ação %r: %r não é um botão de controle" % (name, p))
                pads.append(p)
            mice = [m.lower() for m in _as_list(spec.get("mouse"))]
            for m in mice:
                if m not in MOUSE_BUTTONS:
                    raise ValueError("ação %r: %r não é um botão do mouse" % (name, m))
            self.bindings[name] = {
                "r36s": r36s,
                "key": keys if "key" in spec else [k for b in r36s for k in R36S_TO_KEYS[b]],
                "pad": pads if "pad" in spec else [R36S_TO_PAD[b] for b in r36s],
                "mouse": mice,
            }
            self.held.setdefault(name, set())

    def __contains__(self, name):
        return name in self.bindings

    def names(self):
        return list(self.bindings)

    def resolve(self, source, control):
        """Ações ligadas a um controle de uma origem."""
        return [name for name, b in self.bindings.items() if control in b[source]]

    def feed(self, source, control, state, ms):
        """Um controle apertado ou solto -> [("action", ação, estado, ms)].

        Uma ação ligada a duas teclas só desce na primeira e só sobe quando
        as duas forem soltas.
        """
        out = []
        for name in self.resolve(source, control):
            held = self.held[name]
            if state == DOWN:
                if not held:
                    out.append(("action", name, DOWN, ms))
                held.add((source, control))
            elif (source, control) in held:
                held.discard((source, control))
                if not held:
                    out.append(("action", name, UP, ms))
        return out

    def release_all(self, ms):
        """Solta tudo (a janela perdeu o foco, por exemplo)."""
        out = []
        for name, held in self.held.items():
            if held:
                held.clear()
                out.append(("action", name, UP, ms))
        return out

    def is_held(self, name):
        return bool(self.held.get(name))

    def label(self, name, device=KEYBOARD, every=False):
        """Nome do que aperta a ação no dispositivo, para falar ao jogador.

        device: "keyboard", "r36s", "xbox", "playstation" ou "nintendo".
        every=True junta todas as opções com "ou".
        """
        b = self.bindings[name]
        if device == R36S:
            labels = [R36S_LABELS.get(x, x.upper()) for x in b["r36s"]]
        elif device in PAD_LABELS:
            labels = [PAD_LABELS[device][x] for x in b["pad"]]
        else:
            labels = [key_label(k) for k in b["key"]] + [MOUSE_LABELS[m] for m in b["mouse"]]
        if not labels:
            return ""
        return " ou ".join(labels) if every else labels[0]


def button_label(button, device):
    """Nome do botão do R36S (ou do que fica no lugar dele) no dispositivo:
    o b é "B" no R36S, "Enter" no teclado e "A" no Xbox."""
    if device in PAD_LABELS:
        return PAD_LABELS[device][R36S_TO_PAD[button]]
    if device == R36S:
        return R36S_LABELS.get(button, button.upper())
    return key_label(R36S_TO_KEYS[button][0])
