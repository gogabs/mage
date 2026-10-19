"""Traz para a engine a versão do r36s_a11y que ela copia para os jogos.

    python tools/sync_sdk.py ../r36s-a11y-sdk

Copia python/r36s_a11y (sem DLLs nem __pycache__) para mage/sdk/ e
grava em mage/sdk/origin.json a versão e o commit do Mage Core, para saber
de onde veio a cópia. Rode quando quiser que os jogos passem a usar um Mage Core
mais novo e teste antes de mandar.
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "mage", "sdk")


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    sdk = os.path.abspath(argv[1])
    src = os.path.join(sdk, "python", "r36s_a11y")
    if not os.path.isfile(os.path.join(src, "__init__.py")):
        sys.exit("não achei python/r36s_a11y em %s" % sdk)
    commit = subprocess.check_output(["git", "-C", sdk, "rev-parse", "HEAD"],
                                     universal_newlines=True).strip()
    dirty = subprocess.check_output(["git", "-C", sdk, "status", "--porcelain", "python/r36s_a11y"],
                                    universal_newlines=True).strip()
    if dirty:
        sys.exit("o r36s_a11y do Mage Core tem mudanças sem commit; faça o commit antes")
    with open(os.path.join(src, "__init__.py"), encoding="utf-8") as f:
        version = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)

    out = os.path.join(DEST, "r36s_a11y")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    for name in sorted(os.listdir(src)):
        if name.endswith(".py"):
            shutil.copy2(os.path.join(src, name), os.path.join(out, name))
    with open(os.path.join(DEST, "origin.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"repository": "gogabs/r36s-a11y-sdk", "version": version, "commit": commit},
                  f, indent=2)
        f.write("\n")
    print("Mage Core %s (%s) copiado para %s" % (version, commit[:7], out))


if __name__ == "__main__":
    main(sys.argv)
