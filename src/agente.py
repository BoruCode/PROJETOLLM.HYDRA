"""Laço do agente: estado explícito, orçamento, terminação registrada e log da trajetória.

Quem decide o quê:
  MODELO  -> quais ferramentas chamar e com que argumentos; a análise; o texto final.
  CÓDIGO  -> executar SQL, validar regras de negócio, pedir confirmação, contar orçamento, parar, logar.
  HUMANO  -> confirmar cada escrita.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import Config
from .ferramentas import FERRAMENTAS, SCHEMAS, Contexto, erro

# Motivos de parada (o programa sempre diz por que parou).
RESPOSTA_FINAL = "resposta_final"
RESPOSTA_VAZIA = "resposta_vazia"
ORCAMENTO_PASSOS = "orcamento_passos"
ORCAMENTO_TOKENS = "orcamento_tokens"
ORCAMENTO_CUSTO = "orcamento_custo"
ERRO_LLM = "erro_llm"
AGUARDANDO_HUMANO = "aguardando_humano"  # Parte 2: o grafo parou numa escrita e espera aprovação (não é falha)


# --- prompt em arquivo, versionado e carimbado -----------------------------

def carregar_prompt(caminho: str | Path) -> dict:
    """Lê prompts/*.md: cabeçalho '---' com metadados + corpo. O sha entra no log (prompt x modelo x parâmetros)."""
    caminho = Path(caminho)
    # Fim de linha normalizado: o git no Windows (core.autocrlf) grava CRLF, e o mesmo prompt ganhava outro sha
    # (rodada 2 da demonstração: 3f39cff2 em vez de 939190e6), o que faria a retomada recusar a aprovação.
    bruto = caminho.read_bytes().replace(b"\r\n", b"\n")
    texto = bruto.decode("utf-8")
    meta: dict[str, str] = {}
    corpo = texto
    if texto.startswith("---"):
        _, cabecalho, corpo = texto.split("---", 2)
        for linha in cabecalho.strip().splitlines():
            chave, _, valor = linha.partition(":")
            meta[chave.strip()] = valor.strip()
    return {"arquivo": caminho.name, "caminho": str(caminho), "id": meta.get("id", caminho.stem), "versao": meta.get("versao", "?"),
            "sha": hashlib.sha256(bruto).hexdigest()[:8], "texto": corpo.strip(), "meta": meta}


# --- estado e orçamento -----------------------------------------------------

@dataclass
class Orcamento:
    max_passos: int
    max_tokens: int
    max_custo_usd: float | None  # None = preços não configurados, teto de custo não se aplica


@dataclass
class Estado:
    passo: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float | None = None
    usage_ausente: bool = False
    chamadas: list = field(default_factory=list)   # {"passo", "nome", "args", "erro"}
    escritas: list = field(default_factory=list)   # ids dos alertas registrados
    fatos_gravados: list = field(default_factory=list)  # Parte 2: ids dos fatos gravados na memória semântica
    caminho: list = field(default_factory=list)    # Parte 2: nós do grafo visitados, em ordem
    id_execucao: str | None = None
    resposta: str | None = None
    terminacao: str | None = None
    erro_llm: str | None = None
    aviso_verificador: str | None = None  # Controle 3 (ASI09): lotes na resposta sem fonte em ferramenta

    @property
    def tokens(self) -> int:
        return self.tokens_entrada + self.tokens_saida

    @property
    def erros_de_ferramenta(self) -> list[str]:
        return [c["erro"] for c in self.chamadas if c["erro"]]


class Trajetoria:
    """Log da trajetória: uma linha JSON por evento (ferramenta, argumentos, resultado, erro) + eco no terminal."""

    def __init__(self, caminho: str | Path | None = None, verboso: bool = True):
        self.caminho = Path(caminho) if caminho else None
        self.verboso = verboso
        if self.caminho:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)

    def evento(self, tipo: str, **dados) -> None:
        linha = {"ts": datetime.now().isoformat(timespec="seconds"), "evento": tipo, **dados}
        if self.caminho:
            with self.caminho.open("a", encoding="utf-8") as arq:
                arq.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
        if self.verboso and (texto := _eco(linha)):
            print(texto)


def _eco(linha: dict) -> str | None:
    if linha["evento"] == "ferramenta":
        res = linha["resultado"]
        if linha.get("erro"):
            resumo = f"ERRO {linha['erro']}"
        elif res.get("ok"):
            resumo = f"ok (alerta #{res['id_alerta']})" if "id_alerta" in res else f"ok (fato #{res.get('id_fato')})"
        elif "trechos" in res:
            resumo = f"{len(res['trechos'])} trecho(s): {', '.join(t['id'] for t in res['trechos']) or '-'}"
        else:
            resumo = f"{len(res.get('linhas', []))} linha(s)"
        conf = linha.get("confirmacao")
        extra = f" [{'confirmado' if conf['aprovado'] else 'RECUSADO'} por {conf['por']}]" if conf else ""
        args = json.dumps(linha["argumentos"], ensure_ascii=False)
        return f"  [passo {linha['passo']}] {linha['ferramenta']}({args}) -> {resumo}{extra}"
    if linha["evento"] == "pausa":
        return (f"  [pausa] aguardando aprovação: {linha['descricao']}\n"
                f"  Para decidir: python -m src.main --retomar {linha['id_execucao']} --aprovar | --recusar")
    if linha["evento"] == "erro_llm":
        return f"  ERRO na chamada ao modelo: {linha['erro']}"
    return None


# --- cliente ----------------------------------------------------------------

def criar_cliente(cfg: Config):
    """base_url e chave vêm do .env: trocar de provedor não exige mudar código."""
    from openai import OpenAI  # import tardio: os testes rodam sem a biblioteca instalada
    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)


# --- execução: o laço virou um grafo explícito na Parte 2 (src/grafo.py) -----------------

def executar(pergunta: str, **kwargs) -> Estado:
    """Uma pergunta do Administrador, do início ao motivo de parada. Mesma assinatura da Parte 1;
    a implementação agora é o grafo de src/grafo.py (nós, arestas, checkpoint e pausa para o humano)."""
    from .grafo import executar as executar_grafo
    return executar_grafo(pergunta, **kwargs)


def _orcamento_estourado(estado: Estado, orc: Orcamento) -> str | None:
    """Checado ANTES de cada chamada ao modelo (uma chamada pode ultrapassar o teto por até o seu tamanho)."""
    if estado.passo >= orc.max_passos:
        return ORCAMENTO_PASSOS
    if estado.tokens >= orc.max_tokens:
        return ORCAMENTO_TOKENS
    if orc.max_custo_usd is not None and (estado.custo_usd or 0) >= orc.max_custo_usd:
        return ORCAMENTO_CUSTO
    return None


def _contabilizar(estado: Estado, resposta, cfg: Config, calcula_custo: bool) -> None:
    uso = getattr(resposta, "usage", None)
    entrada = getattr(uso, "prompt_tokens", None)
    saida = getattr(uso, "completion_tokens", None)
    if entrada is None or saida is None:
        estado.usage_ausente = True  # provedor não informou: o teto de tokens/custo fica cego, e o log avisa
        return
    estado.tokens_entrada += entrada
    estado.tokens_saida += saida
    if calcula_custo:
        estado.custo_usd = (estado.custo_usd or 0.0) + (
            entrada * cfg.preco_entrada_por_milhao + saida * cfg.preco_saida_por_milhao) / 1_000_000
