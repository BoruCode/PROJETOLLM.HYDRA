"""Memória de curto prazo persistida: um arquivo JSON por execução, gravado a cada passo do grafo.

Serve para três coisas (Exercício 8 §1.1):
  1. retomar uma execução que parou esperando aprovação humana — horas depois e de outro processo;
  2. não reaplicar efeito colateral na retomada (cada escrita tem chave de idempotência);
  3. depurar: o arquivo tem as mensagens exatas enviadas ao modelo e o carimbo (prompt, modelo, memória lida).

Não guarda chave de API, string de conexão nem nada do .env: isso vem do ambiente na retomada.
Ciclo de vida: status 'aguardando_humano' fica até ser resolvido; 'encerrada' é apagado 7 dias depois
(python -m src.manutencao).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

DIAS_RETENCAO = 7


def _caminho(pasta: Path, id_execucao: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", id_execucao or ""):
        raise ValueError(f"id_execucao inválido: {id_execucao!r}")
    return Path(pasta) / f"{id_execucao}.json"


def salvar(pasta: Path, id_execucao: str, dados: dict) -> Path:
    """Grava de forma atômica (arquivo temporário + rename): uma queda no meio não deixa JSON pela metade."""
    destino = _caminho(pasta, id_execucao)
    destino.parent.mkdir(parents=True, exist_ok=True)
    dados = {**dados, "atualizado_em": datetime.now().isoformat(timespec="seconds")}
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, destino)
    return destino


def carregar(pasta: Path, id_execucao: str) -> dict:
    caminho = _caminho(pasta, id_execucao)
    if not caminho.exists():
        raise FileNotFoundError(f"Não existe checkpoint para a execução {id_execucao} em {pasta}.")
    return json.loads(caminho.read_text(encoding="utf-8"))


def pendentes(pasta: Path) -> list[dict]:
    """Execuções paradas esperando uma pessoa (o que a tela do Hydra, ou o terminal, lista para aprovar)."""
    saida = []
    for arq in sorted(Path(pasta).glob("*.json")) if Path(pasta).exists() else []:
        dados = json.loads(arq.read_text(encoding="utf-8"))
        if dados.get("status") == "aguardando_humano":
            saida.append({"id_execucao": dados["id_execucao"], "pergunta": dados["pergunta"],
                          "descricao": dados["pendente"]["descricao"], "pedido_em": dados["pendente"]["pedido_em"]})
    return saida


def apagar_encerrados(pasta: Path, dias: int = DIAS_RETENCAO) -> int:
    limite = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    n = 0
    for arq in Path(pasta).glob("*.json") if Path(pasta).exists() else []:
        dados = json.loads(arq.read_text(encoding="utf-8"))
        if dados.get("status") == "encerrada" and dados.get("atualizado_em", "") < limite:
            arq.unlink()
            n += 1
    return n
