"""Demonstração + verificador: roda os casos de dados/casos.json e confere cada um contra o gabarito.

  python -m src.avaliar                  roda todos os casos (escritas confirmadas automaticamente)
  python -m src.avaliar --caso 02_divergencia

O verificador confere fatos objetivos, sem depender de "dá para ver que está certo":
  - o estado final do banco (alertas_agente) contra o conjunto esperado;
  - quais ferramentas foram (ou não) chamadas;
  - o motivo de parada;
  - padrões (regex) na resposta, para números e nomes que vieram dos dados.
Uma execução por caso, sobre um banco recriado do zero. Logs em logs/<id>.jsonl e logs/resumo.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from .agente import RESPOSTA_FINAL, Estado, Trajetoria, carregar_prompt, criar_cliente, executar
from .config import RAIZ, Config, carregar_config
from .db import conectar, criar_banco
from .ferramentas import Contexto

ARQUIVO_CASOS = RAIZ / "dados" / "casos.json"


def alertas_no_banco(conn) -> set[tuple]:
    linhas = conn.execute("""
        SELECT p.nome, l.codigo_lote FROM alertas_agente a
          JOIN produtos p ON p.id_produto = a.id_produto
          LEFT JOIN lotes l ON l.id_lote = a.id_lote
         WHERE a.status = 'aberto'""").fetchall()
    return {(linha["nome"], linha["codigo_lote"]) for linha in linhas}


def verificar(regras: dict, estado: Estado, conn) -> list[tuple[str, bool]]:
    """Devolve [(descrição da checagem, passou?)]."""
    chamadas = {c["nome"] for c in estado.chamadas}
    resposta = estado.resposta or ""
    checagens = [(f"terminou por '{regras.get('terminacao', RESPOSTA_FINAL)}'",
                  estado.terminacao == regras.get("terminacao", RESPOSTA_FINAL))]
    for nome in regras.get("deve_chamar", []):
        checagens.append((f"chamou {nome}", nome in chamadas))
    for nome in regras.get("nao_deve_chamar", []):
        checagens.append((f"NÃO chamou {nome}", nome not in chamadas))
    if "alertas_esperados" in regras:
        esperado = {tuple(par) for par in regras["alertas_esperados"]}
        obtido = alertas_no_banco(conn)
        rotulo = "banco com exatamente os alertas esperados" if esperado else "banco sem nenhum alerta novo"
        checagens.append((f"{rotulo} (esperado {len(esperado)}, obtido {len(obtido)})", obtido == esperado))
    for padrao in regras.get("resposta_deve_casar_todos", []):
        checagens.append((f"resposta casa /{padrao}/", bool(re.search(padrao, resposta, re.I))))
    if regras.get("resposta_deve_casar_algum"):
        padroes = regras["resposta_deve_casar_algum"]
        checagens.append((f"resposta casa ao menos um de {padroes}",
                          any(re.search(p, resposta, re.I) for p in padroes)))
    return checagens


def executar_caso(caso: dict, *, cliente, cfg: Config, prompt: dict, pasta_logs: Path) -> dict:
    criar_banco(cfg.caminho_db)  # banco limpo: os casos não contaminam um ao outro
    conn = conectar(cfg.caminho_db)
    try:
        log = pasta_logs / f"{caso['id']}.jsonl"
        log.unlink(missing_ok=True)
        ctx = Contexto(conn, cfg.id_loja, cfg.limite_dias_alerta_validade)
        print(f"\n=== {caso['id']} ({caso['tipo']}) ===\n> {caso['entrada']}")
        estado = executar(caso["entrada"], cliente=cliente, cfg=cfg, ctx=ctx, prompt=prompt,
                          confirmar=lambda d: (True, "automatico (src.avaliar)"), traj=Trajetoria(log))
        checagens = verificar(caso["verificador"], estado, conn)
        passou = all(ok for _, ok in checagens)
        print(f"Resposta: {estado.resposta or '(sem resposta: ' + str(estado.terminacao) + ')'}")
        print(f"Resultado: {'PASSOU' if passou else 'FALHOU'}  ({sum(ok for _, ok in checagens)}/{len(checagens)} checagens)")
        return {"caso": caso, "estado": estado, "checagens": checagens, "passou": passou, "log": log.name}
    finally:
        conn.close()


def escrever_resumo(resultados: list[dict], cfg: Config, prompt: dict, destino: Path) -> None:
    aprovados = sum(r["passou"] for r in resultados)
    linhas = [
        "# Resumo da demonstração",
        "",
        f"- Data: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Carimbo: prompt `{prompt['arquivo']}` v{prompt['versao']} (sha {prompt['sha']}) x modelo `{cfg.modelo}` "
        f"x temperature `{cfg.temperature}` x orçamento (passos {cfg.max_passos}, tokens {cfg.max_tokens})",
        f"- Escritas confirmadas automaticamente pelo avaliador (num uso real, o Administrador confirma uma a uma).",
        f"- **Resultado: {aprovados} de {len(resultados)} casos passaram.**",
        "",
        "| Caso | Tipo | Passou | Terminou por | Passos | Tokens | Alertas | Erros de ferramenta |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in resultados:
        e = r["estado"]
        linhas.append(f"| {r['caso']['id']} | {r['caso']['tipo']} | {'sim' if r['passou'] else '**NÃO**'} | "
                      f"{e.terminacao} | {e.passo} | {e.tokens} | {len(e.escritas)} | "
                      f"{', '.join(e.erros_de_ferramenta) or '-'} |")
    for r in resultados:
        e = r["estado"]
        linhas += ["", f"## {r['caso']['id']}", "", f"_{r['caso']['descricao']}_", "",
                   f"**Entrada:** {r['caso']['entrada']}", "", "**Trajetória:**", ""]
        for c in e.chamadas:
            args = json.dumps(c["args"], ensure_ascii=False)
            linhas.append(f"{c['passo']}. `{c['nome']}({args})`" + (f" -> ERRO `{c['erro']}`" if c["erro"] else ""))
        if not e.chamadas:
            linhas.append("_(nenhuma ferramenta chamada)_")
        linhas += ["", "**Resposta:**", "", f"> {(e.resposta or '(sem resposta)').replace(chr(10), chr(10) + '> ')}",
                   "", "**Checagens:**", ""]
        linhas += [f"- [{'x' if ok else ' '}] {desc}" for desc, ok in r["checagens"]]
        linhas += ["", f"Log completo: `logs/{r['log']}`"]
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="python -m src.avaliar")
    parser.add_argument("--caso", help="roda só o caso com este id")
    parser.add_argument("--pausa", type=int, default=0, help="segundos de espera entre os casos (limite de taxa do provedor)")
    args = parser.parse_args(argv)

    cfg = carregar_config()
    prompt = carregar_prompt(cfg.arquivo_prompt)
    cliente = criar_cliente(cfg)
    casos = json.loads(ARQUIVO_CASOS.read_text(encoding="utf-8"))
    if args.caso:
        casos = [c for c in casos if c["id"] == args.caso]
        if not casos:
            raise SystemExit(f"Caso {args.caso!r} não existe em {ARQUIVO_CASOS.name}.")

    resultados = []
    for i, c in enumerate(casos):
        if i and args.pausa:
            print(f"\n(aguardando {args.pausa}s para respeitar o limite de taxa do provedor)")
            time.sleep(args.pausa)
        resultados.append(executar_caso(c, cliente=cliente, cfg=cfg, prompt=prompt, pasta_logs=cfg.pasta_logs))
    if not args.caso:  # o resumo cobre a rodada completa; rodar um caso só não sobrescreve
        escrever_resumo(resultados, cfg, prompt, cfg.pasta_logs / "resumo.md")
    aprovados = sum(r["passou"] for r in resultados)
    print(f"\n{aprovados} de {len(resultados)} casos passaram." +
          ("" if args.caso else f" Resumo em {cfg.pasta_logs / 'resumo.md'}"))
    return 0 if aprovados == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
