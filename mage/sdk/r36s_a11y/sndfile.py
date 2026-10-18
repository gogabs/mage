"""OGG (e WAV, FLAC...) pela libsndfile, quando não há libvorbisfile.

No Windows não existe uma vorbisfile.dll oficial para baixar; a libsndfile
tem (vem no pacote soundfile do PyPI) e decodifica OGG Vorbis sozinha, numa
DLL só. Sempre entrega PCM de 16 bits.
"""
import ctypes
import os
import sys

from . import native

SFM_READ = 0x10
SEEK_SET = 0

_lib = None


class _Info(ctypes.Structure):
    _fields_ = [("frames", ctypes.c_int64), ("samplerate", ctypes.c_int),
                ("channels", ctypes.c_int), ("format", ctypes.c_int),
                ("sections", ctypes.c_int), ("seekable", ctypes.c_int)]


def _library():
    global _lib
    if _lib is None:
        lib = native.load(["libsndfile_x64.dll", "libsndfile-1.dll", "sndfile.dll",
                           "libsndfile.so.1", "sndfile"])
        vp = ctypes.c_void_p
        lib.sf_open.restype, lib.sf_open.argtypes = vp, [ctypes.c_char_p, ctypes.c_int,
                                                          ctypes.POINTER(_Info)]
        if sys.platform == "win32":  # caminho com acento precisa da versão "larga"
            lib.sf_wchar_open.restype = vp
            lib.sf_wchar_open.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(_Info)]
        lib.sf_readf_short.restype = ctypes.c_int64
        lib.sf_readf_short.argtypes = [vp, ctypes.c_void_p, ctypes.c_int64]
        lib.sf_seek.restype, lib.sf_seek.argtypes = ctypes.c_int64, [vp, ctypes.c_int64, ctypes.c_int]
        lib.sf_close.restype, lib.sf_close.argtypes = ctypes.c_int, [vp]
        lib.sf_strerror.restype, lib.sf_strerror.argtypes = ctypes.c_char_p, [vp]
        _lib = lib
    return _lib


class SndFile:
    """Um arquivo aberto para leitura em blocos (usado também no streaming)."""

    def __init__(self, path):
        self.lib = _library()
        info = _Info()
        if sys.platform == "win32":
            self.handle = self.lib.sf_wchar_open(os.path.abspath(path), SFM_READ, ctypes.byref(info))
        else:
            self.handle = self.lib.sf_open(os.fsencode(path), SFM_READ, ctypes.byref(info))
        if not self.handle:
            raise ValueError("%s: %s" % (path, self.lib.sf_strerror(None).decode("utf-8", "replace")))
        self.channels, self.rate, self.frames = info.channels, info.samplerate, info.frames
        if self.channels not in (1, 2):
            self.close()
            raise ValueError("%s: só mono ou estéreo" % path)

    def read(self, max_bytes):
        """Até max_bytes de PCM 16 bits; b"" no fim."""
        frames = max(1, max_bytes // (2 * self.channels))
        buf = ctypes.create_string_buffer(frames * 2 * self.channels)
        n = self.lib.sf_readf_short(self.handle, buf, frames)
        return ctypes.string_at(buf, max(0, n) * 2 * self.channels)

    def rewind(self):
        if self.lib.sf_seek(self.handle, 0, SEEK_SET) < 0:
            raise ValueError("não deu para voltar ao início do arquivo")

    def close(self):
        if self.handle:
            self.lib.sf_close(self.handle)
            self.handle = None


def decode(path):
    """(canais, 2, taxa, PCM) do arquivo inteiro, como decode_ogg."""
    f = SndFile(path)
    try:
        parts = []
        while True:
            data = f.read(1 << 18)
            if not data:
                break
            parts.append(data)
    finally:
        f.close()
    return f.channels, 2, f.rate, b"".join(parts)
