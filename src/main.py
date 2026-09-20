"""Terminal do Administrador.

  python -m src.main                      modo interativo (uma pergunta por vez, com histórico)
  python -m src.main "pergunta"           uma pergunta e sai
  opções: --confirmar {perguntar,sim,nao}   como tratar a confirmação das escritas (padrão: perguntar)
          --recriar-banco                   apaga e recria o banco simulado antes de rodar
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from .agente import RESPOSTA_FINAL, Trajetoria, carregar_prompt, criar_cliente, executar
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
    parser.add_argument("--confirmar", choices=("perguntar", "sim", "nao"), default="perguntar")
    parser.add_argument("--recriar-banco", action="store_true")
    args = parser.parse_args(argv)

    cfg = carregar_config()
    if args.recriar_banco or not cfg.caminho_db.exists():
        print(f"Criando banco simulado em {criar_banco(cfg.caminho_db)}")
    prompt = carregar_prompt(cfg.arquivo_prompt)
    cliente = criar_cliente(cfg)
    conn = conectar(cfg.caminho_db)
    ctx = Contexto(conn, cfg.id_loja, cfg.limite_dias_alerta_validade)
    confirmar = {"perguntar": confirmar_no_terminal, "sim": confirmacao_fixa(True),
                 "nao": confirmacao_fixa(False)}[args.confirmar]

    historico: list[dict] = []

    def perguntar(texto: str) -> int:
        log = cfg.pasta_logs / f"execucao_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
        estado = executar(texto, cliente=cliente, cfg=cfg, ctx=ctx, prompt=prompt, confirmar=confirmar,
                          traj=Trajetoria(log), historico=historico)
        if estado.resposta:
            print(f"\n{estado.resposta}\n")
        else:
            print(f"\nNão consegui concluir esta pergunta (motivo: {estado.terminacao}).\n")
        custo = f"US$ {estado.custo_usd:.4f}" if estado.custo_usd is not None else "n/d (sem preços no .env)"
        alertas = ", ".join(f"#{i}" for i in estado.escritas) or "nenhum"
        print(f"Terminou por: {estado.terminacao} | passos: {estado.passo} | tokens: {estado.tokens} | "
              f"custo: {custo} | alertas registrados: {alertas}")
        print(f"Log: {log}\n")
        if estado.terminacao == RESPOSTA_FINAL:  # só guarda no histórico o que terminou bem
            historico.extend([{"role": "user", "content": texto},
                              {"role": "assistant", "content": estado.resposta}])
        return 0 if estado.terminacao == RESPOSTA_FINAL else 1

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
