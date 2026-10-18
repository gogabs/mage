"""Meu jogo, feito com o r36s_a11y.

As ações (bip, repetir, sair) e as teclas e botões de cada uma ficam no
game.json. Rode com:  python mage.py run  (na pasta da engine) ou  python main.py
"""
import r36s_a11y as a11y

game = a11y.Game()
bip = game.sound.load("bip", "sounds/bip.wav")


def instrucoes():
    return "%s. Aperte %s para tocar o bip, %s para repetir e %s para sair." % (
        game.name, game.label("bip"), game.label("repetir"), game.label("sair"))


@game.on_start
def comecar():
    game.say(instrucoes())


@game.on_action
def acao(nome, estado, ms):
    if estado != "down":
        return
    if nome == "bip":
        bip.play()
    elif nome == "repetir":
        game.say(instrucoes())
    elif nome == "sair":
        game.quit()


game.run()
