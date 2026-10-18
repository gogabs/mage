"""Linha de comando: new, run, check, update e export."""
import argparse
import os
import subprocess
import sys

from . import downloads, export, project


def cmd_new(args):
    project.create(args.folder, name=args.name, author=args.author)
    print("Para jogar: python %s run %s" % (_self(), args.folder))
    return 0


def cmd_run(args):
    path = os.path.abspath(args.folder)
    manifest = project.load(path)
    if manifest["runtime"] != "python3":
        raise project.ProjectError("o run ainda é só para jogos em Python")
    if sys.platform == "win32":
        dll = os.path.join(path, "r36s_a11y", "dll")
        if not downloads.has_dlls(dll):
            print("Primeira vez no Windows: baixando as DLLs do SDK para o jogo.")
            downloads.install_dlls(dll)
    env = dict(os.environ, A11Y_GAME_DIR=path)
    if args.pc:
        env["A11Y_PLATAFORMA"] = "pc"
    return subprocess.call([sys.executable, manifest["exec"]], cwd=path, env=env)


def cmd_check(args):
    path = os.path.abspath(args.folder)
    manifest, problems = project.check(path)
    if not problems:
        try:
            files = project.package_files(path, manifest)
        except project.ProjectError as e:
            problems = str(e).splitlines()
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
    return p


def main(argv):
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except project.ProjectError as e:
        print("Não deu: %s" % e, file=sys.stderr)
        return 2
