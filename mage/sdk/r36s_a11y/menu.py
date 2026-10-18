"""Menu falado pronto, seguindo as regras de acessibilidade do contrato."""
from .buttons import DOWN, REPEAT, is_back, is_confirm


class Menu:
    """Menu vertical falado.

        menu = Menu(game, "Menu principal", ["Jogar", "Instruções", "Sair"],
                    on_select=escolheu, on_back=voltou)
        menu.open()

    on_select(índice, texto) é chamado ao confirmar. on_back() ao apertar
    Voltar; sem on_back, Voltar fecha o menu. Cima/Baixo navegam (dando a
    volta), Select repete o item atual.
    """

    HELP = "Cima e baixo escolhem. B confirma. A volta."

    def __init__(self, game, title, items, on_select, on_back=None,
                 wrap=True, sounds=None):
        self.game = game
        self.title = title
        self.items = list(items)
        self.on_select = on_select
        self.on_back = on_back
        self.wrap = wrap
        # sons opcionais: {"move": Sound, "select": Sound, "edge": Sound}
        self.sounds = sounds or {}
        self.index = 0
        self.is_open = False

    def open(self, index=0, announce_help=True):
        self.index = index
        self.is_open = True
        self.game.push_focus(self)
        text = "%s. %s" % (self.title, self._item_text())
        if announce_help:
            text += ". " + self.help_text()
        self.game.say(text)

    def help_text(self):
        """Como usar o menu, com os nomes do dispositivo em uso no PC."""
        device = getattr(self.game, "device", "r36s")
        label = getattr(self.game, "button_label", None)
        if device == "r36s" or label is None or type(self).HELP != Menu.HELP:
            return self.HELP
        moves = "As setas para cima e para baixo" if device == "keyboard" else "O direcional"
        return "%s escolhem. %s confirma. %s volta." % (moves, label("b"), label("a"))

    def close(self):
        self.is_open = False
        self.game.pop_focus(self)

    def _item_text(self):
        return "%s, %d de %d" % (self.items[self.index], self.index + 1, len(self.items))

    def _play(self, name):
        sound = self.sounds.get(name)
        if sound is not None:
            sound.play()

    def _move(self, delta):
        new = self.index + delta
        if self.wrap:
            new %= len(self.items)
        elif not 0 <= new < len(self.items):
            self._play("edge")
            self.game.say(self._item_text())
            return
        self.index = new
        self._play("move")
        self.game.say(self._item_text())

    def handle_button(self, button, state, ms):
        if state not in (DOWN, REPEAT):
            return
        if button == "down":
            self._move(1)
        elif button == "up":
            self._move(-1)
        elif state != DOWN:
            return
        elif is_confirm(button):
            self._play("select")
            self.on_select(self.index, self.items[self.index])
        elif is_back(button):
            if self.on_back is not None:
                self.on_back()
            else:
                self.close()
        elif button == "select":
            self.game.say(self._item_text())
