#!/usr/bin/env python3
"""Cria, roda e exporta jogos feitos com o r36s_a11y.

    python mage.py new C:\\jogos\\meu-jogo --name "Meu Jogo"
    python mage.py run C:\\jogos\\meu-jogo
    python mage.py export C:\\jogos\\meu-jogo              # R36S e Windows
    python mage.py export C:\\jogos\\meu-jogo --to r36s

Veja "python mage.py --help" e o README.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mage.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
