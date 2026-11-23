"""Terminal do Administrador.

  python -m src.main                      modo interativo (uma pergunta por vez, com histórico)
  python -m src.main "pergunta"           uma pergunta e sai
  opções: --confirmar {perguntar,sim,nao,pausar}  como tratar a confirmação das escritas (padrão: perguntar)
                 pausar = o grafo grava o checkpoint e PARA; a decisão vem depois, de outro terminal:
          --pendentes                       lista as execuções paradas esperando aprovação
          --retomar ID --aprovar|--recusar  decide uma execução parada e continua de onde ela parou
          --por NOME                        quem está decidindo (vai para o log e para o fato/alerta)
          --sem-memoria                     desliga a memória de longo prazo nesta execução
          --recriar-banco                   apaga e recria o banco simulado antes de rodar
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

import dataclasses

from . import checkpoint
from .agente import AGUARDANDO_HUMANO, RESPOSTA_FINAL, Trajetoria, carregar_prompt, criar_cliente, executar
from .config import carregar_config
from .db import conectar, criar_banco
from .ferramentas import Contexto


def confirmar_no_terminal(descricao: str) -> tuple[bool, str]:
    resposta = input(f"\n  >> ACAO DE ESCRITA (reversivel): {descricao}\n  Confirmar? [s/N] ").strip().lower()
    return resposta in ("s", "sim", "y", "yes"), "administrador (terminal)"


def confirmacao_fixa(aprovar: bool):
    rotulo = "sim" if aprovar else "nao"
    return lambda descricao: (aprovar, f"automatico (--confirmar {rotulo})")


def _utf8() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")  # console do Windows costuma vir em cp1252
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8()
    parser = argparse.ArgumentParser(prog="python -m src.main", description="Assistente de estoque do Hydra")
    parser.add_argument("pergunta", nargs="?", help="pergunta em português; sem ela, abre o modo interativo")
    parser.add_argument("--confirmar", choices=("perguntar", "sim", "nao", "pausar"), default=None)
    parser.add_argument("--pendentes", action="store_true")
    parser.add_argument("--retomar", metavar="ID")
    decisao = parser.add_mutually_exclusive_group()
    decisao.add_argument("--aprovar", action="store_true")
    decisao.add_argument("--recusar", action="store_true")
    parser.add_argument("--por", default="administrador (terminal)")
    parser.add_argument("--sem-memoria", action="store_true")
    parser.add_argument("--recriar-banco", action="store_true")
    args = parser.parse_args(argv)

    cfg = carregar_config(exigir_llm=not args.pendentes)
    if args.sem_memoria:
        cfg = dataclasses.replace(cfg, memoria=False)
    if args.pendentes:
        lista = checkpoint.pendentes(cfg.pasta_checkpoints)
        for p in lista:
            print(f"{p['id_execucao']}  (pedido em {p['pedido_em']})\n  pergunta: {p['pergunta']}\n  ação: {p['descricao']}")
        print(f"{len(lista)} execução(ões) aguardando aprovação.")
        return 0
    if args.retomar and not (args.aprovar or args.recusar):
        parser.error("--retomar exige --aprovar ou --recusar")
    modo_conf = args.confirmar or ("pausar" if cfg.modo_confirmacao == "pausar" else "perguntar")
    if args.recriar_banco or not cfg.caminho_db.exists():
        print(f"Criando banco simulado em {criar_banco(cfg.caminho_db)}")
    prompt = carregar_prompt(cfg.arquivo_prompt)
    cliente = criar_cliente(cfg)
    conn = conectar(cfg.caminho_db)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'memoria_semantica'").fetchone():
        conn.close()  # banco criado pela Parte 1, sem as tabelas da Parte 2: recria (os dados são simulados)
        print(f"Banco sem as tabelas da Parte 2; recriando em {criar_banco(cfg.caminho_db)}")
        conn = conectar(cfg.caminho_db)
    ctx = Contexto(conn, cfg.id_loja, cfg.limite_dias_alerta_validade, memoria=cfg.memoria)
    confirmar = {"perguntar": confirmar_no_terminal, "sim": confirmacao_fixa(True),
                 "nao": confirmacao_fixa(False), "pausar": None}[modo_conf]

    def relatar(estado, log) -> int:
        if estado.resposta:
            print(f"\n{estado.resposta}\n")
        elif estado.terminacao == AGUARDANDO_HUMANO:
            print(f"\nParei antes de gravar: a ação precisa da sua aprovação (execução {estado.id_execucao}).\n")
        else:
            print(f"\nNão consegui concluir esta pergunta (motivo: {estado.terminacao}).\n")
        custo = f"US$ {estado.custo_usd:.4f}" if estado.custo_usd is not None else "n/d (sem preços no .env)"
        alertas = ", ".join(f"#{i}" for i in estado.escritas) or "nenhum"
        fatos = ", ".join(f"#{i}" for i in estado.fatos_gravados) or "nenhum"
        print(f"Terminou por: {estado.terminacao} | passos: {estado.passo} | tokens: {estado.tokens} | "
              f"custo: {custo} | alertas registrados: {alertas} | fatos guardados: {fatos}")
        print(f"Execução: {estado.id_execucao} | Log: {log}\n")
        return 0 if estado.terminacao in (RESPOSTA_FINAL, AGUARDANDO_HUMANO) else 1

    if args.retomar:
        from .grafo import retomar
        try:
            dados = checkpoint.carregar(cfg.pasta_checkpoints, args.retomar)
            print(f"Decidindo: {dados['pendente']['descricao']} -> {'APROVADO' if args.aprovar else 'RECUSADO'}")
            estado = retomar(args.retomar, aprovado=args.aprovar, por=args.por, cliente=cliente, cfg=cfg, ctx=ctx)
        except (FileNotFoundError, ValueError, TypeError) as exc:
            print(f"Não foi possível retomar: {exc}")
            conn.close()
            return 1
        codigo = relatar(estado, dados.get("log"))
        conn.close()
        return codigo

    historico: list[dict] = []

    def perguntar(texto: str) -> int:
        log = cfg.pasta_logs / f"execucao_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
        estado = executar(texto, cliente=cliente, cfg=cfg, ctx=ctx, prompt=prompt, confirmar=confirmar,
                          traj=Trajetoria(log), historico=historico,
                          modo_confirmacao="pausar" if modo_conf == "pausar" else "sincrono")
        codigo = relatar(estado, log)
        if estado.terminacao == RESPOSTA_FINAL:  # só guarda no histórico o que terminou bem
            historico.extend([{"role": "user", "content": texto},
                              {"role": "assistant", "content": estado.resposta}])
        return codigo

    try:
        if args.pergunta:
            return perguntar(args.pergunta)
        print("Assistente de estoque do Hydra. Digite sua pergunta (linha vazia ou 'sair' encerra).")
        while (texto := input("Você> ").strip()) and texto.lower() != "sair":
            perguntar(texto)
        return 0
    except (KeyboardInterrupt, EOFError):
        print()
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
