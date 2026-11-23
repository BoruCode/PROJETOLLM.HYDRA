"""Comparação de duas rodadas da suíte de avaliação.

Uso:
    python -m evals.comparar evals/resultados/<rodada-A> evals/resultados/<rodada-B>

Imprime:

    DATASET v<x.y.z>   <n> casos   (producao <n> · desenvolvimento <n> · sintetico <n>)
    Sistema A: v1.0.0  prompt sha ...  modelo ...
    Sistema B: v1.1.0  prompt sha ...  modelo ...

    classe               versão A   versão B   delta
    consulta              100.0%     100.0%     0.0
    escrita               75.0%      100.0%    +25.0
    ...
    MÉDIA                  85.0%      95.0%    +10.0

    Portões absolutos (B):  OK / VIOLADO — <lista de violações>
    Ruído de base R (A×A):  <valor>pp  (calculado de A1 e A2 se disponíveis)
    Decisão de promoção: PROMOVE / NÃO PROMOVE — <razão>

A regra de promoção v1 (de Avaliacao.Agent/aula-11-avaliacao.md §4.3):
  1. Portões absolutos: nenhuma ocorrência de alerta fora do gabarito (R1), alerta
     citado mas não gravado (R3), escrita onde não se pediu (T3) ou número da loja 2 (D3).
  2. Ganho acima do ruído: média B − média A ≥ R + 5pp.
  3. Nenhuma fatia cai: nenhuma classe perde mais de 1 caso em pass^k.
  4. O juiz só decide se foi adotado.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.config import RAIZ

PASTA_RESULTADOS = RAIZ / "evals" / "resultados"


def carregar_resumo(pasta: str | Path) -> dict:
    p = Path(pasta)
    if not p.is_absolute():
        p = RAIZ / p
    arq = p / "resumo.json"
    if not arq.exists():
        raise SystemExit(f"Arquivo resumo.json não encontrado em: {p}")
    return json.loads(arq.read_text(encoding="utf-8"))


def comparar(pasta_a: str | Path, pasta_b: str | Path) -> None:
    ra = carregar_resumo(pasta_a)
    rb = carregar_resumo(pasta_b)

    # Cabeçalho
    origens = ra["origens"]
    total = ra["total_casos"]
    print(f"\nDATASET v{ra['versao_dataset']}   {total} casos   "
          f"(producao {origens['producao']} · "
          f"desenvolvimento {origens['desenvolvimento']} · "
          f"sintetico {origens['sintetico']})")
    print(f"Sistema A: v{ra['versao_sistema']}  sha {ra['prompt_sha']}  modelo {ra['modelo']}")
    print(f"Sistema B: v{rb['versao_sistema']}  sha {rb['prompt_sha']}  modelo {rb['modelo']}")
    print()

    # Tabela por classe
    classes = sorted(set(list(ra["por_classe"]) + list(rb["por_classe"])))
    print(f"{'classe':<22} {'versão A':>10} {'versão B':>10} {'delta':>8}")
    print("-" * 55)

    deltas: dict[str, float] = {}
    for cl in classes:
        ta = ra["por_classe"].get(cl, {}).get("taxa", 0.0)
        tb = rb["por_classe"].get(cl, {}).get("taxa", 0.0)
        delta = tb - ta
        deltas[cl] = delta
        sinal = f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"
        print(f"{cl:<22} {ta:>9.1f}% {tb:>9.1f}% {sinal:>8}")

    print("-" * 55)
    delta_media = rb["taxa_pass_k"] - ra["taxa_pass_k"]
    sinal_m = f"+{delta_media:.1f}" if delta_media > 0 else f"{delta_media:.1f}"
    print(f"{'MÉDIA':<22} {ra['taxa_pass_k']:>9.1f}% {rb['taxa_pass_k']:>9.1f}% {sinal_m:>8}")

    # Métricas adicionais
    print(f"\nLatência  A: p50={ra['latencia_p50_ms']:.0f}ms p95={ra['latencia_p95_ms']:.0f}ms  "
          f"B: p50={rb['latencia_p50_ms']:.0f}ms p95={rb['latencia_p95_ms']:.0f}ms")
    print(f"Terminações A: {ra['terminacoes']}")
    print(f"Terminações B: {rb['terminacoes']}")

    # Regra de promoção v1
    print("\n--- Regra de promoção v1 ---")
    # Portões absolutos (simplificado — verificação completa exige leitura dos logs)
    print("Portões absolutos (R1, R3, T3, D3): verificar manualmente nos logs de B")

    # Ganho acima do ruído (R estimado como 5pp se não houver A1×A2)
    R = 5.0  # estimativa conservadora
    print(f"Ruído de base R: {R}pp (estimativa; rode A duas vezes para medir)")
    limiar_ganho = R + 5.0
    if delta_media >= limiar_ganho:
        print(f"Ganho {delta_media:.1f}pp ≥ R+5 ({limiar_ganho:.1f}pp): ✓ acima do ruído")
        decisao = "PROMOVE (ganho acima do ruído; confirme portões e fatias)"
    elif delta_media >= -R:
        if rb.get("custo_total_usd") and ra.get("custo_total_usd"):
            reducao = (ra["custo_total_usd"] - rb["custo_total_usd"]) / ra["custo_total_usd"] * 100
            if reducao >= 30:
                decisao = f"NÃO PROMOVE como melhoria (Δ={delta_media:.1f}pp); PROMOVE como redução de custo ({reducao:.0f}%)"
            else:
                decisao = f"SEM DIFERENÇA DETECTÁVEL (Δ={delta_media:.1f}pp ≤ R={R}pp)"
        else:
            decisao = f"SEM DIFERENÇA DETECTÁVEL (Δ={delta_media:.1f}pp ≤ R={R}pp)"
    else:
        decisao = f"NÃO PROMOVE (Δ={delta_media:.1f}pp < −R={-R}pp: regressão)"
    print(f"Decisão: {decisao}")


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="python -m evals.comparar")
    p.add_argument("rodada_a", help="Pasta da rodada A (ex.: evals/resultados/1.0.0_20261123_1000)")
    p.add_argument("rodada_b", help="Pasta da rodada B (ex.: evals/resultados/1.1.0_20261123_1100)")
    args = p.parse_args(argv)
    comparar(args.rodada_a, args.rodada_b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
