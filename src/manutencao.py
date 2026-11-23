"""Rotina de esquecimento (rodar uma vez por dia; docs/memoria.md §2.2):
  - apaga episódios com mais de 90 dias (memória episódica);
  - apaga checkpoints de execuções encerradas há mais de 7 dias.
A memória semântica não é apagada por tempo: fato sem reconfirmação há 180 dias só entra marcado como duvidoso.

  python -m src.manutencao
"""
from __future__ import annotations

import sys

from . import checkpoint
from .config import carregar_config
from .db import conectar
from .memoria import apagar_episodios_antigos


def main() -> int:
    cfg = carregar_config(exigir_llm=False)
    conn = conectar(cfg.caminho_db)
    try:
        n_epi = apagar_episodios_antigos(conn)
    finally:
        conn.close()
    n_chk = checkpoint.apagar_encerrados(cfg.pasta_checkpoints)
    print(f"episódios apagados: {n_epi} | checkpoints apagados: {n_chk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
