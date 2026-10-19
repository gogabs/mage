"""O projeto de um jogo: a pasta com game.json, o código e a cópia do Mage Core.

O game.json é o mesmo do contrato da plataforma (docs/contrato.md), com dois
campos opcionais a mais que o Mage Core e a engine entendem:

  "actions": as ações do jogo, no formato de Game.actions (r36s_a11y/actions.py);
  "export":  {"ignore": [...]} padrões de arquivos que não vão para a exportação,
             além dos padrões de IGNORE; {"compress_sounds": false} manda os WAV
             sem virar OGG (veja assets.py).

Os assets ficam em sounds/, images/ e data/ (assets.py).
"""
import fnmatch
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import unicodedata
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
# A versão do Mage Core que a engine copia para os jogos (tools/sync_sdk.py).
SDK_DIR = os.path.join(HERE, "sdk")
SDK_PY = os.path.join(SDK_DIR, "r36s_a11y")
TEMPLATE = os.path.join(HERE, "template")

if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)
from r36s_a11y.actions import Actions  # noqa: E402

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")
RUNTIMES = ("native", "python3", "love", "dotnet")
# Caracteres que o exFAT do cartão e o Windows não aceitam em nomes.
BAD_CHARS = set('<>:"\\|?*')

# Nunca vão para a exportação: coisas de desenvolvimento e de outra plataforma.
# Um padrão sem "/" vale para qualquer nome, em qualquer pasta; com "/" no
# começo, só na raiz do projeto; com "/" no meio, para o caminho inteiro.
IGNORE = [".git", ".github", ".gitignore", ".gitattributes", ".vscode", ".idea",
          "__pycache__", "*.pyc", "*.swp", ".DS_Store", "Thumbs.db",
          "/dist", "/tests", "/tools", "/docs", "/previews", "/r36s_a11y/dll"]


class ProjectError(Exception):
    """Algo no projeto impede de rodar ou exportar; a mensagem diz o quê."""


def load(path):
    """O game.json do projeto, conferido. ProjectError se algo estiver errado."""
    manifest, problems = check(path)
    if problems:
        raise ProjectError("\n".join(problems))
    return manifest


def check(path):
    """(game.json, [problemas]) sem levantar erro, para mostrar tudo de uma vez."""
    file = os.path.join(path, "game.json")
    try:
        with open(file, encoding="utf-8") as f:
            manifest = json.load(f)
    except OSError:
        return {}, ["não achei o game.json em %s" % os.path.abspath(path)]
    except ValueError as e:
        return {}, ["o game.json não é um JSON válido: %s" % e]
    if not isinstance(manifest, dict):
        return {}, ["o game.json precisa ser um objeto {...}"]
    return manifest, manifest_problems(manifest, path)


def manifest_problems(manifest, path):
    """Os problemas de um game.json (já lido) do projeto em path."""
    problems = []
    for field in ("id", "name", "version", "contract", "runtime", "exec"):
        if field not in manifest:
            problems.append("falta o campo \"%s\" no game.json" % field)
    gid = manifest.get("id")
    if gid is not None and not (isinstance(gid, str) and ID_RE.match(gid)):
        problems.append("o id \"%s\" deve ter só minúsculas, números e hífen" % gid)
    version = manifest.get("version")
    if version is not None and not (isinstance(version, str) and SEMVER_RE.match(version)):
        problems.append("a versão \"%s\" deve ser como 1.0.0" % version)
    runtime = manifest.get("runtime")
    if runtime is not None and runtime not in RUNTIMES:
        problems.append("o runtime \"%s\" não existe (use %s)" % (runtime, ", ".join(RUNTIMES)))
    exe = manifest.get("exec")
    if isinstance(exe, str) and not os.path.exists(os.path.join(path, exe)):
        problems.append("o exec aponta para %s, que não existe" % exe)
    export = manifest.get("export")
    if export is not None and not isinstance(export, dict):
        problems.append("\"export\" precisa ser um objeto {...}")
    elif export and not isinstance(export.get("compress_sounds", True), bool):
        problems.append("\"compress_sounds\" em \"export\" deve ser true ou false")
    actions = manifest.get("actions")
    if actions is not None:
        try:
            if not isinstance(actions, dict):
                raise ValueError("\"actions\" precisa ser um objeto {...}")
            Actions().define(actions)
        except (ValueError, AttributeError, KeyError, TypeError) as e:
            problems.append("ações do game.json: %s" % e)
    return problems


def ignore_patterns(manifest):
    extra = (manifest.get("export") or {}).get("ignore") or []
    return IGNORE + [p.rstrip("/") for p in extra if p.strip("/")]


def _ignored(rel, patterns):
    name = os.path.basename(rel)
    for p in patterns:
        if p.startswith("/"):
            if fnmatch.fnmatch(rel, p[1:]):
                return True
        elif fnmatch.fnmatch(rel if "/" in p else name, p):
            return True
    return False


