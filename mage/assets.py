"""Os arquivos do jogo que não são código: sons, imagens e dados.

Cada tipo tem a sua pasta na raiz do projeto:

  sounds/   WAV, OGG ou FLAC
  images/   PNG, JPG, BMP, GIF ou WebP (sprites, fundos)
  data/     o resto: JSON, texto, mapas, fases

Na exportação, os WAV viram OGG Vorbis pela libsndfile, que é bem menor. O
código continua pedindo "sounds/bip.wav": o r36s_a11y 0.4.0 ou mais novo acha
o "sounds/bip.ogg" sozinho. Para mandar os WAV como estão, use no game.json
"export": {"compress_sounds": false}.
"""
import ctypes
import os
import re
import shutil
import sys

from . import downloads, project
from r36s_a11y import native

FOLDERS = {
    "sounds": (".wav", ".ogg", ".flac"),
    "images": (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"),
    "data": None,   # qualquer outro arquivo
}
LABELS = {"sounds": "Sons", "images": "Imagens", "data": "Dados"}
MAX_UPLOAD = 200 * 1024 * 1024
OGG_QUALITY = 0.5           # 0 a 1, VBR da libvorbis; 0.5 soa limpo em fone
FALLBACK_SDK = (0, 4, 0)    # o r36s_a11y que acha o .ogg quando o código pede .wav
BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def folder_for(name):
    """A pasta (sounds, images ou data) de um arquivo, pela extensão."""
    ext = os.path.splitext(name)[1].lower()
    for folder, exts in FOLDERS.items():
        if exts and ext in exts:
            return folder
    return "data"


def clean_name(name):
    """Só o nome do arquivo, conferido para valer no cartão (exFAT) e no Windows."""
    name = os.path.basename(name.replace("\\", "/")).strip()
    if not name or name in (".", "..") or BAD_NAME.search(name) or name.endswith((".", " ")):
        raise project.ProjectError("o nome de arquivo \"%s\" não vale no cartão do R36S" % name)
    return name


def listing(path):
    """{pasta: [(caminho relativo, bytes)]} das três pastas de assets."""
    found = {}
    for folder in FOLDERS:
        items = []
        for root, dirs, names in os.walk(os.path.join(path, folder)):
            dirs.sort()
            for name in sorted(names):
                full = os.path.join(root, name)
                items.append((os.path.relpath(full, path).replace(os.sep, "/"),
                              os.path.getsize(full)))
        found[folder] = items
    return found


def inside(path, rel):
    """O caminho completo de rel, se ele estiver dentro de uma pasta de assets."""
    full = os.path.realpath(os.path.join(path, rel))
    for folder in FOLDERS:
        base = os.path.realpath(os.path.join(path, folder))
        if full.startswith(base + os.sep) and os.path.isfile(full):
            return full
    return None


def add(path, name, data):
    """Grava um arquivo na pasta do tipo dele. Devolve (relativo, substituiu?)."""
    name = clean_name(name)
    folder = folder_for(name)
    os.makedirs(os.path.join(path, folder), exist_ok=True)
    full = os.path.join(path, folder, name)
    replaced = os.path.exists(full)
    tmp = full + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, full)
    return "%s/%s" % (folder, name), replaced


def remove(path, rel):
    full = inside(path, rel)
    if not full:
        raise project.ProjectError("%s não é um arquivo de sounds, images ou data" % rel)
    os.remove(full)


def size_text(size):
    if size >= 1024 * 1024:
        return ("%.1f MB" % (size / 1048576.0)).replace(".", ",")
    if size >= 1024:
        return "%d KB" % round(size / 1024.0)
    return "%d bytes" % size


# --- pipeline da exportação ----------------------------------------------
SFM_READ, SFM_WRITE = 0x10, 0x20
SF_FORMAT_OGG_VORBIS = 0x200000 | 0x0060
SFC_SET_VBR_ENCODING_QUALITY = 0x1300


class _Info(ctypes.Structure):
    _fields_ = [("frames", ctypes.c_int64), ("samplerate", ctypes.c_int),
                ("channels", ctypes.c_int), ("format", ctypes.c_int),
                ("sections", ctypes.c_int), ("seekable", ctypes.c_int)]


_lib = None


