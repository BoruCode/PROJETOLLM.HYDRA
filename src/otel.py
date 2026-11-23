"""Instrumentação OpenTelemetry GenAI — Parte 3 (Observabilidade).

Emite traces segundo as convenções semânticas GenAI do OpenTelemetry:
  invoke_agent  — uma vez por execução (raiz)
  chat          — a cada chamada ao modelo
  execute_tool  — a cada ferramenta executada

Atributos obrigatórios na raiz (src/grafo.py):
  gen_ai.system              = "groq" (ou o provedor)
  gen_ai.agent.id            = id_execucao
  gen_ai.agent.version       = versao_sistema
  hydra.terminacao           = motivo de término (taxonomia da Aula 05)
  hydra.prompt_sha           = sha do prompt
  hydra.temperatura          = temperature

O módulo importa opentelemetry-sdk se disponível; caso contrário, usa stubs no-op
para não quebrar o sistema quando o pacote não estiver instalado.

Configuração (variáveis de ambiente, opcionais):
  OTEL_ENABLED=1              habilita a exportação (padrão: habilitado se SDK instalado)
  OTEL_EXPORTER_FILE=traces/traces.jsonl   exporta para arquivo local (padrão)
  OTEL_EXPORTER_OTLP_ENDPOINT=http://...   exporta para endpoint OTLP (Jaeger, Tempo, etc.)

Como ver os traces:
  Arquivo local: cat traces/traces.jsonl | jq .
  Jaeger: docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one
          OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 python -m src.main "..."
          Abrir http://localhost:16686
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .config import RAIZ

_OTEL_DISPONIVEL = False
_tracer = None
_exporter_arquivo: Path | None = None


def _inicializar():
    global _OTEL_DISPONIVEL, _tracer, _exporter_arquivo
    if os.getenv("OTEL_ENABLED", "1").strip().lower() in ("0", "false", "off"):
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        arquivo = os.getenv("OTEL_EXPORTER_FILE", "").strip() or "traces/traces.jsonl"
        _exporter_arquivo = RAIZ / arquivo
        _exporter_arquivo.parent.mkdir(parents=True, exist_ok=True)

        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()

        recurso = Resource.create({"service.name": "hydra-agente", "service.version": "3.0.0"})
        provider = TracerProvider(resource=recurso)

        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            except ImportError:
                pass  # opentelemetry-exporter-otlp não instalado

        # Sempre exporta para arquivo local (queryable com jq, grep, etc.)
        provider.add_span_processor(SimpleSpanProcessor(_FileSpanExporter(_exporter_arquivo)))

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("hydra.agente", "3.0.0")
        _OTEL_DISPONIVEL = True
    except ImportError:
        pass  # opentelemetry-sdk não instalado — no-op silencioso


class _FileSpanExporter:
    """Exporta spans como JSON-L para um arquivo local (consultável com jq, grep, etc.)."""

    def __init__(self, caminho: Path):
        self._caminho = caminho

    def export(self, spans):
        with open(self._caminho, "a", encoding="utf-8") as f:
            for span in spans:
                dados = {
                    "trace_id": format(span.context.trace_id, "032x"),
                    "span_id": format(span.context.span_id, "016x"),
                    "parent_span_id": (format(span.parent.span_id, "016x")
                                       if span.parent else None),
                    "name": span.name,
                    "start_time_ms": span.start_time // 1_000_000,
                    "end_time_ms": span.end_time // 1_000_000,
                    "duration_ms": (span.end_time - span.start_time) // 1_000_000,
                    "status": span.status.status_code.name,
                    "attributes": dict(span.attributes or {}),
                }
                f.write(json.dumps(dados, ensure_ascii=False) + "\n")
        from opentelemetry.sdk.trace.export import SpanExportResult
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

@contextmanager
def span_invoke_agent(id_execucao: str, versao: str, pergunta: str,
                      modelo: str, prompt_sha: str, temperatura):
    """Span raiz: invoke_agent. Abrir uma vez por execução."""
    if not _OTEL_DISPONIVEL or _tracer is None:
        yield None
        return
    from opentelemetry import trace
    with _tracer.start_as_current_span(
        "invoke_agent",
        attributes={
            "gen_ai.system": "groq",
            "gen_ai.agent.id": id_execucao,
            "gen_ai.agent.version": versao,
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.prompt": pergunta[:500],
            "hydra.prompt_sha": prompt_sha,
            "hydra.temperatura": str(temperatura),
            "hydra.modelo": modelo,
        },
    ) as span:
        yield span


def finalizar_invoke_agent(span, terminacao: str, tokens_entrada: int,
                            tokens_saida: int, custo_usd, alertas: list,
                            aviso_verificador: str | None):
    """Adiciona atributos de fim ao span raiz."""
    if span is None:
        return
    span.set_attribute("hydra.terminacao", terminacao or "desconhecido")
    span.set_attribute("gen_ai.usage.input_tokens", tokens_entrada)
    span.set_attribute("gen_ai.usage.output_tokens", tokens_saida)
    if custo_usd is not None:
        span.set_attribute("gen_ai.usage.cost_usd", custo_usd)
    span.set_attribute("hydra.alertas_registrados", json.dumps(alertas))
    if aviso_verificador:
        span.set_attribute("hydra.aviso_verificador", aviso_verificador)
        from opentelemetry.trace import StatusCode
        span.set_status(StatusCode.ERROR, aviso_verificador)


@contextmanager
def span_chat(passo: int, modelo: str, tokens_entrada: int = 0, tokens_saida: int = 0):
    """Span de chamada ao modelo: chat."""
    if not _OTEL_DISPONIVEL or _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(
        "chat",
        attributes={
            "gen_ai.operation.name": "chat",
            "gen_ai.system": "groq",
            "gen_ai.request.model": modelo,
            "hydra.passo": passo,
        },
    ) as span:
        yield span
        if tokens_entrada:
            span.set_attribute("gen_ai.usage.input_tokens", tokens_entrada)
        if tokens_saida:
            span.set_attribute("gen_ai.usage.output_tokens", tokens_saida)


@contextmanager
def span_execute_tool(nome_ferramenta: str, argumentos: dict, escrita: bool = False):
    """Span de execução de ferramenta: execute_tool."""
    if not _OTEL_DISPONIVEL or _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(
        "execute_tool",
        attributes={
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": nome_ferramenta,
            "hydra.ferramenta.escrita": escrita,
            "gen_ai.tool.call.arguments": json.dumps(argumentos, ensure_ascii=False)[:500],
        },
    ) as span:
        yield span


def registrar_resultado_tool(span, resultado: dict, erro: str | None, ms: float):
    """Adiciona resultado ao span de ferramenta."""
    if span is None:
        return
    span.set_attribute("hydra.ferramenta.ms", ms)
    if erro:
        span.set_attribute("gen_ai.tool.call.error", erro)
        from opentelemetry.trace import StatusCode
        span.set_status(StatusCode.ERROR, erro)
    else:
        span.set_attribute("hydra.ferramenta.ok", True)


# Inicializar ao importar o módulo
_inicializar()
