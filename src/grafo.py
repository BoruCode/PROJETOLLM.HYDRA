"""O agente como grafo explícito (Parte 2).

Cada nó é uma função que recebe a Execucao (o estado) e devolve o nome do próximo nó. As arestas
permitidas estão em ARESTAS, e o motor recusa qualquer transição fora delas: o fluxo é o desenho, não
uma consequência do código.

    preparar ──> orcamento ──(estourou)──────────────────────────────> finalizar ──> FIM
                    │                                                     ^
                    v                                                     │
                  modelo ──(texto final | erro do provedor)───────────────┤
                    │ └──(chamada de ferramenta fora do schema)──> orcamento
                    │ pede ferramenta(s)                                  │
                    v                                                     │
               ferramentas ──(fila vazia)──> orcamento                    │
                    │ escrita válida e modo "pausar"                      │
                    v                                                     │
                  pausar ──> FIM   (checkpoint: status aguardando_humano) │
                                                                          │
    retomar (outro processo, horas depois) ──> ferramentas ──> ... ───────┘

Quem decide em cada nó:
    preparar     CÓDIGO   monta a janela: prompt + memória de longo prazo (com teto) + histórico + pergunta
    orcamento    CÓDIGO   passos, tokens, custo
    modelo       MODELO   que ferramenta chamar, com que argumentos; o texto final
    ferramentas  CÓDIGO   executa leitura; numa escrita: VALIDA as regras, depois pede ao HUMANO
    pausar       CÓDIGO   grava o checkpoint e para; a decisão é do HUMANO, quando ele puder
    retomar      CÓDIGO   recarrega o checkpoint, VALIDA DE NOVO (o mundo mudou) e só então escreve
    finalizar    CÓDIGO   grava o episódio (memória episódica) e o fim do log
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Callable

from . import checkpoint
from .agente import (AGUARDANDO_HUMANO, ERRO_LLM, RESPOSTA_FINAL, RESPOSTA_VAZIA, Estado, Orcamento,
                     Trajetoria, _contabilizar, _orcamento_estourado, carregar_prompt)
from .config import Config
from .ferramentas import FERRAMENTAS, SCHEMAS, Contexto, erro

VERSAO_GRAFO = "2.0.0"
FIM = "FIM"

ARESTAS: dict[str, set[str]] = {
    "preparar": {"orcamento"},
    "orcamento": {"modelo", "finalizar"},
    "modelo": {"ferramentas", "finalizar", "orcamento"},  # orcamento: chamada de ferramenta inválida, refaz
    "ferramentas": {"orcamento", "pausar"},
    "pausar": {FIM},
    "retomar": {"ferramentas"},
    "finalizar": {FIM},
}


@dataclass
class Execucao:
    """O estado completo que atravessa o grafo. Tudo o que precisa sobreviver a uma pausa vai no checkpoint."""
    pergunta: str
    cliente: object
    cfg: Config
    ctx: Contexto
    prompt: dict
    traj: Trajetoria
    confirmar: Callable[[str], tuple[bool, str]] | None
    modo: str = "sincrono"                      # "sincrono" (confirma na hora) | "pausar" (para e espera)
    estado: Estado = field(default_factory=Estado)
    orcamento: Orcamento | None = None
    calcula_custo: bool = False
    mensagens: list = field(default_factory=list)
    fila: list = field(default_factory=list)    # chamadas de ferramenta ainda não executadas: {id, name, arguments}
    pendente: dict | None = None                # a escrita que espera o humano
    decisao: dict | None = None                 # {aprovado, por, em}: preenchido na retomada
    memoria_lida: dict = field(default_factory=dict)
    historico_tamanho: int = 0


# ==================================================================================================
# Motor
# ==================================================================================================

def rodar(ex: Execucao, inicio: str) -> Estado:
    no = inicio
    while no != FIM:
        ex.estado.caminho.append(no)
        proximo = NOS[no](ex)
        if proximo not in ARESTAS[no]:
            raise RuntimeError(f"transição fora do grafo: {no} -> {proximo}")
        no = proximo
    return ex.estado


# ==================================================================================================
# Nós
# ==================================================================================================

def no_preparar(ex: Execucao) -> str:
    sistema = ex.prompt["texto"]
    if ex.ctx.memoria:
        from .memoria import bloco_de_contexto, hash_memoria
        bloco, ex.memoria_lida = bloco_de_contexto(ex.ctx, ex.pergunta)
        ex.memoria_lida["hash"] = hash_memoria(ex.ctx)
        sistema += bloco
    ex.mensagens = [{"role": "system", "content": sistema}, *ex.mensagens,
                    {"role": "user", "content": ex.pergunta}]
    ex.traj.evento("inicio", pergunta=ex.pergunta, base_url=ex.cfg.base_url, modelo=ex.cfg.modelo,
                   temperature=ex.cfg.temperature, orcamento=asdict(ex.orcamento),
                   prompt={"arquivo": ex.prompt["arquivo"], "versao": ex.prompt["versao"], "sha": ex.prompt["sha"]},
                   custo_calculado=ex.calcula_custo, id_execucao=ex.estado.id_execucao, grafo=VERSAO_GRAFO,
                   modo_confirmacao=ex.modo, memoria=ex.memoria_lida or None)
    for d in ex.memoria_lida.get("descartes", []):
        ex.traj.evento("memoria_descartada", **d)
    _salvar(ex, "em_andamento")
    return "orcamento"


def no_orcamento(ex: Execucao) -> str:
    motivo = _orcamento_estourado(ex.estado, ex.orcamento)
    if motivo:
        ex.estado.terminacao = motivo
        return "finalizar"
    return "modelo"


def _chamada_invalida(exc: Exception) -> bool:
    """Erro 400 'tool_use_failed' (Groq): a chamada de ferramenta gerada não bateu com o schema."""
    return getattr(exc, "code", None) == "tool_use_failed" or "tool_use_failed" in str(exc)


def no_modelo(ex: Execucao) -> str:
    estado, cfg = ex.estado, ex.cfg
    estado.passo += 1
    argumentos = {"model": cfg.modelo, "messages": ex.mensagens, "tools": SCHEMAS}
    if cfg.temperature is not None:
        argumentos["temperature"] = cfg.temperature
    try:
        resposta = ex.cliente.chat.completions.create(**argumentos)
    except Exception as exc:  # rede, chave, modelo inexistente, limite de taxa...
        if _chamada_invalida(exc):
            # O provedor recusou a chamada de ferramenta gerada (ex.: tipo "valididade" fora do enum). Não é falha
            # do provedor: o modelo pode refazer. Devolve o erro a ele e volta ao orçamento, que limita as tentativas.
            ex.traj.evento("chamada_invalida", passo=estado.passo, erro=f"{type(exc).__name__}: {exc}")
            ex.mensagens.append({"role": "user", "content": (
                "[sistema] A sua última chamada de ferramenta foi recusada pelo provedor por não seguir o schema: "
                f"{exc}. Refaça a chamada com argumentos válidos.")})
            return "orcamento"
        estado.terminacao = ERRO_LLM
        estado.erro_llm = f"{type(exc).__name__}: {exc}"
        ex.traj.evento("erro_llm", passo=estado.passo, erro=estado.erro_llm)
        return "finalizar"

    _contabilizar(estado, resposta, cfg, ex.calcula_custo)
    # Span chat (OTel GenAI)
    try:
        from .otel import span_chat
        with span_chat(estado.passo, cfg.modelo,
                       estado.tokens_entrada, estado.tokens_saida):
            pass  # o span já foi aberto e fechado, apenas registramos os tokens
    except Exception:
        pass
    msg = resposta.choices[0].message
    chamadas = list(msg.tool_calls or [])
    ex.traj.evento("passo", passo=estado.passo, tokens_entrada=estado.tokens_entrada,
                   tokens_saida=estado.tokens_saida, custo_usd=estado.custo_usd,
                   pediu_ferramentas=[c.function.name for c in chamadas], usage_ausente=estado.usage_ausente)
    if not chamadas:
        estado.resposta = (msg.content or "").strip()
        estado.terminacao = RESPOSTA_FINAL if estado.resposta else RESPOSTA_VAZIA
        return "finalizar"

    ex.fila = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments} for c in chamadas]
    ex.mensagens.append({"role": "assistant", "content": msg.content,
                         "tool_calls": [{"id": c["id"], "type": "function",
                                         "function": {"name": c["name"], "arguments": c["arguments"]}}
                                        for c in ex.fila]})
    _salvar(ex, "em_andamento")
    return "ferramentas"


def no_ferramentas(ex: Execucao) -> str:
    while ex.fila:
        chamada = ex.fila[0]
        inicio = time.perf_counter()
        ferramenta, argumentos, resultado = _preparar_chamada(chamada)
        confirmacao = None
        if resultado is None:
            if not ferramenta.escrita:
                resultado = _rodar(lambda: ferramenta.funcao(ex.ctx, **argumentos))
            else:
                violacao = _rodar(lambda: ferramenta.valida(ex.ctx, **argumentos) or {})
                if violacao:  # nem incomoda o humano com uma escrita que já sabemos inválida
                    resultado = violacao
                else:
                    descricao = ferramenta.descreve(ex.ctx, **argumentos)
                    if ex.modo == "pausar":
                        ex.pendente = {"tool_call_id": chamada["id"], "ferramenta": ferramenta.nome,
                                       "argumentos": argumentos, "descricao": descricao,
                                       "chave_idempotencia": _chave(ex, chamada),
                                       "pedido_em": datetime.now().isoformat(timespec="seconds")}
                        return "pausar"
                    aprovado, quem = ex.confirmar(descricao)
                    confirmacao = {"aprovado": aprovado, "por": quem}
                    resultado = _escrever(ex, chamada, ferramenta, argumentos, aprovado, quem)
        _registrar(ex, chamada, ferramenta, argumentos, resultado, confirmacao, inicio)
    return "orcamento"


def no_pausar(ex: Execucao) -> str:
    ex.estado.terminacao = AGUARDANDO_HUMANO
    ex.traj.evento("pausa", id_execucao=ex.estado.id_execucao, descricao=ex.pendente["descricao"],
                   ferramenta=ex.pendente["ferramenta"], argumentos=ex.pendente["argumentos"],
                   chave_idempotencia=ex.pendente["chave_idempotencia"])
    _salvar(ex, "aguardando_humano")
    ex.traj.evento("fim", terminacao=ex.estado.terminacao, resposta=None, passos=ex.estado.passo,
                   tokens_entrada=ex.estado.tokens_entrada, tokens_saida=ex.estado.tokens_saida,
                   custo_usd=ex.estado.custo_usd, alertas_registrados=ex.estado.escritas,
                   fatos_gravados=ex.estado.fatos_gravados, erros_de_ferramenta=ex.estado.erros_de_ferramenta,
                   caminho=ex.estado.caminho)
    return FIM


def no_retomar(ex: Execucao) -> str:
    """A decisão humana chegou. O mundo pode ter mudado desde a pausa: a regra é validada DE NOVO."""
    pend, dec = ex.pendente, ex.decisao
    chamada = ex.fila[0]
    if chamada["id"] != pend["tool_call_id"]:
        raise RuntimeError("checkpoint inconsistente: o pendente não é a próxima chamada da fila")
    inicio = time.perf_counter()
    ferramenta, argumentos, _ = _preparar_chamada(chamada)
    confirmacao = {"aprovado": dec["aprovado"], "por": dec["por"], "em": dec["em"], "pedido_em": pend["pedido_em"]}
    resultado = None
    if dec["aprovado"]:
        violacao = _rodar(lambda: ferramenta.valida(ex.ctx, **argumentos) or {})
        if violacao:
            resultado = {**violacao, "revalidado_na_retomada": True}
    if resultado is None:
        resultado = _escrever(ex, chamada, ferramenta, argumentos, dec["aprovado"], dec["por"])
    ex.pendente = None
    _registrar(ex, chamada, ferramenta, argumentos, resultado, confirmacao, inicio)
    return "ferramentas"


def no_finalizar(ex: Execucao) -> str:
    estado = ex.estado
    episodio = None
    if ex.ctx.memoria:
        from .memoria import gravar_episodio
        try:
            episodio = gravar_episodio(ex.ctx, estado.id_execucao, ex.pergunta, estado, ex.prompt["versao"])
        except sqlite3.Error as exc:  # memória é auxiliar: falhar aqui não pode apagar a resposta
            ex.traj.evento("memoria_erro", erro=str(exc))
    # Controle 3 (ASI09): verificar que lotes citados na resposta vieram de ferramentas desta execução.
    if estado.resposta:
        try:
            from .verificar import verificar_lotes_na_resposta
            lotes_sem_fonte = verificar_lotes_na_resposta(estado.resposta, estado.chamadas)
            if lotes_sem_fonte:
                estado.aviso_verificador = f"⚠ lote(s) sem fonte na resposta: {lotes_sem_fonte}"
                ex.traj.evento("aviso_verificador", lotes_sem_fonte=lotes_sem_fonte)
        except Exception:  # fail-open: a falha do verificador não apaga a resposta
            pass
    _salvar(ex, "encerrada")
    ex.traj.evento("fim", terminacao=estado.terminacao, resposta=estado.resposta, passos=estado.passo,
                   tokens_entrada=estado.tokens_entrada, tokens_saida=estado.tokens_saida,
                   custo_usd=estado.custo_usd, alertas_registrados=estado.escritas,
                   erros_de_ferramenta=estado.erros_de_ferramenta,
                   **({"fatos_gravados": estado.fatos_gravados, "episodio": episodio, "caminho": estado.caminho}
                      if ex.ctx.memoria or ex.modo == "pausar" or estado.fatos_gravados else {}))
    return FIM


NOS: dict[str, Callable[[Execucao], str]] = {
    "preparar": no_preparar, "orcamento": no_orcamento, "modelo": no_modelo, "ferramentas": no_ferramentas,
    "pausar": no_pausar, "retomar": no_retomar, "finalizar": no_finalizar,
}


# ==================================================================================================
# Auxiliares dos nós
# ==================================================================================================

def _preparar_chamada(chamada: dict):
    """(ferramenta, argumentos, resultado_de_erro_ou_None). Erro de nome ou de JSON vira dado para o modelo."""
    ferramenta = FERRAMENTAS.get(chamada["name"])
    if ferramenta is None:
        return None, {}, erro("ferramenta_desconhecida", f"Não existe a ferramenta {chamada['name']!r}.",
                              f"Use uma de: {', '.join(FERRAMENTAS)}.")
    try:
        argumentos = json.loads(chamada["arguments"] or "{}")
        if not isinstance(argumentos, dict):
            raise ValueError("os argumentos devem ser um objeto JSON")
    except ValueError as exc:
        return ferramenta, {}, erro("argumentos_invalidos", f"JSON inválido: {exc}",
                                    "Reenvie os argumentos como um objeto JSON conforme o schema.")
    return ferramenta, argumentos, None


def _rodar(funcao) -> dict:
    try:
        return funcao()
    except TypeError as exc:  # argumento faltando ou que não existe no schema
        return erro("argumentos_invalidos", str(exc), "Confira o schema da ferramenta e reenvie.")
    except sqlite3.Error as exc:
        return erro("erro_banco", str(exc), "O banco falhou; tente uma vez mais ou avise o Administrador.")


def _chave(ex: Execucao, chamada: dict) -> str:
    return f"{ex.estado.id_execucao}:{ex.estado.passo}:{chamada['id']}"


def _escrever(ex: Execucao, chamada, ferramenta, argumentos, aprovado: bool, quem: str) -> dict:
    if not aprovado:
        return erro("nao_confirmado", "O Administrador recusou esta ação.",
                    "Não tente de novo nem insista; diga que nada foi registrado.")
    ex.ctx.chave_idempotencia, ex.ctx.aprovado_por = _chave(ex, chamada), quem
    try:
        return _rodar(lambda: ferramenta.funcao(ex.ctx, **argumentos))
    finally:
        ex.ctx.chave_idempotencia = ex.ctx.aprovado_por = None


def _resumo_resultado(resultado: dict) -> str:
    if resultado.get("erro"):
        return f"erro {resultado['erro']}"
    if "id_alerta" in resultado:
        return f"alerta #{resultado['id_alerta']}"
    if "id_fato" in resultado:
        return f"fato #{resultado['id_fato']}"
    if "trechos" in resultado:
        return "trechos " + (",".join(t["id"] for t in resultado["trechos"]) or "nenhum")
    linhas = resultado.get("linhas", [])
    lotes = [l["codigo_lote"] for l in linhas if l.get("codigo_lote")]
    return f"{len(linhas)} linha(s)" + (f" [{', '.join(lotes[:8])}]" if lotes else "")


def _registrar(ex: Execucao, chamada, ferramenta, argumentos, resultado, confirmacao, inicio) -> None:
    estado = ex.estado
    if ferramenta and ferramenta.escrita and resultado.get("ok"):
        if "id_alerta" in resultado:
            estado.escritas.append(resultado["id_alerta"])
        elif "id_fato" in resultado:
            estado.fatos_gravados.append(resultado["id_fato"])
    estado.chamadas.append({"passo": estado.passo, "nome": chamada["name"], "args": argumentos,
                            "erro": resultado.get("erro"), "resumo_resultado": _resumo_resultado(resultado)})
    # Span execute_tool (OTel GenAI)
    ms_tool = round((time.perf_counter() - inicio) * 1000, 1)
    try:
        from .otel import span_execute_tool, registrar_resultado_tool
        with span_execute_tool(chamada["name"], argumentos,
                               escrita=bool(ferramenta and ferramenta.escrita)) as span_t:
            registrar_resultado_tool(span_t, resultado, resultado.get("erro"), ms_tool)
    except Exception:
        pass
    ex.traj.evento("ferramenta", passo=estado.passo, ferramenta=chamada["name"], argumentos=argumentos,
                   escrita=bool(ferramenta and ferramenta.escrita),
                   reversivel=ferramenta.reversivel if ferramenta else None,
                   confirmacao=confirmacao, resultado=resultado, erro=resultado.get("erro"),
                   ms=round((time.perf_counter() - inicio) * 1000, 1))
    ex.mensagens.append({"role": "tool", "tool_call_id": chamada["id"],
                         "content": json.dumps(resultado, ensure_ascii=False, default=str)})
    ex.fila.pop(0)
    _salvar(ex, "em_andamento")


def _salvar(ex: Execucao, status: str) -> None:
    """Checkpoint a cada passo. Sem pasta configurada (testes), só quando é obrigatório: na pausa."""
    pasta = ex.cfg.pasta_checkpoints
    if pasta is None:
        if status != "aguardando_humano":
            return
        raise RuntimeError("modo 'pausar' exige cfg.pasta_checkpoints")
    checkpoint.salvar(pasta, ex.estado.id_execucao, {
        "id_execucao": ex.estado.id_execucao, "status": status, "pergunta": ex.pergunta,
        "id_loja": ex.ctx.id_loja, "modo": ex.modo, "log": str(ex.traj.caminho) if ex.traj.caminho else None,
        "estado": asdict(ex.estado), "mensagens": ex.mensagens, "fila": ex.fila, "pendente": ex.pendente,
        "historico_tamanho": ex.historico_tamanho,
        "carimbo": {"prompt": {"caminho": ex.prompt.get("caminho"), "arquivo": ex.prompt["arquivo"],
                               "versao": ex.prompt["versao"], "sha": ex.prompt["sha"]},
                    "modelo": ex.cfg.modelo, "temperature": ex.cfg.temperature,
                    "orcamento": asdict(ex.orcamento), "grafo": VERSAO_GRAFO,
                    "data_referencia": datetime.now().date().isoformat(),
                    "limite_dias_validade": ex.ctx.limite_dias_validade,
                    "memoria": ex.memoria_lida or None},
    })


def _orcamento_de(cfg: Config) -> tuple[Orcamento, bool]:
    calcula = cfg.preco_entrada_por_milhao is not None and cfg.preco_saida_por_milhao is not None
    return Orcamento(cfg.max_passos, cfg.max_tokens, cfg.max_custo_usd if calcula else None), calcula


# ==================================================================================================
# Pontos de entrada
# ==================================================================================================

def executar(pergunta: str, *, cliente, cfg: Config, ctx: Contexto, prompt: dict,
             confirmar: Callable[[str], tuple[bool, str]] | None = None, traj: Trajetoria,
             historico: tuple | list = (), modo_confirmacao: str = "sincrono",
             id_execucao: str | None = None) -> Estado:
    """Nunca levanta exceção por erro do modelo ou de ferramenta: tudo vira estado.terminacao ou dado."""
    if modo_confirmacao not in ("sincrono", "pausar"):
        raise ValueError("modo_confirmacao deve ser 'sincrono' ou 'pausar'")
    if modo_confirmacao == "sincrono" and confirmar is None:
        raise ValueError("modo 'sincrono' precisa de uma função confirmar")
    orc, calcula = _orcamento_de(cfg)
    id_exec = id_execucao or f"{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}"
    estado = Estado(id_execucao=id_exec)
    ctx.id_execucao = estado.id_execucao
    ex = Execucao(pergunta=pergunta, cliente=cliente, cfg=cfg, ctx=ctx, prompt=prompt, traj=traj,
                  confirmar=confirmar, modo=modo_confirmacao, estado=estado, orcamento=orc, calcula_custo=calcula,
                  mensagens=list(historico), historico_tamanho=len(historico))
    # Span raiz OpenTelemetry GenAI (Parte 3 — Observabilidade)
    try:
        from .otel import span_invoke_agent, finalizar_invoke_agent
        _otel = span_invoke_agent(
            id_execucao=id_exec,
            versao=VERSAO_GRAFO,
            pergunta=pergunta,
            modelo=cfg.modelo,
            prompt_sha=prompt.get("sha", ""),
            temperatura=cfg.temperature,
        )
    except Exception:
        from contextlib import nullcontext
        _otel = nullcontext(None)
    with _otel as span_raiz:
        resultado = rodar(ex, "preparar")
        try:
            from .otel import finalizar_invoke_agent
            finalizar_invoke_agent(
                span_raiz,
                terminacao=resultado.terminacao or "",
                tokens_entrada=resultado.tokens_entrada,
                tokens_saida=resultado.tokens_saida,
                custo_usd=resultado.custo_usd,
                alertas=resultado.escritas,
                aviso_verificador=resultado.aviso_verificador,
            )
        except Exception:
            pass
        return resultado


def retomar(id_execucao: str, *, aprovado: bool, por: str, cliente, cfg: Config, ctx: Contexto,
            traj: Trajetoria | None = None, confirmar=None) -> Estado:
    """Continua uma execução parada em 'aguardando_humano'. Pode rodar em outro processo, horas depois.

    - recusa se o prompt mudou desde a pausa (a decisão foi pedida sob outras regras);
    - continua o orçamento de onde parou, sem zerar;
    - a escrita aprovada é validada de novo e gravada com a chave de idempotência do pendente.
    Escritas seguintes da mesma resposta do modelo voltam a pausar (cada uma tem a sua aprovação)."""
    dados = checkpoint.carregar(cfg.pasta_checkpoints, id_execucao)
    if dados["status"] != "aguardando_humano":
        raise ValueError(f"A execução {id_execucao} não está aguardando aprovação (status: {dados['status']}).")
    carimbo = dados["carimbo"]["prompt"]
    prompt = carregar_prompt(carimbo["caminho"] or (cfg.arquivo_prompt.parent / carimbo["arquivo"]))
    if prompt["sha"] != carimbo["sha"]:
        raise ValueError(f"O prompt {carimbo['arquivo']} mudou desde a pausa (sha {carimbo['sha']} -> "
                         f"{prompt['sha']}). Recuse e refaça a pergunta.")
    if dados["id_loja"] != ctx.id_loja:
        raise ValueError("A execução pertence a outra loja.")
    estado = Estado(**dados["estado"])
    estado.terminacao = None
    ctx.id_execucao = estado.id_execucao
    orc, calcula = _orcamento_de(cfg)
    traj = traj or Trajetoria(dados["log"])
    ex = Execucao(pergunta=dados["pergunta"], cliente=cliente, cfg=cfg, ctx=ctx, prompt=prompt, traj=traj,
                  confirmar=confirmar, modo="pausar" if confirmar is None else "sincrono", estado=estado,
                  orcamento=orc, calcula_custo=calcula, mensagens=dados["mensagens"], fila=dados["fila"],
                  pendente=dados["pendente"],
                  decisao={"aprovado": aprovado, "por": por, "em": datetime.now().isoformat(timespec="seconds")},
                  memoria_lida=dados["carimbo"].get("memoria") or {},
                  historico_tamanho=dados.get("historico_tamanho", 0))
    traj.evento("retomada", id_execucao=id_execucao, aprovado=aprovado, por=por,
                pedido_em=dados["pendente"]["pedido_em"])
    return rodar(ex, "retomar")


def diagrama_mermaid() -> str:
    linhas = ["flowchart TD"]
    for origem, destinos in ARESTAS.items():
        for destino in sorted(destinos):
            linhas.append(f"    {origem} --> {destino}")
    return "\n".join(linhas)


if __name__ == "__main__":
    print(diagrama_mermaid())
