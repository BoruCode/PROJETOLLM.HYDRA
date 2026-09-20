"""Cronometra a linha de base (seção 2.5 do enunciado): a MESMA tarefa por dois caminhos, N rodadas cada.

  python -m src.baseline                 # 10 rodadas por caminho
  python -m src.baseline --rodadas 5

Como usar: leia o nome do caminho, aperte ENTER para COMEÇAR, faça a tarefa, aperte ENTER quando tiver a resposta
anotada. Digite x + ENTER no fim para descartar a rodada (ex.: foi interrompido). Cada rodada é gravada na hora em
docs/baseline.csv; se o programa for interrompido, ao rodar de novo ele continua de onde parou.
No fim, reescreve o bloco entre <!-- BASELINE:INICIO --> e <!-- BASELINE:FIM --> em docs/case.md.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from .config import RAIZ

TAREFA = "Descobrir quais produtos estão com estoque baixo (nome e quantidade de cada um)"
CAMINHOS = {"hydra": "Hydra sem o agente (telas)", "agente": "Agente (terminal)"}
ARQUIVO_CSV = RAIZ / "docs" / "baseline.csv"
ARQUIVO_CASE = RAIZ / "docs" / "case.md"
INICIO, FIM = "<!-- BASELINE:INICIO -->", "<!-- BASELINE:FIM -->"


def ler_csv(caminho: Path) -> tuple[dict[str, list[float]], float | None]:
    tempos: dict[str, list[float]] = {chave: [] for chave in CAMINHOS}
    volume = None
    if Path(caminho).exists():
        with open(caminho, encoding="utf-8", newline="") as arq:
            for linha in csv.DictReader(arq):
                if linha["caminho"] == "volume_semanal":
                    volume = float(linha["segundos"])
                elif linha["caminho"] in tempos:
                    tempos[linha["caminho"]].append(float(linha["segundos"]))
    return tempos, volume


def gravar_csv(caminho: Path, tempos: dict[str, list[float]], volume: float | None) -> None:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as arq:
        escritor = csv.writer(arq)
        escritor.writerow(["caminho", "rodada", "segundos"])
        for chave, lista in tempos.items():
            for i, segundos in enumerate(lista, 1):
                escritor.writerow([chave, i, segundos])
        if volume is not None:
            escritor.writerow(["volume_semanal", "", volume])


def resumir(tempos: list[float]) -> dict:
    return {"n": len(tempos), "mediana": statistics.median(tempos), "media": statistics.fmean(tempos),
            "minimo": min(tempos), "maximo": max(tempos)}


def ganho_percentual(antes: float, depois: float) -> float:
    """Positivo = o agente é mais rápido; negativo = mais lento."""
    return (antes - depois) / antes * 100


def gerar_bloco(tarefa: str, tempos: dict[str, list[float]], volume: float | None, hoje: date | None = None) -> str:
    hydra, agente = tempos["hydra"], tempos["agente"]
    if not hydra or not agente:
        return ("_Pendente: rode `python -m src.baseline` (10 rodadas por caminho). Este bloco é reescrito com a "
                "tabela, a mediana e a conta assinada por essa medição._")
    rh, ra = resumir(hydra), resumir(agente)
    ganho = ganho_percentual(rh["mediana"], ra["mediana"])
    linhas = [
        f"**Tarefa cronometrada:** {tarefa}.",
        "",
        f"Medido em {(hoje or date.today()):%d/%m/%Y} com o cronômetro do `python -m src.baseline` "
        f"({rh['n']} rodadas no Hydra, {ra['n']} no agente). O tempo do agente inclui digitar a pergunta e ler a resposta.",
        "",
        f"| Rodada | {CAMINHOS['hydra']} (s) | {CAMINHOS['agente']} (s) |",
        "|---|---|---|",
    ]
    for i in range(max(len(hydra), len(agente))):
        h = f"{hydra[i]:g}" if i < len(hydra) else "-"
        a = f"{agente[i]:g}" if i < len(agente) else "-"
        linhas.append(f"| {i + 1} | {h} | {a} |")
    linhas += [
        f"| **Mediana** | **{rh['mediana']:g}** | **{ra['mediana']:g}** |",
        f"| Mínimo a máximo | {rh['minimo']:g} a {rh['maximo']:g} | {ra['minimo']:g} a {ra['maximo']:g} |",
        "",
    ]
    if ganho >= 0:
        conta = (f"**A conta:** de {rh['mediana']:.0f} s para {ra['mediana']:.0f} s por consulta = "
                 f"{ganho:.0f}% de ganho de tempo (mediana de {rh['n']} e {ra['n']} rodadas).")
    else:
        conta = (f"**A conta:** de {rh['mediana']:.0f} s para {ra['mediana']:.0f} s por consulta = o agente foi "
                 f"{abs(ganho):.0f}% MAIS LENTO nesta tarefa (mediana de {rh['n']} e {ra['n']} rodadas). "
                 "Nesta tarefa o ganho não está no tempo.")
    linhas.append(conta)
    if volume:
        horas = (rh["mediana"] - ra["mediana"]) * volume / 3600
        linhas.append(f"Com {volume:g} consultas por semana (informado pelo grupo): {horas:+.2f} h por semana.")
    else:
        linhas.append("Volume semanal de consultas: **pendente** (perguntar a quem faz; sem ele não há conta por semana).")
    linhas += ["",
               "**Ressalva:** estimativa. É uma tarefa, feita por quem conhece o sistema, sobre dados simulados; "
               "não mede o custo de uma resposta errada do agente (ver §2.7)."]
    return "\n".join(linhas)


def atualizar_case(caminho: Path, bloco: str) -> None:
    texto = Path(caminho).read_text(encoding="utf-8")
    assert INICIO in texto and FIM in texto, f"marcadores {INICIO} ... {FIM} não encontrados em {caminho}"
    antes, resto = texto.split(INICIO, 1)
    _, depois = resto.split(FIM, 1)
    Path(caminho).write_text(f"{antes}{INICIO}\n{bloco}\n{FIM}{depois}", encoding="utf-8")


def _numero(texto: str) -> float | None:
    try:
        return float(texto.strip().replace(",", "."))
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="python -m src.baseline")
    parser.add_argument("--rodadas", type=int, default=10)
    args = parser.parse_args(argv)

    tempos, volume = ler_csv(ARQUIVO_CSV)
    print(f"TAREFA (a mesma nos dois caminhos): {TAREFA}.")
    print("Aperte ENTER para começar cada rodada e ENTER de novo quando tiver a resposta anotada.")
    print("Digite x + ENTER no fim para descartar a rodada. O progresso é salvo a cada rodada.")
    try:
        for chave, rotulo in CAMINHOS.items():
            while len(tempos[chave]) < args.rodadas:
                n = len(tempos[chave]) + 1
                input(f"\n[{rotulo}] rodada {n}/{args.rodadas}. ENTER para COMEÇAR... ")
                inicio = time.perf_counter()
                resposta = input("   ENTER ao ter a resposta anotada (x = descartar)... ").strip().lower()
                segundos = round(time.perf_counter() - inicio, 1)
                if resposta == "x":
                    print("   rodada descartada.")
                    continue
                tempos[chave].append(segundos)
                gravar_csv(ARQUIVO_CSV, tempos, volume)
                print(f"   {segundos:g} s registrados.")
        if volume is None:
            volume = _numero(input("\nQuantas vezes por semana o Administrador faz essa consulta? "
                                   "(número; ENTER para deixar pendente) "))
            gravar_csv(ARQUIVO_CSV, tempos, volume)
    except (KeyboardInterrupt, EOFError):
        print(f"\nInterrompido. O que foi medido está em {ARQUIVO_CSV}; rode de novo para continuar.")
        return 1
    bloco = gerar_bloco(TAREFA, tempos, volume)
    atualizar_case(ARQUIVO_CASE, bloco)
    print(f"\n{bloco}\n\nBloco gravado em {ARQUIVO_CASE} e tempos em {ARQUIVO_CSV}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