def package_files(path, manifest):
    """[(caminho no disco, caminho relativo com /)] do que vai para o jogo exportado.

    ProjectError se algum nome não puder ir para o cartão (exFAT) ou o Windows.
    """
    patterns = ignore_patterns(manifest)
    files, problems, seen = [], [], {}
    for root, dirs, names in os.walk(path):
        rel_root = os.path.relpath(root, path).replace(os.sep, "/")
        rel_root = "" if rel_root == "." else rel_root + "/"
        dirs[:] = sorted(d for d in dirs if not _ignored(rel_root + d, patterns))
        for entry in dirs + sorted(names):
            rel = rel_root + entry
            full = os.path.join(root, entry)
            if entry in names and _ignored(rel, patterns):
                continue
            if os.path.islink(full):
                problems.append("%s é um link simbólico, e o cartão do R36S não aceita links" % rel)
                continue
            if BAD_CHARS & set(entry) or entry.endswith((" ", ".")):
                problems.append("o nome %s tem caracteres que o cartão e o Windows não aceitam" % rel)
            key = rel.lower()
            if key in seen and seen[key] != rel:
                problems.append("%s e %s só diferem em maiúsculas" % (seen[key], rel))
            seen[key] = rel
            if entry in names:
                files.append((full, rel))
    if problems:
        raise ProjectError("\n".join(problems))
    return files


def update_sdk(path, log=print):
    """Troca a cópia do r36s_a11y do projeto pela que vem com a engine, mantendo as DLLs."""
    dest = os.path.join(path, "r36s_a11y")
    os.makedirs(dest, exist_ok=True)
    for name in os.listdir(dest):
        full = os.path.join(dest, name)
        if name.endswith(".py") or name == "__pycache__":
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
    for name in sorted(os.listdir(SDK_PY)):
        if name.endswith(".py"):
            shutil.copy2(os.path.join(SDK_PY, name), os.path.join(dest, name))
    log("Mage Core %s copiado para %s" % (sdk_version(), dest))


def sdk_version():
    with open(os.path.join(SDK_PY, "__init__.py"), encoding="utf-8") as f:
        match = re.search(r'__version__ = "([^"]+)"', f.read())
    return match.group(1) if match else "?"


def make_id(name):
    """"Meu Jogo Legal" -> "meu-jogo-legal"."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "meu-jogo"


def create(path, name=None, author=None, log=print):
    """Cria um projeto novo em path, a partir do modelo. Devolve o game.json."""
    path = os.path.abspath(path)
    if os.path.exists(path) and os.listdir(path):
        raise ProjectError("a pasta %s já existe e não está vazia" % path)
    folder = os.path.basename(os.path.normpath(path))
    name = name or folder
    gid = folder if ID_RE.match(folder) else make_id(folder)
    for folder in ("sounds", "images", "data"):
        os.makedirs(os.path.join(path, folder), exist_ok=True)

    with open(os.path.join(TEMPLATE, "game.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["id"], manifest["name"] = gid, name
    if author:
        manifest["author"] = author
    else:
        manifest.pop("author", None)
    _write_json(os.path.join(path, "game.json"), manifest)
    for entry in ("main.py", ".gitignore"):
        shutil.copy2(os.path.join(TEMPLATE, entry), os.path.join(path, entry))
    _write_beep(os.path.join(path, "sounds", "bip.wav"))
    update_sdk(path, log=lambda *_: None)
    log("Projeto %s criado em %s" % (name, path))
    return manifest


def _write_json(file, data):
    with open(file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _write_beep(file, freq=880, seconds=0.15, rate=22050):
    """Um bip curto e mono, para o modelo já tocar um som."""
    frames = int(rate * seconds)
    samples = []
    for i in range(frames):
        fade = min(1.0, i / 200.0, (frames - i) / 400.0)
        samples.append(int(12000 * fade * math.sin(2 * math.pi * freq * i / rate)))
    with wave.open(file, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % frames, *samples))


def check_all(path):
    """(game.json, [problemas], [arquivos para exportar]): o game.json, as ações e os nomes."""
    manifest, problems = check(path)
    files = []
    if not problems:
        try:
            files = package_files(path, manifest)
        except ProjectError as e:
            problems = str(e).splitlines()
    return manifest, problems, files


def start_game(path, pc=False, log=print):
    """Abre o jogo num processo à parte e devolve o Popen.

    No Windows, baixa as DLLs do Mage Core para o jogo na primeira vez.
    """
    path = os.path.abspath(path)
    manifest = load(path)
    if manifest["runtime"] != "python3":
        raise ProjectError("rodar ainda é só para jogos em Python")
    if sys.platform == "win32":
        from . import downloads
        dll = os.path.join(path, "r36s_a11y", "dll")
        if not downloads.has_dlls(dll):
            log("Primeira vez no Windows: baixando as DLLs do Mage Core para o jogo.")
            downloads.install_dlls(dll, log)
    env = dict(os.environ, A11Y_GAME_DIR=path)
    if pc:
        env["A11Y_PLATAFORMA"] = "pc"
    return subprocess.Popen([sys.executable, manifest["exec"]], cwd=path, env=env)


def save_manifest(path, manifest):
    """Grava o game.json do projeto, mantendo acentos legíveis."""
    _write_json(os.path.join(path, "game.json"), manifest)
