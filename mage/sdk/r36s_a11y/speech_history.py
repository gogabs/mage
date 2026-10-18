"""Histórico de falas do sistema (/roms/a11y/log/historico-falas.txt).

Cada fala do jogo vira uma linha no fim do arquivo; o a11yd deixa o jogador
voltar e avançar nas últimas 50 com Fn + L1 e Fn + R1. Formato comum a todas
as bibliotecas-ponte: uma fala por linha, em UTF-8, com as quebras de linha
trocadas por espaço, só acrescentando no fim. Quem vê o arquivo passar de
TRIM_BYTES o reescreve com as últimas MAX_ENTRIES linhas.

Sem a pasta do arquivo (no PC, por exemplo), nada é gravado.
"""
import os

PATH = os.environ.get("A11Y_HISTORICO_FALAS", "/roms/a11y/log/historico-falas.txt")
MAX_ENTRIES = 50
TRIM_BYTES = 16384


def record(text, path=None):
    """Acrescenta a fala ao histórico. Erros de disco são ignorados."""
    path = path or PATH
    line = " ".join(str(text).split())
    if not line or not os.path.isdir(os.path.dirname(path)):
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            size = f.tell()
        if size > TRIM_BYTES:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = [l.strip() for l in f if l.strip()][-MAX_ENTRIES:]
            data = "".join(l + "\n" for l in lines)
            tmp = "%s.%d.tmp" % (path, os.getpid())
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(data)
                os.replace(tmp, path)
            except OSError:
                # Sem rename por cima (exFAT pela FUSE): reescreve direto.
                with open(path, "w", encoding="utf-8") as f:
                    f.write(data)
                if os.path.exists(tmp):
                    os.remove(tmp)
    except OSError:
        pass
