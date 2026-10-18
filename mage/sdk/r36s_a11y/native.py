"""Carrega as bibliotecas nativas (SDL2, OpenAL...) do sistema ou da pasta dll.

No PC com Windows, `tools/preparar_windows.py` baixa as DLLs para
`r36s_a11y/dll/`; elas também valem se estiverem ao lado da biblioteca. No
console, tudo vem do sistema.
"""
import ctypes
import ctypes.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DLL_DIR = os.path.join(HERE, "dll")

if sys.platform == "win32" and os.path.isdir(DLL_DIR) and hasattr(os, "add_dll_directory"):
    # dependências entre DLLs (SDL2_ttf precisa da SDL2.dll, por exemplo)
    os.add_dll_directory(DLL_DIR)


def load(names, mode=None, loader=ctypes.CDLL):
    """Abre a primeira biblioteca que existir; OSError se nenhuma existir."""
    kwargs = {} if mode is None else {"mode": mode}
    for name in names:
        candidates = []
        if name.endswith(".dll"):
            candidates += [os.path.join(d, name) for d in (DLL_DIR, HERE)
                           if os.path.exists(os.path.join(d, name))]
        candidates += [name, ctypes.util.find_library(name)]
        for candidate in candidates:
            if candidate:
                try:
                    return loader(candidate, **kwargs)
                except OSError:
                    pass
    raise OSError("biblioteca não encontrada: %s" % ", ".join(names))
