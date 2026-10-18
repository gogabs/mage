"""Nomes dos botões do R36S e convenções do contrato."""

# Código evdev -> nome padrão do contrato.
BUTTON_CODES = {
    0x130: "b",       # BTN_SOUTH, botão de baixo
    0x131: "a",       # BTN_EAST, botão da direita
    0x133: "x",       # BTN_NORTH, botão de cima
    0x134: "y",       # BTN_WEST, botão da esquerda
    0x136: "l1",
    0x137: "r1",
    0x138: "l2",
    0x139: "r2",
    0x220: "up",
    0x221: "down",
    0x222: "left",
    0x223: "right",
    0x2C0: "select",  # BTN_TRIGGER_HAPPY1
    0x2C1: "start",   # BTN_TRIGGER_HAPPY2
    0x2C2: "l3",      # BTN_TRIGGER_HAPPY3
    0x2C3: "r3",      # BTN_TRIGGER_HAPPY4
}

# Fn é do sistema (a11yd): nunca chega ao jogo, nem o que for apertado com ele.
FN_CODE = 0x2C4      # BTN_TRIGGER_HAPPY5

# Código evdev de eixo -> nome padrão.
AXIS_CODES = {
    0x00: "lx",  # ABS_X
    0x01: "ly",  # ABS_Y
    0x03: "rx",  # ABS_RX
    0x04: "ry",  # ABS_RY
}

BUTTONS = tuple(BUTTON_CODES.values())

DOWN, UP, REPEAT = "down", "up", "repeat"


def is_confirm(button):
    """B (de baixo) confirma."""
    return button == "b"


def is_back(button):
    """A (da direita) volta."""
    return button == "a"
