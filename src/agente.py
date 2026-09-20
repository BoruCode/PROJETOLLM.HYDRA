"""Laço do agente: estado explícito, orçamento, terminação registrada e log da trajetória.

Quem decide o quê:
  MODELO  -> quais ferramentas chamar e com que argumentos; a análise; o texto final.
  CÓDIGO  -> executar SQL, validar regras de negócio, pedir confirmação, contar orçamento, parar, logar.
  HUMANO  -> confirmar cada escrita.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import Config
from .ferramentas import FERRAMENTAS, SCHEMAS, Contexto, erro

# Motivos de parada (o programa sempre diz por que parou).
RESPOSTA_FINAL = "resposta_final"
RESPOSTA_VAZIA = "resposta_vazia"
ORCAMENTO_PASSOS = "orcamento_passos"
ORCAMENTO_TOKENS = "orcamento_tokens"
ORCAMENTO_CUSTO = "orcamento_custo"
ERRO_LLM = "erro_llm"


# --- prompt em arquivo, versionado e carimbado -----------------------------

def carregar_prompt(caminho: str | Path) -> dict:
    """Lê prompts/*.md: cabeçalho '---' com metadados + corpo. O sha entra no log (prompt x modelo x parâmetros)."""
    caminho = Path(caminho)
    bruto = caminho.read_bytes()
    texto = bruto.decode("utf-8")
    meta: dict[str, str] = {}
    corpo = texto
    if texto.startswith("---"):
        _, cabecalho, corpo = texto.split("---", 2)
        for linha in cabecalho.strip().splitlines():
            chave, _, valor = linha.partition(":")
            meta[chave.strip()] = valor.strip()
    return {"arquivo": caminho.name, "id": meta.get("id", caminho.stem), "versao": meta.get("versao", "?"),
            "sha": hashlib.sha256(bruto).hexdigest()[:8], "texto": corpo.strip(), "meta": meta}


# --- estado e orçamento -----------------------------------------------------

@dataclass
class Orcamento:
    max_passos: int
    max_tokens: int
    max_custo_usd: float | None  # None = preços não configurados, teto de custo não se aplica


@dataclass
class Estado:
    passo: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float | None = None
    usage_ausente: bool = False
    chamadas: list = field(default_factory=list)   # {"passo", "nome", "args", "erro"}
    escritas: list = field(default_factory=list)   # ids dos alertas registrados
    resposta: str | None = None
    terminacao: str | None = None
    erro_llm: str | None = None

    @property
    def tokens(self) -> int:
        return self.tokens_entrada + self.tokens_saida

    @property
    def erros_de_ferramenta(self) -> list[str]:
        return [c["erro"] for c in self.chamadas if c["erro"]]


class Trajetoria:
    """Log da trajetória: uma linha JSON por evento (ferramenta, argumentos, resultado, erro) + eco no terminal."""

    def __init__(self, caminho: str | Path | None = None, verboso: bool = True):
        self.caminho = Path(caminho) if caminho else None
        self.verboso = verboso
        if self.caminho:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)

    def evento(self, tipo: str, **dados) -> None:
        linha = {"ts": datetime.now().isoformat(timespec="seconds"), "evento": tipo, **dados}
        if self.caminho:
            with self.caminho.open("a", encoding="utf-8") as arq:
                arq.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
        if self.verboso and (texto := _eco(linha)):
            print(texto)


def _eco(linha: dict) -> str | None:
    if linha["evento"] == "ferramenta":
        res = linha["resultado"]
        if linha.get("erro"):
            resumo = f"ERRO {linha['erro']}"
        elif res.get("ok"):
            resumo = f"ok (alerta #{res['id_alerta']})"
        else:
            resumo = f"{len(res.get('linhas', []))} linha(s)"
        conf = linha.get("confirmacao")
        extra = f" [{'confirmado' if conf['aprovado'] else 'RECUSADO'} por {conf['por']}]" if conf else ""
        args = json.dumps(linha["argumentos"], ensure_ascii=False)
        return f"  [passo {linha['passo']}] {linha['ferramenta']}({args}) -> {resumo}{extra}"
    if linha["evento"] == "erro_llm":
        return f"  ERRO na chamada ao modelo: {linha['erro']}"
    return None


# --- cliente ----------------------------------------------------------------

def criar_cliente(cfg: Config):
    """base_url e chave vêm do .env: trocar de provedor não exige mudar código."""
    from openai import OpenAI  # import tardio: os testes rodam sem a biblioteca instalada
    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)


# --- laço -------------------------------------------------------------------

def executar(pergunta: str, *, cliente, cfg: Config, ctx: Contexto, prompt: dict,
             confirmar: Callable[[str], tuple[bool, str]], traj: Trajetoria,
             historico: tuple | list = ()) -> Estado:
    """Uma pergunta do Administrador, do início ao motivo de parada. Nunca levanta exceção por erro do
    modelo ou de ferramenta: tudo vira estado.terminacao ou resultado de ferramenta."""
    calcula_custo = cfg.preco_entrada_por_milhao is not None and cfg.preco_saida_por_milhao is not None
    orc = Orcamento(cfg.max_passos, cfg.max_tokens, cfg.max_custo_usd if calcula_custo else None)
    estado = Estado()
    mensagens = [{"role": "system", "content": prompt["texto"]}, *historico,
                 {"role": "user", "content": pergunta}]
    traj.evento("inicio", pergunta=pergunta, base_url=cfg.base_url, modelo=cfg.modelo,
                temperature=cfg.temperature, orcamento=asdict(orc),
                prompt={"arquivo": prompt["arquivo"], "versao": prompt["versao"], "sha": prompt["sha"]},
                custo_calculado=calcula_custo)

    while estado.terminacao is None:
        motivo = _orcamento_estourado(estado, orc)
        if motivo:
            estado.terminacao = motivo
            break
        estado.passo += 1

        # ---- ETAPA: chamada ao modelo (única em que o MODELO decide) ---------------------------------
        # Técnica: zero-shot com instruções no prompt de sistema (prompts/sistema_v1.md) + tool calling.
        #   Sem few-shot: são poucas regras, e a dificuldade dos casos vem dos dados, não do formato;
        #   exemplos custariam tokens em TODA chamada.
        # Contrato de saída: (a) tool_calls válidos segundo SCHEMAS, ou (b) texto final em português,
        #   até 6 linhas, sem tabelas. Proibido: inventar número, alterar estoque/produto/venda,
        #   registrar alerta sem pedido explícito, trocar de produto sozinho.
        # O que impede de dar errado: número inventado (RN29), concordar com afirmação errada do
        #   Administrador, escrita fora do escopo (RN28), troca silenciosa de produto, resposta longa.
        # Rede de segurança que NÃO depende do modelo: regras de negócio em código, confirmação humana
        #   e orçamento (passos, tokens, custo).
        argumentos = {"model": cfg.modelo, "messages": mensagens, "tools": SCHEMAS}
        if cfg.temperature is not None:
            argumentos["temperature"] = cfg.temperature
        try:
            resposta = cliente.chat.completions.create(**argumentos)
        except Exception as exc:  # rede, chave, modelo inexistente, limite de taxa...
            estado.terminacao = ERRO_LLM
            estado.erro_llm = f"{type(exc).__name__}: {exc}"
            traj.evento("erro_llm", passo=estado.passo, erro=estado.erro_llm)
            break

        _contabilizar(estado, resposta, cfg, calcula_custo)
        msg = resposta.choices[0].message
        chamadas = list(msg.tool_calls or [])
        traj.evento("passo", passo=estado.passo, tokens_entrada=estado.tokens_entrada,
                    tokens_saida=estado.tokens_saida, custo_usd=estado.custo_usd,
                    pediu_ferramentas=[c.function.name for c in chamadas],
                    usage_ausente=estado.usage_ausente)

        if not chamadas:
            estado.resposta = (msg.content or "").strip()
            estado.terminacao = RESPOSTA_FINAL if estado.resposta else RESPOSTA_VAZIA
            break

        mensagens.append({
            "role": "assistant", "content": msg.content,
            "tool_calls": [{"id": c.id, "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments}}
                           for c in chamadas]})
        for chamada in chamadas:
            resultado = _despachar(chamada, estado, ctx, confirmar, traj)
            mensagens.append({"role": "tool", "tool_call_id": chamada.id,
                              "content": json.dumps(resultado, ensure_ascii=False, default=str)})

    traj.evento("fim", terminacao=estado.terminacao, resposta=estado.resposta, passos=estado.passo,
                tokens_entrada=estado.tokens_entrada, tokens_saida=estado.tokens_saida,
                custo_usd=estado.custo_usd, alertas_registrados=estado.escritas,
                erros_de_ferramenta=estado.erros_de_ferramenta)
    return estado


def _orcamento_estourado(estado: Estado, orc: Orcamento) -> str | None:
    """Checado ANTES de cada chamada ao modelo (uma chamada pode ultrapassar o teto por até o seu tamanho)."""
    if estado.passo >= orc.max_passos:
        return ORCAMENTO_PASSOS
    if estado.tokens >= orc.max_tokens:
        return ORCAMENTO_TOKENS
    if orc.max_custo_usd is not None and (estado.custo_usd or 0) >= orc.max_custo_usd:
        return ORCAMENTO_CUSTO
    return None


def _contabilizar(estado: Estado, resposta, cfg: Config, calcula_custo: bool) -> None:
    uso = getattr(resposta, "usage", None)
    entrada = getattr(uso, "prompt_tokens", None)
    saida = getattr(uso, "completion_tokens", None)
    if entrada is None or saida is None:
        estado.usage_ausente = True  # provedor não informou: o teto de tokens/custo fica cego, e o log avisa
        return
    estado.tokens_entrada += entrada
    estado.tokens_saida += saida
    if calcula_custo:
        estado.custo_usd = (estado.custo_usd or 0.0) + (
            entrada * cfg.preco_entrada_por_milhao + saida * cfg.preco_saida_por_milhao) / 1_000_000


def _despachar(chamada, estado: Estado, ctx: Contexto, confirmar, traj: Trajetoria) -> dict:
    nome = chamada.function.name
    ferramenta = FERRAMENTAS.get(nome)
    argumentos: dict = {}
    confirmacao = None
    inicio = time.perf_counter()

    if ferramenta is None:
        resultado = erro("ferramenta_desconhecida", f"Não existe a ferramenta {nome!r}.",
                         f"Use uma de: {', '.join(FERRAMENTAS)}.")
    else:
        try:
            argumentos = json.loads(chamada.function.arguments or "{}")
            if not isinstance(argumentos, dict):
                raise ValueError("os argumentos devem ser um objeto JSON")
        except ValueError as exc:
            argumentos = {}
            resultado = erro("argumentos_invalidos", f"JSON inválido: {exc}",
                             "Reenvie os argumentos como um objeto JSON conforme o schema.")
        else:
            resultado, confirmacao = _executar(ferramenta, argumentos, ctx, confirmar)

    if ferramenta and ferramenta.escrita and resultado.get("ok"):
        estado.escritas.append(resultado["id_alerta"])
    estado.chamadas.append({"passo": estado.passo, "nome": nome, "args": argumentos, "erro": resultado.get("erro")})
    traj.evento("ferramenta", passo=estado.passo, ferramenta=nome, argumentos=argumentos,
                escrita=bool(ferramenta and ferramenta.escrita),
                reversivel=ferramenta.reversivel if ferramenta else None,
                confirmacao=confirmacao, resultado=resultado, erro=resultado.get("erro"),
                ms=round((time.perf_counter() - inicio) * 1000, 1))
    return resultado


def _executar(ferramenta, argumentos: dict, ctx: Contexto, confirmar):
    """Passo de escrita: VALIDAR (código) -> CONFIRMAR (humano) -> ESCREVER. Leitura vai direto."""
    confirmacao = None
    try:
        if ferramenta.escrita:
            violacao = ferramenta.valida(ctx, **argumentos)
            if violacao:  # nem incomoda o humano com uma escrita que já sabemos inválida
                return violacao, None
            aprovado, quem = confirmar(ferramenta.descreve(ctx, **argumentos))
            confirmacao = {"aprovado": aprovado, "por": quem}
            if not aprovado:
                return erro("nao_confirmado", "O Administrador recusou esta ação.",
                            "Não tente de novo nem insista; diga que nada foi registrado."), confirmacao
        return ferramenta.funcao(ctx, **argumentos), confirmacao
    except TypeError as exc:  # argumento faltando ou que não existe no schema
        return erro("argumentos_invalidos", str(exc), "Confira o schema da ferramenta e reenvie."), confirmacao
    except sqlite3.Error as exc:
        return erro("erro_banco", str(exc), "O banco falhou; tente uma vez mais ou avise o Administrador."), confirmacao
