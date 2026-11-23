"""Mede o RAG sozinho, sem modelo: recall@1 e recall@3 nas perguntas com resposta conhecida, e se as perguntas
fora da base voltam vazias (o agente então diz "a documentação não trata disso").

  python -m src.avaliar_rag
"""
from __future__ import annotations

import json
import sys

from .config import RAIZ
from .rag import buscar

ARQUIVO = RAIZ / "dados" / "perguntas_rag.json"


def medir() -> dict:
    perguntas = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    linhas, r1, r3, com_resposta, vazias_ok, fora = [], 0, 0, 0, 0, 0
    for p in perguntas:
        ids = [t["id"] for t in buscar(p["pergunta"])]
        if p["esperado"]:
            com_resposta += 1
            r1 += bool(ids) and ids[0] in p["esperado"]
            ok = any(e in ids for e in p["esperado"])
            r3 += ok
        else:
            fora += 1
            vazias_ok += not ids
            ok = not ids
        linhas.append((p["pergunta"], "/".join(p["esperado"] or []) or "(nenhum)", ids, ok))
    return {"linhas": linhas, "recall@1": r1 / com_resposta, "recall@3": r3 / com_resposta,
            "com_resposta": com_resposta, "fora_vazias": vazias_ok, "fora": fora}


def main() -> int:
    m = medir()
    for pergunta, esperado, ids, ok in m["linhas"]:
        print(f"[{'ok' if ok else 'XX'}] {pergunta}  esperado={esperado}  recuperado={ids or '[]'}")
    print(f"\nrecall@1 = {m['recall@1']:.0%}  recall@3 = {m['recall@3']:.0%}  ({m['com_resposta']} perguntas com resposta)")
    print(f"fora da base sem trecho: {m['fora_vazias']} de {m['fora']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
