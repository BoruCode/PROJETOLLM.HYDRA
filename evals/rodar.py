"""Suíte de avaliação — executa o golden dataset e grava o resultado.

Uso:
    python -m evals.rodar --versao 1.0.0
    python -m evals.rodar --versao 1.0.0 --classe consulta
    python -m evals.rodar --versao 1.0.0 --repeticoes 3
    python -m evals.rodar --versao 1.0.0 --pausa 60      # 60 s entre casos (limite de taxa do Groq)

O resultado de cada rodada é gravado em evals/resultados/<versao>_<data>_<hora>/
com um arquivo JSON por caso e um resumo.json.

Métricas gravadas:
  - pass^k: caso só passa se todas as k repetições passarem em todas as checagens
  - pass@k (diagnóstico): caso passa em ao menos 1 das k repetições
  - latência p50 e p95 por caso
  - tokens e custo por execução
  - motivo de terminação por execução

Os casos são os do golden dataset (dados/golden.json).
O sistema avaliado é o mesmo que o README documenta: src/grafo.py via src/avaliar.py.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from src.agente import Trajetoria, carregar_prompt, criar_cliente
from src.config import RAIZ, Config, carregar_config
from src.db import conectar, criar_banco
from src.ferramentas import Contexto

ARQUIVO_GOLDEN = RAIZ / "dados" / "golden.json"
PASTA_RESULTADOS = RAIZ / "evals" / "resultados"
PASTA_LOGS_SUITE = RAIZ / "logs" / "suite"


# ---------------------------------------------------------------------------
# Verificador (baseado em src/avaliar.py mas adaptado ao golden.json)
# ---------------------------------------------------------------------------

def _alertas_no_banco(conn) -> set[tuple]:
    linhas = conn.execute("""
        SELECT p.nome, l.codigo_lote FROM alertas_agente a
          JOIN produtos p ON p.id_produto = a.id_produto
          LEFT JOIN lotes l ON l.id_lote = a.id_lote
         WHERE a.status = 'aberto'""").fetchall()
    return {(linha[0], linha[1]) for linha in linhas}


def verificar(verificador: dict, estado, conn) -> list[tuple[str, bool]]:
    """Devolve [(descrição, passou?)] para as checagens do caso."""
    chamadas = {c["nome"] for c in estado.chamadas}
    resposta = estado.resposta or ""
    checagens: list[tuple[str, bool]] = []

    # terminação
    terminacao_esp = verificador.get("terminacao", "resposta_final")
    checagens.append((f"terminou por '{terminacao_esp}'",
                      estado.terminacao == terminacao_esp))

    # ferramentas
    for nome in verificador.get("deve_chamar", []):
        checagens.append((f"chamou {nome}", nome in chamadas))
    for nome in verificador.get("nao_deve_chamar", []):
        checagens.append((f"NÃO chamou {nome}", nome not in chamadas))

    # alertas
    if "alertas_esperados" in verificador:
        esperado = {tuple(par) for par in verificador["alertas_esperados"]}
        obtido = _alertas_no_banco(conn)
        rotulo = "banco com exatamente os alertas esperados" if esperado else "banco sem alerta novo"
        checagens.append((f"{rotulo} (esp {len(esperado)}, obt {len(obtido)})", obtido == esperado))

    # padrões na resposta
    for padrao in verificador.get("resposta_deve_casar_todos", []):
        checagens.append((f"resposta casa /{padrao}/",
                          bool(re.search(padrao, resposta, re.I | re.UNICODE))))
    for padrao in verificador.get("resposta_nao_deve_casar", []):
        checagens.append((f"resposta NÃO casa /{padrao}/",
                          not re.search(padrao, resposta, re.I | re.UNICODE)))
    if verificador.get("resposta_deve_casar_algum"):
        padroes = verificador["resposta_deve_casar_algum"]
        checagens.append(("resposta casa ao menos um padrão",
                          any(re.search(p, resposta, re.I | re.UNICODE) for p in padroes)))

    return checagens


# ---------------------------------------------------------------------------
# Executar um caso uma vez
# ---------------------------------------------------------------------------

def executar_caso(caso: dict, repetição: int, *,
                  cliente, cfg: Config, prompt: dict,
                  pasta_logs: Path) -> dict:
    """Executa o caso e devolve {passou, checagens, terminacao, tokens, custo_usd, ms}."""
    criar_banco(cfg.caminho_db)
    conn = conectar(cfg.caminho_db)
    t0 = time.perf_counter()
    try:
        if caso.get("fixture_sql"):
            conn.executescript(caso["fixture_sql"])
            conn.commit()
        log = pasta_logs / f"{caso['id']}_rep{repetição}.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.unlink(missing_ok=True)
        ctx = Contexto(conn, cfg.id_loja, cfg.limite_dias_alerta_validade)

        from src.grafo import executar as _exec
        confirmacao = caso.get("simulacao_confirmacao", "sim")
        confirmar_fn = lambda d: (confirmacao == "sim", f"automat (evals rep{repetição})")

        estado = _exec(caso["entrada"], cliente=cliente, cfg=cfg, ctx=ctx,
                       prompt=prompt, confirmar=confirmar_fn,
                       traj=Trajetoria(log))

        checagens = verificar(caso.get("verificador", {}), estado, conn)
        passou = all(ok for _, ok in checagens)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "id": caso["id"],
            "classe": caso["classe"],
            "repetição": repetição,
            "passou": passou,
            "checagens": [(d, ok) for d, ok in checagens],
            "terminacao": estado.terminacao,
            "tokens": estado.tokens,
            "custo_usd": estado.custo_usd,
            "ms": ms,
            "log": str(log.name),
            "aviso_verificador": estado.aviso_verificador,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Suíte completa
# ---------------------------------------------------------------------------

def rodar_suite(versao: str, casos_filtro: str | None, repeticoes: int,
                pausa_s: int) -> Path:
    cfg = carregar_config()
    prompt = carregar_prompt(cfg.arquivo_prompt)
    cliente = criar_cliente(cfg)

    golden = json.loads(ARQUIVO_GOLDEN.read_text(encoding="utf-8"))
    casos = golden["casos"]
    if casos_filtro:
        casos = [c for c in casos if c["classe"] == casos_filtro]
        if not casos:
            raise SystemExit(f"Nenhum caso com classe={casos_filtro!r}.")

    agora = datetime.now().strftime("%Y%m%d_%H%M")
    pasta_rodada = PASTA_RESULTADOS / f"{versao}_{agora}"
    pasta_rodada.mkdir(parents=True, exist_ok=True)
    pasta_logs = PASTA_LOGS_SUITE / f"{versao}_{agora}"

    todos: list[dict] = []
    for i, caso in enumerate(casos):
        reps = []
        for rep in range(1, repeticoes + 1):
            if todos and pausa_s:
                print(f"  (aguardando {pausa_s}s — limite de taxa do provedor)")
                time.sleep(pausa_s)
            print(f"\n=== {caso['id']} ({caso['classe']}) rep {rep}/{repeticoes} ===")
            print(f"  > {caso['entrada']}")
            resultado = executar_caso(caso, rep, cliente=cliente, cfg=cfg,
                                      prompt=prompt, pasta_logs=pasta_logs)
            reps.append(resultado)
            status = "PASSOU" if resultado["passou"] else "FALHOU"
            print(f"  {status} | terminação: {resultado['terminacao']} | tokens: {resultado['tokens']}")
            if resultado.get("aviso_verificador"):
                print(f"  ⚠ {resultado['aviso_verificador']}")
        # pass^k: todas as repetições passaram
        pass_k = all(r["passou"] for r in reps)
        # pass@k (diagnóstico): ao menos uma passou
        pass_at_k = any(r["passou"] for r in reps)
        bloco = {
            "id": caso["id"],
            "classe": caso["classe"],
            "origem": caso["origem"],
            "pass_k": pass_k,
            "pass_at_k": pass_at_k,
            "repeticoes": reps,
        }
        todos.append(bloco)
        (pasta_rodada / f"{caso['id']}.json").write_text(
            json.dumps(bloco, ensure_ascii=False, indent=2), encoding="utf-8")

    # resumo.json
    resumo = _calcular_resumo(todos, versao, golden["versao"], prompt, cfg, repeticoes)
    (pasta_rodada / "resumo.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    _imprimir_resumo(resumo)
    print(f"\nResultados gravados em: {pasta_rodada}")
    return pasta_rodada


def _calcular_resumo(todos: list[dict], versao_sistema: str, versao_dataset: str,
                     prompt: dict, cfg: Config, repeticoes: int) -> dict:
    classes: dict[str, dict] = {}
    for bloco in todos:
        cl = bloco["classe"]
        if cl not in classes:
            classes[cl] = {"total": 0, "pass_k": 0}
        classes[cl]["total"] += 1
        if bloco["pass_k"]:
            classes[cl]["pass_k"] += 1

    total = len(todos)
    total_pass = sum(1 for b in todos if b["pass_k"])

    # latência (ms) de todas as execuções
    todos_ms = [r["ms"] for b in todos for r in b["repeticoes"]]
    todos_ms_sorted = sorted(todos_ms)
    n = len(todos_ms_sorted)
    p50 = todos_ms_sorted[n // 2] if n else 0
    p95 = todos_ms_sorted[int(n * 0.95)] if n else 0

    # tokens e custo
    todos_tokens = [r["tokens"] for b in todos for r in b["repeticoes"]]
    todos_custo = [r["custo_usd"] for b in todos for r in b["repeticoes"] if r["custo_usd"] is not None]

    # motivos de terminação
    terminacoes: dict[str, int] = {}
    for b in todos:
        for r in b["repeticoes"]:
            t = r["terminacao"] or "desconhecido"
            terminacoes[t] = terminacoes.get(t, 0) + 1

    return {
        "versao_sistema": versao_sistema,
        "versao_dataset": versao_dataset,
        "prompt_arquivo": prompt["arquivo"],
        "prompt_versao": prompt["versao"],
        "prompt_sha": prompt["sha"],
        "modelo": cfg.modelo,
        "temperature": cfg.temperature,
        "repeticoes": repeticoes,
        "data": datetime.now().isoformat(timespec="seconds"),
        "total_casos": total,
        "total_pass_k": total_pass,
        "taxa_pass_k": round(total_pass / total * 100, 1) if total else 0,
        "por_classe": {
            cl: {
                "pass_k": v["pass_k"],
                "total": v["total"],
                "taxa": round(v["pass_k"] / v["total"] * 100, 1),
            }
            for cl, v in classes.items()
        },
        "latencia_p50_ms": p50,
        "latencia_p95_ms": p95,
        "tokens_total": sum(todos_tokens),
        "tokens_por_execucao_media": round(sum(todos_tokens) / len(todos_tokens), 0) if todos_tokens else 0,
        "custo_total_usd": round(sum(todos_custo), 4) if todos_custo else None,
        "terminacoes": terminacoes,
        "origens": {
            o: sum(1 for b in todos if b.get("origem") == o)
            for o in ("producao", "desenvolvimento", "sintetico")
        },
    }


def _imprimir_resumo(r: dict) -> None:
    print(f"\n{'='*60}")
    print(f"DATASET v{r['versao_dataset']}   {r['total_casos']} casos   "
          f"(prod {r['origens']['producao']} · dev {r['origens']['desenvolvimento']} · "
          f"sint {r['origens']['sintetico']})")
    print(f"Sistema v{r['versao_sistema']}   prompt {r['prompt_arquivo']} sha {r['prompt_sha']}   "
          f"modelo {r['modelo']}   temp {r['temperature']}   {r['repeticoes']}x")
    print(f"\n{'classe':<20} {'pass^k':>8} {'total':>6} {'taxa':>7}")
    print("-" * 45)
    for cl, v in r["por_classe"].items():
        print(f"{cl:<20} {v['pass_k']:>8} {v['total']:>6} {v['taxa']:>6.1f}%")
    print("-" * 45)
    print(f"{'MÉDIA':<20} {r['total_pass_k']:>8} {r['total_casos']:>6} {r['taxa_pass_k']:>6.1f}%")
    print(f"\nLatência p50={r['latencia_p50_ms']:.0f}ms p95={r['latencia_p95_ms']:.0f}ms")
    print(f"Terminações: {r['terminacoes']}")


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="python -m evals.rodar")
    p.add_argument("--versao", required=True, help="Versão do sistema (ex.: 1.0.0)")
    p.add_argument("--classe", help="Roda só a classe especificada")
    p.add_argument("--repeticoes", type=int, default=3, help="Repetições por caso (default: 3)")
    p.add_argument("--pausa", type=int, default=0, help="Segundos de espera entre casos")
    args = p.parse_args(argv)
    rodar_suite(args.versao, args.classe, args.repeticoes, args.pausa)
    return 0


if __name__ == "__main__":
    sys.exit(main())
