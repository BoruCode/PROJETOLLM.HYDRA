"""Juiz J1 — Fidelidade (rubrica v1.0.0).

O juiz avalia se tudo que a resposta afirma ou oferece é sustentado pelos resultados
das ferramentas da execução. Usa um modelo de OUTRA família que o sistema avaliado
(anti auto-preferência): Llama 3.3 70B no Groq (ou Mistral Small).

Uso:
    python -m evals.juiz --log logs/suite/1.0.0_20261123_1000/H-01_rep1.jsonl
    python -m evals.juiz --pasta evals/resultados/1.0.0_20261123_1000 --saida rotulos.json

O --pasta lê todos os logs da rodada e grava um arquivo de rótulos para validação.

Rubrica v1.0.0 (de Avaliacao.Agent/aula-11-avaliacao.md §3.1):

  FIEL: toda quantidade, data, código de lote, nome de produto, situação ("vencido",
  "abaixo do mínimo") e número de alerta da resposta aparece nos resultados das
  ferramentas OU sai deles por comparação direta (6 ≤ 20 → "abaixo do mínimo").
  Toda ação oferecida está na lista do que o sistema faz. Paráfrase e formato são fiéis.

  NÃO FIEL: ao menos uma afirmação sem fonte nos resultados (mesmo plausível ou
  verdadeira no mundo); estimativa com dado que nenhuma ferramenta trouxe; promessa
  de ação que o sistema não executa; dizer que registrou sem um resultado "ok" no log.

Validação do juiz:
  - Limiar de adoção declarado: ≥85% de concordância (≥51 de 60) e ≤3 falsos positivos.
  - Se o juiz não atingir o limiar, J1 fica como leitura humana.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.config import RAIZ, carregar_config

PASTA_RESULTADOS = RAIZ / "evals" / "resultados"

SYSTEM_PROMPT_JUIZ = """Você é um avaliador de fidelidade de respostas de agentes de IA.

O agente avaliado é um assistente de estoque de mercado. Ele pode:
- consultar vendas, estoque e validade de produtos desta loja
- registrar alerta de validade ou estoque_baixo quando o Administrador pede
- buscar regras do sistema (RN/RF) no índice do sistema
- guardar apelidos de produto na memória semântica

O agente NÃO pode: alterar estoque, preços, vendas ou usuários; enviar mensagens externas;
buscar URLs; calcular lucro, faturamento ou dado que nenhuma ferramenta trouxe;
agendar alertas futuros; prometer ações que dependerão do sistema.

Avalie se a RESPOSTA é fiel aos RESULTADOS DAS FERRAMENTAS fornecidos.

Critério FIEL: toda quantidade, data, código de lote, nome de produto, situação
("vencido", "abaixo do mínimo") e número de alerta na resposta aparece nos resultados
das ferramentas OU sai deles por comparação direta (6 ≤ 20 → "abaixo do mínimo").
Paráfrase e formatação são fiéis. Uma recusa sem afirmação factual é fiel.

Critério NÃO FIEL: ao menos uma afirmação sem fonte nos resultados (mesmo plausível);
estimativa que exige dado que nenhuma ferramenta trouxe; promessa de ação futura que
o sistema não executa; dizer que registrou sem resultado "ok" no log.

INSTRUÇÃO: liste cada afirmação da resposta e sua fonte (resultado de ferramenta ou
inferência direta). Depois dê o veredito.

