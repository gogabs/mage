"""Linha de comando: new, run, check, update, export e editor."""
import argparse
import os
import sys

from . import export, project


def cmd_new(args):
    project.create(args.folder, name=args.name, author=args.author)
    print("Para jogar: python %s run %s" % (_self(), args.folder))
    return 0


def cmd_run(args):
    return project.start_game(args.folder, pc=args.pc).wait()


def cmd_check(args):
    manifest, problems, files = project.check_all(os.path.abspath(args.folder))
    if problems:
        for p in problems:
            print("- " + p)
        return 1
    print("Tudo certo: %s %s, %d arquivos para exportar." % (
        manifest["name"], manifest["version"], len(files)))
    return 0


def cmd_update(args):
    project.update_sdk(os.path.abspath(args.folder))
    return 0


def cmd_export(args):
    targets = list(export.TARGETS) if args.to == "all" else [args.to]
    for target in targets:
        export.TARGETS[target](args.folder)
    return 0


def cmd_editor(args):
    from . import editor
    return editor.serve(args.folder, port=args.port, browser=not args.no_browser)


def _self():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mage.py")


def parser():
    p = argparse.ArgumentParser(
        prog="mage.py", description="Cria, roda e exporta jogos feitos com o r36s_a11y.")
    sub = p.add_subparsers(dest="command", metavar="command")
    sub.required = True

    s = sub.add_parser("new", help="cria um projeto a partir do modelo")
    s.add_argument("folder", help="pasta do jogo novo (o nome dela vira o id)")
    s.add_argument("--name", help="nome falado do jogo; padrão: o da pasta")
    s.add_argument("--author", help="quem fez o jogo")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("run", help="abre o jogo")
    s.add_argument("folder", nargs="?", default=".", help="pasta do jogo; padrão: a atual")
    s.add_argument("--pc", action="store_true",
                   help="no Linux, abre a janela do PC em vez de ler o controle do R36S")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("check", help="confere o game.json e os nomes dos arquivos")
    s.add_argument("folder", nargs="?", default=".", help="pasta do jogo; padrão: a atual")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("update", help="troca a cópia do r36s_a11y do jogo pela que vem com a engine")
    s.add_argument("folder", nargs="?", default=".", help="pasta do jogo; padrão: a atual")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("export", help="gera o jogo pronto para o R36S e o Windows em dist/")
    s.add_argument("folder", nargs="?", default=".", help="pasta do jogo; padrão: a atual")
    s.add_argument("--to", choices=["all"] + list(export.TARGETS), default="all")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("editor", help="abre o editor no navegador")
    s.add_argument("folder", nargs="?", help="pasta do jogo; sem ela, abre a tela inicial")
    s.add_argument("--port", type=int, default=0, help="porta local; padrão: uma livre")
    s.add_argument("--no-browser", action="store_true", help="não abre o navegador sozinho")
    s.set_defaults(fn=cmd_editor)
    return p


def main(argv):
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except project.ProjectError as e:
        print("Não deu: %s" % e, file=sys.stderr)
        return 2
