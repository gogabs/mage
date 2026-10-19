"""Downloads conferidos pelo SHA-256: as DLLs do r36s_a11y e o Python do Windows.

A lista das DLLs é a mesma do tools/preparar_windows.py do Mage Core; mude as duas juntas.

Tudo vem de lançamentos oficiais (GitHub da SDL e da OpenAL Soft, PyPI e o
pacote NuGet do Python, publicado pela própria Python Software Foundation).
Os arquivos baixados ficam numa pasta de cache, para a segunda exportação
não baixar de novo.
"""
import hashlib
import io
import os
import sys
import urllib.request
import zipfile

GH = "https://github.com"
PYPI = "https://files.pythonhosted.org/packages"
NUGET = "https://api.nuget.org/v3-flatcontainer"

# (url, sha256, {arquivo dentro do zip: nome na pasta dll})
DLLS = [
    (GH + "/libsdl-org/SDL/releases/download/release-2.32.10/SDL2-2.32.10-win32-x64.zip",
     "6cf9706eefd0a4a06dc764007934d428afaf029fabdd408a9e646048c91e18fb",
     {"SDL2.dll": "SDL2.dll", "README-SDL.txt": "LICENCA-SDL2.txt"}),
    (GH + "/libsdl-org/SDL_image/releases/download/release-2.8.8/SDL2_image-2.8.8-win32-x64.zip",
     "740d6c7fe40087db01e0d7bd636e3eaebe4bffbde58b595bf0c3b7c359a43033",
     {"SDL2_image.dll": "SDL2_image.dll"}),
    (GH + "/libsdl-org/SDL_ttf/releases/download/release-2.24.0/SDL2_ttf-2.24.0-win32-x64.zip",
     "8d72240aafc783d37d6cf960b1a2138e6ca4eb0c1b5b9a9e71ea299d1ef27ef9",
     {"SDL2_ttf.dll": "SDL2_ttf.dll"}),
    (GH + "/kcat/openal-soft/releases/download/1.24.3/openal-soft-1.24.3-bin.zip",
     "03c8c0c0bcdba9d3fb54b0d3c2f9a565f81b3e2a19a538dd394f9b8cb6caaa22",
     {"openal-soft-1.24.3-bin/bin/Win64/soft_oal.dll": "soft_oal.dll",
      "openal-soft-1.24.3-bin/COPYING": "LICENCA-OpenAL-Soft.txt"}),
    (PYPI + "/ed/97/b39c18ac1df45e755ca22b8b00e872929da5d107998a207a5e4ac831bfda/"
     "soundfile-0.14.0-py2.py3-none-win_amd64.whl",
     "299491d3499460fb1b74bb4bd78b57ffc2d243a5fafa7b6ec1b264875c78453e",
     {"_soundfile_data/libsndfile_x64.dll": "libsndfile_x64.dll",
      "_soundfile_data/COPYING": "LICENCA-libsndfile.txt"}),
    (PYPI + "/02/8e/2bb81f845d8f3ecb07acd094544ecbf0c0e02f80364e35fdabaec96ee6dc/"
     "accessible_output2-0.17-py2.py3-none-any.whl",
     "bdcfc5f2c8ecb50b219fa7d547018dd0c99dfa4c56b506872c74f5dc941a3288",
     {"accessible_output2/lib/nvdaControllerClient64.dll": "nvdaControllerClient64.dll"}),
]

# Python 3.13 para Windows x64 que vai dentro do executável exportado.
PYTHON_VERSION = "3.13.16"
PYTHON = (NUGET + "/python/%s/python.%s.nupkg" % (PYTHON_VERSION, PYTHON_VERSION),
          "95fad176338f1d6a799e45946488063f4aa61764e6cff2f132ddeffbf7a04c34")


def cache_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    path = os.path.join(base, "r36s-a11y", "downloads")
    os.makedirs(path, exist_ok=True)
    return path


def fetch(url, sha256, log=print):
    """Os bytes do arquivo, do cache ou da internet, sempre conferidos."""
    cached = os.path.join(cache_dir(), sha256)
    if os.path.exists(cached):
        with open(cached, "rb") as f:
            data = f.read()
        if hashlib.sha256(data).hexdigest() == sha256:
            return data
    log("baixando %s..." % url.rsplit("/", 1)[1])
    with urllib.request.urlopen(url, timeout=300) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise RuntimeError("SHA-256 diferente do esperado para %s" % url)
    tmp = cached + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, cached)
    return data


def has_dlls(dest):
    return all(os.path.exists(os.path.join(dest, out))
               for _, _, files in DLLS for out in files.values())


def install_dlls(dest, log=print):
    """Põe as DLLs na pasta dest (a pasta dll do r36s_a11y)."""
    os.makedirs(dest, exist_ok=True)
    for url, sha256, files in DLLS:
        if all(os.path.exists(os.path.join(dest, out)) for out in files.values()):
            continue
        with zipfile.ZipFile(io.BytesIO(fetch(url, sha256, log))) as archive:
            for inner, out in files.items():
                with open(os.path.join(dest, out), "wb") as f:
                    f.write(archive.read(inner))


def python_package(log=print):
    """O pacote NuGet do Python, como ZipFile."""
    return zipfile.ZipFile(io.BytesIO(fetch(PYTHON[0], PYTHON[1], log)))