def _sndfile(log=print):
    """A libsndfile, para ler qualquer WAV e gravar OGG; None se não houver."""
    global _lib
    if _lib is None:
        names = ["libsndfile_x64.dll", "libsndfile-1.dll", "sndfile.dll", "libsndfile.so.1",
                 "sndfile"]
        try:
            lib = native.load(names)
        except OSError:
            if sys.platform != "win32":
                return None
            downloads.install_dlls(native.DLL_DIR, log=log)
            try:
                lib = native.load(names)
            except OSError:
                return None
        vp = ctypes.c_void_p
        lib.sf_open.restype, lib.sf_open.argtypes = vp, [ctypes.c_char_p, ctypes.c_int,
                                                          ctypes.POINTER(_Info)]
        if sys.platform == "win32":
            lib.sf_wchar_open.restype = vp
            lib.sf_wchar_open.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(_Info)]
        lib.sf_readf_short.restype = ctypes.c_int64
        lib.sf_readf_short.argtypes = [vp, ctypes.c_void_p, ctypes.c_int64]
        lib.sf_writef_short.restype = ctypes.c_int64
        lib.sf_writef_short.argtypes = [vp, ctypes.c_void_p, ctypes.c_int64]
        lib.sf_command.restype = ctypes.c_int
        lib.sf_command.argtypes = [vp, ctypes.c_int, vp, ctypes.c_int]
        lib.sf_close.restype, lib.sf_close.argtypes = ctypes.c_int, [vp]
        lib.sf_strerror.restype, lib.sf_strerror.argtypes = ctypes.c_char_p, [vp]
        _lib = lib
    return _lib


def _open(lib, path, mode, info):
    if sys.platform == "win32":
        handle = lib.sf_wchar_open(os.path.abspath(path), mode, ctypes.byref(info))
    else:
        handle = lib.sf_open(os.fsencode(path), mode, ctypes.byref(info))
    if not handle:
        raise ValueError("%s: %s" % (path, lib.sf_strerror(None).decode("utf-8", "replace")))
    return handle


def encode_ogg(src, dest, quality=OGG_QUALITY, lib=None):
    """Grava src (WAV, FLAC...) como OGG Vorbis em dest."""
    lib = lib or _sndfile()
    info = _Info()
    reader = _open(lib, src, SFM_READ, info)
    try:
        out_info = _Info(samplerate=info.samplerate, channels=info.channels,
                         format=SF_FORMAT_OGG_VORBIS)
        writer = _open(lib, dest, SFM_WRITE, out_info)
        try:
            q = ctypes.c_double(quality)
            lib.sf_command(writer, SFC_SET_VBR_ENCODING_QUALITY, ctypes.byref(q),
                           ctypes.sizeof(q))
            frames = 16384
            buf = ctypes.create_string_buffer(frames * 2 * info.channels)
            while True:
                n = lib.sf_readf_short(reader, buf, frames)
                if n <= 0:
                    break
                lib.sf_writef_short(writer, buf, n)
        finally:
            lib.sf_close(writer)
    finally:
        lib.sf_close(reader)


def game_sdk_version(path):
    try:
        with open(os.path.join(path, "r36s_a11y", "__init__.py"), encoding="utf-8") as f:
            match = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)', f.read())
    except OSError:
        return None
    return tuple(int(n) for n in match.groups()) if match else None


class Pipeline:
    """Processa os arquivos da exportação, um por vez, e conta o que fez."""

    def __init__(self, path, manifest, files, log=print):
        self.log = log
        self.compressed = self.before = self.after = 0
        self.lib = None
        self.reason = None
        rels = set(rel.lower() for _, rel in files)
        self.has_ogg = lambda rel: os.path.splitext(rel)[0].lower() + ".ogg" in rels
        wavs = [rel for _, rel in files if rel.lower().endswith(".wav")]
        if not wavs:
            return
        if (manifest.get("export") or {}).get("compress_sounds", True) is False:
            return
        if manifest.get("runtime") != "python3":
            self.reason = "só jogos em Python acham o .ogg sozinhos"
        elif (game_sdk_version(path) or (0, 0, 0)) < FALLBACK_SDK:
            self.reason = ("o r36s_a11y do jogo é antigo; rode \"mage.py update\" para "
                           "comprimir os sons")
        else:
            self.lib = _sndfile(log)
            if self.lib is None:
                self.reason = "não achei a libsndfile neste computador"

    def copy(self, full, rel, out):
        """Copia full para out, comprimindo os WAV. Devolve o caminho gravado."""
        if self.lib and rel.lower().endswith(".wav") and not self.has_ogg(rel):
            ogg = os.path.splitext(out)[0] + ".ogg"
            try:
                encode_ogg(full, ogg, lib=self.lib)
            except ValueError as e:
                self.log("ficou em WAV: %s" % e)
            else:
                size, new = os.path.getsize(full), os.path.getsize(ogg)
                if new < size:
                    self.compressed += 1
                    self.before += size
                    self.after += new
                    return ogg
                os.remove(ogg)
        shutil.copy2(full, out)
        return out

    def summary(self):
        if self.compressed:
            return "Sons: %d WAV viraram OGG, de %s para %s." % (
                self.compressed, size_text(self.before), size_text(self.after))
        if self.reason:
            return "Os WAV foram como estão: %s." % self.reason
        return None
