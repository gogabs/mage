"""Exporta um projeto para o R36S (pasta para o cartão) e para o Windows (.exe).

R36S:    dist/<id>-r36s.zip, com a pasta <id>/ para copiar em a11y/games no cartão.
Windows: dist/<id>-windows.zip, com a pasta <Nome>/ e o <Nome>.exe dentro.

O executável do Windows é o pythonw.exe oficial renomeado, com o Python
inteiro ao lado. O python3XX._pth deixa esse Python isolado (não usa o
Python instalado no computador) e importa o sitecustomize.py, que abre o
jogo da pasta jogo/. Nada é compilado, então a exportação para Windows
funciona a partir de qualquer sistema.
"""
import os
import re
import shutil
import zipfile

from . import assets, downloads, project

# Partes do Python que um jogo não usa: ficam fora do .exe exportado.
PYTHON_SKIP = ("Lib/site-packages/", "Lib/test/", "Lib/idlelib/", "Lib/tkinter/",
               "Lib/turtledemo/", "Lib/ensurepip/", "Lib/venv/", "Lib/lib2to3/",
               "Lib/pydoc_data/", "Lib/__phello__/", "include/", "libs/",
               "python.exe", "Lib/turtle.py")

LAUNCHER = '''"""Abre o jogo quando o executável começa. Gerado pelo MAGE ("mage.py export").

Este Python é só do jogo: o python3XX._pth ao lado o isola do Python
instalado no computador e faz ele importar este arquivo ao começar.
"""
import os
import sys

GAME_ID = %(id)r
EXEC = %(exec)r


def _message(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, %(name)r, 0x10)
    except Exception:
        pass


def _main():
    import runpy
    import traceback
    here = os.path.dirname(os.path.abspath(__file__))  # ao lado do .exe
    game_dir = os.path.join(here, "jogo")
    save_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                            "r36s-a11y", GAME_ID)
    os.makedirs(save_dir, exist_ok=True)
    log_file = os.path.join(save_dir, GAME_ID + ".log")
    log = open(log_file, "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log  # o pythonw não tem console
    os.environ["A11Y_GAME_DIR"] = game_dir
    os.environ.setdefault("A11Y_SAVE_DIR", save_dir)
    os.chdir(game_dir)
    sys.path.insert(0, game_dir)
    main = os.path.join(game_dir, EXEC)
    sys.argv = [main]
    code = 0
    try:
        runpy.run_path(main, run_name="__main__")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        traceback.print_exc()
        code = 1
        _message("O jogo fechou com erro. Os detalhes estão em " + log_file)
    log.flush()
    os._exit(code)


_main()
'''


def _dist(path):
    dist = os.path.join(path, "dist")
    os.makedirs(dist, exist_ok=True)
    return dist


def _zip_dir(folder, zip_path):
    """Compacta a pasta folder (ela mesma vira a raiz do zip)."""
    base = os.path.dirname(folder)
    tmp = zip_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, names in os.walk(folder):
            dirs.sort()
            for name in sorted(names):
                full = os.path.join(root, name)
                z.write(full, os.path.relpath(full, base).replace(os.sep, "/"))
    os.replace(tmp, zip_path)


def _copy_game(path, manifest, dest, log=print):
    files = project.package_files(path, manifest)
    pipeline = assets.Pipeline(path, manifest, files, log=log)
    for full, rel in files:
        out = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        pipeline.copy(full, rel, out)
    summary = pipeline.summary()
    if summary:
        log(summary)


def _fresh(folder):
    if os.path.exists(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)


def _needs_sdk(path, manifest):
    if manifest.get("runtime") == "python3" and not os.path.isfile(
            os.path.join(path, "r36s_a11y", "__init__.py")):
        raise project.ProjectError(
            "o projeto não tem a pasta r36s_a11y; rode \"mage.py update\" para copiá-la")


def r36s(path, log=print):
    """Gera dist/<id>-r36s.zip. Devolve o caminho do zip."""
    path = os.path.abspath(path)
    manifest = project.load(path)
    _needs_sdk(path, manifest)
    gid = manifest["id"]
    stage = os.path.join(_dist(path), "r36s")
    _fresh(stage)
    _copy_game(path, manifest, os.path.join(stage, gid), log)
    out = os.path.join(_dist(path), "%s-r36s.zip" % gid)
    _zip_dir(os.path.join(stage, gid), out)
    shutil.rmtree(stage)
    log("R36S: %s (copie a pasta %s para a11y/games no cartão)" % (out, gid))
    return out


def exe_name(name):
    """Nome de arquivo válido no Windows a partir do nome do jogo."""
    clean = "".join(c for c in name if c not in project.BAD_CHARS and c != "/" and ord(c) >= 32)
    clean = re.sub(r"\s+", " ", clean).strip(" .")
    return clean or "jogo"


def windows(path, log=print):
    """Gera dist/<id>-windows.zip com o .exe. Devolve o caminho do zip."""
    path = os.path.abspath(path)
    manifest = project.load(path)
    if manifest.get("runtime") != "python3":
        raise project.ProjectError("a exportação para Windows ainda é só para jogos em Python")
    _needs_sdk(path, manifest)
    gid, title = manifest["id"], exe_name(manifest["name"])
    stage = os.path.join(_dist(path), "windows")
    _fresh(stage)
    app = os.path.join(stage, title)
    game_dir = os.path.join(app, "jogo")
    _copy_game(path, manifest, game_dir, log)

    dll_dir = os.path.join(game_dir, "r36s_a11y", "dll")
    project_dll = os.path.join(path, "r36s_a11y", "dll")
    if downloads.has_dlls(project_dll):
        shutil.copytree(project_dll, dll_dir)
    else:
        downloads.install_dlls(dll_dir, log)

    with downloads.python_package(log) as pkg:
        dll_name = None
        for info in pkg.infolist():
            if not info.filename.startswith("tools/") or info.filename.endswith("/"):
                continue
            rel = info.filename[len("tools/"):]
            if rel.startswith(PYTHON_SKIP) or "/__pycache__/" in rel:
                continue
            if rel == "pythonw.exe":
                rel = title + ".exe"
            elif rel == "LICENSE.txt":
                rel = "LICENCA-Python.txt"
            elif re.match(r"^python3\d+\.dll$", rel):
                dll_name = rel
            out = os.path.join(app, *rel.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with pkg.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    if dll_name is None:
        raise RuntimeError("o pacote do Python não tem a python3XX.dll")
    with open(os.path.join(app, dll_name[:-4] + "._pth"), "w", encoding="utf-8") as f:
        f.write("Lib\nDLLs\n.\nimport site\n")
    with open(os.path.join(app, "sitecustomize.py"), "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"id": gid, "exec": manifest["exec"], "name": manifest["name"]})

    out = os.path.join(_dist(path), "%s-windows.zip" % gid)
    _zip_dir(app, out)
    shutil.rmtree(stage)
    log("Windows: %s (descompacte e abra %s.exe)" % (out, title))
    return out


TARGETS = {"r36s": r36s, "windows": windows}
