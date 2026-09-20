"""Configuração: tudo vem do ambiente (.env). Nenhuma chave no código."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

OBRIGATORIAS = ("LLM_BASE_URL", "OPENAI_API_KEY", "LLM_MODEL")


@dataclass(frozen=True)
class Config:
    # provedor e modelo (docs/modelos.md justifica a escolha)
    base_url: str = ""
    api_key: str = ""
    modelo: str = ""
    temperature: float | None = 0.0  # None = não envia o parâmetro (alguns modelos rejeitam)

    # dados
    caminho_db: Path = RAIZ / "dados" / "hydra_demo.db"
    id_loja: int = 1
    limite_dias_alerta_validade: int = 30  # regra de negócio da escrita

    # orçamento por pergunta (o laço para quando qualquer teto é atingido)
    max_passos: int = 8
    max_tokens: int = 20_000
    max_custo_usd: float = 0.05
    preco_entrada_por_milhao: float | None = None  # sem preços, o custo não é calculado
    preco_saida_por_milhao: float | None = None

    # arquivos
    arquivo_prompt: Path = RAIZ / "prompts" / "sistema_v1.md"
    pasta_logs: Path = RAIZ / "logs"


def _numero(nome: str, padrao, tipo=float):
    bruto = os.getenv(nome, "").strip()
    if not bruto:
        return padrao
    try:
        return tipo(bruto)
    except ValueError:
        raise SystemExit(f"Valor inválido em {nome}={bruto!r} (esperado {tipo.__name__}).")


def _temperatura() -> float | None:
    bruto = os.getenv("LLM_TEMPERATURE", "0").strip().lower()
    if bruto in ("none", "null"):
        return None
    try:
        return float(bruto or 0)
    except ValueError:
        raise SystemExit(f"Valor inválido em LLM_TEMPERATURE={bruto!r}.")


def carregar_config(exigir_llm: bool = True) -> Config:
    faltando = [n for n in OBRIGATORIAS if not os.getenv(n, "").strip()]
    if exigir_llm and faltando:
        raise SystemExit(
            "Faltam variáveis no .env: " + ", ".join(faltando) + "\n"
            "Copie .env.example para .env e preencha."
        )
    caminho_db = os.getenv("HYDRA_DB_PATH", "").strip()
    return Config(
        base_url=os.getenv("LLM_BASE_URL", "").strip(),
        api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        modelo=os.getenv("LLM_MODEL", "").strip(),
        temperature=_temperatura(),
        caminho_db=(RAIZ / caminho_db) if caminho_db else Config.caminho_db,
        id_loja=_numero("ID_LOJA", 1, int),
        limite_dias_alerta_validade=_numero("LIMITE_DIAS_ALERTA_VALIDADE", 30, int),
        max_passos=_numero("MAX_PASSOS", 8, int),
        max_tokens=_numero("MAX_TOKENS", 20_000, int),
        max_custo_usd=_numero("MAX_CUSTO_USD", 0.05, float),
        preco_entrada_por_milhao=_numero("PRECO_ENTRADA_USD_POR_MILHAO", None, float),
        preco_saida_por_milhao=_numero("PRECO_SAIDA_USD_POR_MILHAO", None, float),
    )
