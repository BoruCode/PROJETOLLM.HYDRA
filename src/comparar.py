"""Compara os candidatos de dados/candidatos.json nos casos de dados/casos.json (docs/modelos.md, seções 3.2 e 3.3).

  python -m src.comparar                       # todos os candidatos que tiverem chave no .env
  python -m src.comparar --candidato mistral-small
  python -m src.comparar --pausa 90            # espera entre os casos (limite de tokens por minuto do plano gratuito)

Mesmo prompt, mesma temperature, mesmo banco recriado por caso, mesmos verificadores. O que muda é só o modelo.
Cada candidato lê a chave da variável indicada em "chave_env" (GROQ_API_KEY, MISTRAL_API_KEY...). Sem a chave, o
candidato aparece como "não medido" (não é erro).
Saída: logs/comparacao/<id>/<caso>.jsonl, logs/comparacao/resumo.md e o bloco entre
<!-- COMPARACAO:INICIO --> e <!-- COMPARACAO:FIM --> em docs/modelos.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

from .agente import ERRO_LLM, carregar_prompt, criar_cliente
from .avaliar import ARQUIVO_CASOS, executar_caso
from .config import RAIZ, Config, carregar_config

ARQUIVO_CANDIDATOS = RAIZ / "dados" / "candidatos.json"
ARQUIVO_MODELOS = RAIZ / "docs" / "modelos.md"
INICIO, FIM = "<!-- COMPARACAO:INICIO -->", "<!-- COMPARACAO:FIM -->"
EXECUCOES_SEMESTRE = 300  # premissa: desenvolvimento, testes e demonstrações (~60 rodadas de 5 casos)


def custo_usd(entrada: int, saida: int, preco_entrada: float, preco_saida: float) -> float:
    return (entrada * preco_entrada + saida * preco_saida) / 1_000_000


def comparar(candidatos: list[dict], casos: list[dict], cfg_base: Config, prompt: dict, pasta_logs: Path,
             pausa: int = 0, dormir=time.sleep, ambiente=os.environ, criar=criar_cliente) -> list[dict]:
    resultados = []
    ja_rodou = False
    for cand in candidatos:
        chave = ambiente.get(cand["chave_env"], "").strip()
        if not chave:
            resultados.append({"cand": cand, "medido": False, "motivo": f"sem {cand['chave_env']} no .env"})
            continue
        cfg = replace(cfg_base, base_url=cand["base_url"], api_key=chave, modelo=cand["modelo"],
                      preco_entrada_por_milhao=cand["preco_entrada_por_milhao"],
                      preco_saida_por_milhao=cand["preco_saida_por_milhao"])
        cliente = criar(cfg)
        linhas = []
        for caso in casos:
            if ja_rodou and pausa:
                print(f"\n(aguardando {pausa}s para respeitar o limite de taxa do provedor)")
                dormir(pausa)
            ja_rodou = True
            inicio = time.perf_counter()
            r = executar_caso(caso, cliente=cliente, cfg=cfg, prompt=prompt, pasta_logs=pasta_logs / cand["id"])
            e = r["estado"]
            linhas.append({"caso": caso["id"], "passou": r["passou"], "terminacao": e.terminacao,
                           "passos": e.passo, "tokens_entrada": e.tokens_entrada, "tokens_saida": e.tokens_saida,
                           "segundos": time.perf_counter() - inicio})
        resultados.append({"cand": cand, "medido": True, "linhas": linhas})
    return resultados


def resumir_candidato(resultado: dict, execucoes_semestre: int = EXECUCOES_SEMESTRE) -> dict:
    """Médias só sobre os casos que chegaram ao modelo (erro_llm não gasta token e distorceria a média)."""
    linhas = resultado["linhas"]
    validas = [l for l in linhas if l["terminacao"] != ERRO_LLM]
    cand = resultado["cand"]
    resumo = {"passaram": sum(l["passou"] for l in linhas), "total": len(linhas),
              "erros_llm": len(linhas) - len(validas), "medias": None}
    if validas:
        n = len(validas)
        entrada = sum(l["tokens_entrada"] for l in validas) / n
        saida = sum(l["tokens_saida"] for l in validas) / n
        custo = custo_usd(entrada, saida, cand["preco_entrada_por_milhao"], cand["preco_saida_por_milhao"])
        resumo["medias"] = {"segundos": sum(l["segundos"] for l in validas) / n,
                            "passos": sum(l["passos"] for l in validas) / n,
                            "tokens_entrada": entrada, "tokens_saida": saida, "custo": custo,
                            "custo_100": custo * 100, "custo_semestre": custo * execucoes_semestre}
    return resumo


def _celula(linha: dict) -> str:
    if linha["terminacao"] == ERRO_LLM:
        return "ERRO"
    return "OK" if linha["passou"] else "FALHOU"


def gerar_markdown(resultados: list[dict], casos: list[dict], prompt: dict, hoje: date | None = None,
                   execucoes_semestre: int = EXECUCOES_SEMESTRE) -> str:
    ids = [c["id"] for c in casos]
    medidos = [r for r in resultados if r["medido"]]
    linhas = [
        f"_Gerado por `python -m src.comparar` em {(hoje or date.today()):%d/%m/%Y}. Mesmo prompt "
        f"(`{prompt['arquivo']}`, sha {prompt['sha']}), temperature 0, banco recriado a cada caso._",
        "",
        "**Verificação (3.3): resultado de cada caso rotulado**",
        "",
        "| Modelo | " + " | ".join(i.split("_")[0] for i in ids) + " | Passaram | Tempo médio por caso | Chamadas por caso |",
        "|---|" + "---|" * (len(ids) + 3),
    ]
    for r in resultados:
        nome = r["cand"]["nome"]
        if not r["medido"]:
            linhas.append(f"| {nome} | " + " | ".join("-" for _ in ids) + f" | **não medido** ({r['motivo']}) | - | - |")
            continue
        s = resumir_candidato(r, execucoes_semestre)
        por_caso = {l["caso"]: _celula(l) for l in r["linhas"]}
        m = s["medias"]
        aviso = f" ({s['erros_llm']} com erro do provedor)" if s["erros_llm"] else ""
        linhas.append(f"| {nome} | " + " | ".join(por_caso.get(i, "-") for i in ids) +
                      f" | **{s['passaram']} de {s['total']}**{aviso} | "
                      + (f"{m['segundos']:.1f} s | {m['passos']:.1f} |" if m else "- | - |"))
    linhas += ["", "OK = passou em todas as checagens do caso; FALHOU = o modelo respondeu, mas alguma checagem falhou; "
               "ERRO = o provedor recusou a chamada (chave, limite de taxa), então o caso não mede o modelo.", "",
               "**Conta de custo (3.2)**", "",
               "| Modelo | Preço US$/1M (entrada / saída) | Tokens por caso (entrada / saída) | Custo por execução | "
               "Custo por 100 execuções | Custo do semestre |",
               "|---|---|---|---|---|---|"]
    for r in medidos:
        c, s = r["cand"], resumir_candidato(r, execucoes_semestre)
        m = s["medias"]
        preco = f"{c['preco_entrada_por_milhao']:g} / {c['preco_saida_por_milhao']:g}"
        if m:
            linhas.append(f"| {c['nome']} | {preco} | {m['tokens_entrada']:.0f} / {m['tokens_saida']:.0f} | "
                          f"US$ {m['custo']:.5f} | US$ {m['custo_100']:.3f} | US$ {m['custo_semestre']:.2f} |")
        else:
            linhas.append(f"| {c['nome']} | {preco} | sem resposta do provedor | - | - | - |")
    linhas += ["",
               f"Premissa do semestre: {execucoes_semestre} execuções (desenvolvimento, testes e demonstrações). Cada "
               "\"execução\" é um dos casos rotulados, com 1 a 4 chamadas ao modelo (coluna de chamadas por caso). "
               "Os preços são de lista, de agregadores (ver `docs/fontes.md`), e devem ser conferidos na página do provedor."]
    return "\n".join(linhas)


def atualizar_modelos(caminho: Path, bloco: str) -> None:
    texto = Path(caminho).read_text(encoding="utf-8")
    assert INICIO in texto and FIM in texto, f"marcadores {INICIO} ... {FIM} não encontrados em {caminho}"
    antes, resto = texto.split(INICIO, 1)
    _, depois = resto.split(FIM, 1)
    Path(caminho).write_text(f"{antes}{INICIO}\n{bloco}\n{FIM}{depois}", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="python -m src.comparar")
    parser.add_argument("--pausa", type=int, default=60, help="segundos entre os casos (padrão 60)")
    parser.add_argument("--candidato", action="append", help="id de um candidato; repita para escolher vários")
    args = parser.parse_args(argv)

    cfg = carregar_config(exigir_llm=False)
    prompt = carregar_prompt(cfg.arquivo_prompt)
    candidatos = json.loads(ARQUIVO_CANDIDATOS.read_text(encoding="utf-8"))
    if args.candidato:
        candidatos = [c for c in candidatos if c["id"] in args.candidato]
        if not candidatos:
            raise SystemExit(f"Nenhum candidato com esses ids em {ARQUIVO_CANDIDATOS.name}.")
    casos = json.loads(ARQUIVO_CASOS.read_text(encoding="utf-8"))

    pasta = cfg.pasta_logs / "comparacao"
    resultados = comparar(candidatos, casos, cfg, prompt, pasta, pausa=args.pausa)
    bloco = gerar_markdown(resultados, casos, prompt)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "resumo.md").write_text(bloco + "\n", encoding="utf-8")
    if ARQUIVO_MODELOS.exists():
        atualizar_modelos(ARQUIVO_MODELOS, bloco)
    print("\n" + bloco)
    print(f"\nTabelas gravadas em {pasta / 'resumo.md'} e no bloco COMPARACAO de {ARQUIVO_MODELOS}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