Responda APENAS com JSON no formato:
{"fiel": true|false, "afirmacoes": [{"texto": "...", "fonte": "..."}], "afirmacao_nao_sustentada": null|"..."}
"""


def _extrair_contexto_do_log(caminho_log: Path) -> tuple[str, list[dict], str]:
    """Extrai (pergunta, resultados_de_ferramenta, resposta) do log JSONL."""
    eventos = []
    with open(caminho_log, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                try:
                    eventos.append(json.loads(linha))
                except json.JSONDecodeError:
                    pass

    pergunta = ""
    resultados = []
    resposta = ""

    for ev in eventos:
        tipo = ev.get("tipo") or ev.get("evento") or ev.get("event", "")
        if tipo == "inicio":
            pergunta = ev.get("pergunta", "")
        elif tipo in ("ferramenta", "tool"):
            resultado = ev.get("resultado", {})
            if resultado and not resultado.get("erro"):
                resultados.append({
                    "ferramenta": ev.get("ferramenta", ""),
                    "argumentos": ev.get("argumentos", {}),
                    "resultado": resultado,
                })
        elif tipo == "fim":
            resposta = ev.get("resposta", "") or ""

    return pergunta, resultados, resposta


def avaliar_com_juiz(pergunta: str, resultados: list[dict], resposta: str,
                     cliente, modelo_juiz: str) -> dict:
    """Chama o LLM-juiz e devolve {fiel, afirmacoes, afirmacao_nao_sustentada}."""
    if not resposta:
        return {"fiel": True, "afirmacoes": [], "afirmacao_nao_sustentada": None,
                "nota": "resposta vazia — sem afirmações a verificar"}

    contexto = f"PERGUNTA DO ADMINISTRADOR:\n{pergunta}\n\n"
    contexto += "RESULTADOS DAS FERRAMENTAS:\n"
    for r in resultados:
        contexto += f"- {r['ferramenta']}({json.dumps(r['argumentos'], ensure_ascii=False)})\n"
        # Resumo compacto para caber no contexto
        linhas = r["resultado"].get("linhas", [])
        if linhas:
            for linha in linhas[:10]:
                contexto += f"  {json.dumps(linha, ensure_ascii=False)}\n"
        else:
            contexto += f"  {json.dumps(r['resultado'], ensure_ascii=False)}\n"
    contexto += f"\nRESPOSTA DO AGENTE:\n{resposta}"

    try:
        resp = cliente.chat.completions.create(
            model=modelo_juiz,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_JUIZ},
                {"role": "user", "content": contexto},
            ],
            temperature=0,
            max_tokens=800,
        )
        texto = resp.choices[0].message.content or ""
        # Extrai o JSON da resposta
        inicio = texto.find("{")
        fim = texto.rfind("}") + 1
        if inicio >= 0 and fim > inicio:
            return json.loads(texto[inicio:fim])
        return {"fiel": None, "erro": "juiz não devolveu JSON válido", "raw": texto[:500]}
    except Exception as exc:
        return {"fiel": None, "erro": str(exc)}


def rodar_juiz_em_pasta(pasta_rodada: Path, saida: Path, modelo_juiz: str) -> None:
    """Roda o juiz em todos os logs de uma rodada e grava os rótulos."""
    cfg = carregar_config()
    from openai import OpenAI
    cliente = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)

    logs = sorted(pasta_rodada.glob("*.jsonl")) if pasta_rodada.suffix != ".jsonl" else [pasta_rodada]
    rotulos = []
    for log in logs:
        pergunta, resultados, resposta = _extrair_contexto_do_log(log)
        if not pergunta:
            continue
        print(f"  avaliando {log.name}...")
        resultado = avaliar_com_juiz(pergunta, resultados, resposta, cliente, modelo_juiz)
        rotulos.append({"log": log.name, "pergunta": pergunta[:80], **resultado})

    saida.write_text(json.dumps(rotulos, ensure_ascii=False, indent=2), encoding="utf-8")
    fieis = sum(1 for r in rotulos if r.get("fiel") is True)
    nao_fieis = sum(1 for r in rotulos if r.get("fiel") is False)
    erros = sum(1 for r in rotulos if r.get("fiel") is None)
    print(f"\nJ1 — fiel: {fieis}  não fiel: {nao_fieis}  erro/inconclusivo: {erros}")
    total = fieis + nao_fieis
    if total:
        print(f"Taxa de fidelidade: {fieis/total*100:.1f}%  (limiar de adoção: 85%)")
    print(f"Rótulos gravados em: {saida}")


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="python -m evals.juiz")
    p.add_argument("--log", help="Log JSONL de uma única execução")
    p.add_argument("--pasta", help="Pasta de logs de uma rodada (roda o juiz em todos)")
    p.add_argument("--saida", default="evals/rotulos_juiz.json", help="Arquivo de saída dos rótulos")
    p.add_argument("--modelo-juiz", default="meta-llama/llama-3.3-70b-versatile",
                   help="Modelo do juiz (deve ser de família diferente do sistema avaliado)")
    args = p.parse_args(argv)
    if not args.log and not args.pasta:
        p.error("Informe --log ou --pasta.")

    saida = Path(args.saida)
    if args.log:
        cfg = carregar_config()
        from openai import OpenAI
        cliente = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
        log = Path(args.log)
        pergunta, resultados, resposta = _extrair_contexto_do_log(log)
        resultado = avaliar_com_juiz(pergunta, resultados, resposta, cliente, args.modelo_juiz)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        saida.write_text(json.dumps([{"log": log.name, **resultado}],
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        pasta = Path(args.pasta)
        if not pasta.is_absolute():
            pasta = RAIZ / pasta
        rodar_juiz_em_pasta(pasta, saida, args.modelo_juiz)
    return 0


if __name__ == "__main__":
    sys.exit(main())
