"""Controle 3 de segurança (ASI09): verificação de fidelidade numérica da resposta.

Extrai todos os códigos de lote da resposta final (padrão L-[A-Z]{3}-\\d{2}) e verifica
que cada um apareceu em pelo menos um resultado de ferramenta da execução.

Um código de lote que aparece na resposta mas nunca veio de uma ferramenta é um
"lote sem fonte" — o agente inventou ou confundiu com lote de outra execução.

Uso em src/grafo.py:no_finalizar:

    from .verificar import verificar_lotes_na_resposta
    lotes_sem_fonte = verificar_lotes_na_resposta(estado.resposta, estado.chamadas)
    if lotes_sem_fonte:
        estado.aviso_verificador = f"⚠ lote(s) sem fonte na resposta: {lotes_sem_fonte}"

Teste: tests/test_seguranca.py::TestVerificarResposta
"""
from __future__ import annotations

import json
import re

# Padrão de código de lote usado no banco simulado e nos logs do case.
# Exemplos: L-IOG-01, L-PAO-02, L-PRE-01
_RE_LOTE = re.compile(r"\bL-[A-Z]{2,4}-\d{2,3}\b")

# O gpt-oss-120b escreve o hífen dos códigos de lote como hífen não separável (U+2011).
# Sem normalizar, L-IOG-01 não casa e a checagem reprovaria um acerto verdadeiro.
_HIFEN_UNICODE = "\u2011"  # hífen não separável


def _normalizar(texto: str) -> str:
    return texto.replace(_HIFEN_UNICODE, "-")


def _lotes_em_texto(texto: str) -> set[str]:
    """Extrai o conjunto de códigos de lote de um texto qualquer."""
    return set(_RE_LOTE.findall(_normalizar(texto)))


def _lotes_nos_resultados(chamadas: list[dict]) -> set[str]:
    """União dos lotes que apareceram em algum resultado de ferramenta desta execução."""
    lotes: set[str] = set()
    for chamada in chamadas:
        # 'resumo_resultado' é o campo curto gravado por _registrar (src/grafo.py)
        resumo = chamada.get("resumo_resultado", "")
        lotes |= _lotes_em_texto(resumo)
        # Também verifica o campo 'args' (os argumentos da chamada podem conter o lote)
        args = chamada.get("args", {})
        args_str = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args)
        lotes |= _lotes_em_texto(args_str)
    return lotes


def verificar_lotes_na_resposta(resposta: str | None, chamadas: list[dict]) -> list[str]:
    """Controle 3 (ASI09): devolve os códigos de lote da resposta que não vieram de nenhuma ferramenta.

    Args:
        resposta: texto da resposta final do agente.
        chamadas: lista de dicts {'nome', 'args', 'resumo_resultado', ...} de Estado.chamadas.

    Returns:
        Lista (possivelmente vazia) de lotes sem fonte. Lista vazia = resposta fiel aos dados.
    """
    if not resposta:
        return []
    lotes_resposta = _lotes_em_texto(resposta)
    if not lotes_resposta:
        return []
    lotes_ferramentas = _lotes_nos_resultados(chamadas)
    return sorted(lotes_resposta - lotes_ferramentas)
