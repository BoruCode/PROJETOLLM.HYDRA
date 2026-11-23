"""Acesso ao SQLite: a fronteira do processo (requisito 4.2 do enunciado).

O agente nunca toca no banco diretamente: só as ferramentas (src/ferramentas.py) abrem
consultas, sempre com parâmetros "?" (nunca concatenando valor do modelo no SQL).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import RAIZ


def conectar(caminho: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(caminho))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def conectar_leitura(caminho: str | Path) -> sqlite3.Connection:
    """Controle 2 (ASI03): abre o SQLite em modo somente leitura (mode=ro).

    Qualquer tentativa de INSERT/UPDATE/DELETE levanta sqlite3.OperationalError
    antes de tocar nos dados — garante que uma ferramenta de leitura não escreva
    por bug ou injeção futura.

    fail-closed: se o arquivo não existir ou não for acessível, a conexão falha
    e a ferramenta devolve erro_banco (nenhuma leitura acontece).

    Teste: tests/test_seguranca.py::TestConectarLeitura
    """
    uri = f"file:{Path(caminho).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def criar_banco(caminho: str | Path) -> Path:
    """Apaga e recria o banco a partir de dados/schema.sql + dados/seed.sql."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.unlink(missing_ok=True)
    conn = sqlite3.connect(str(caminho))
    try:
        for arquivo in ("schema.sql", "seed.sql"):
            conn.executescript((RAIZ / "dados" / arquivo).read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return caminho
