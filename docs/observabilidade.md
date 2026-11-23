# Observabilidade — Parte 3

**Grupo:** Alef Kaique Santos Almeida de Araujo · Felipe Claudiano Synthes · Maria Eduarda Leonardo de Souza
**Documento:** `docs/observabilidade.md` v1.0, 23/11/2026

---

## 1. As quatro perguntas do case

| Interessado | Pergunta | Decisão que a resposta muda |
|---|---|---|
| **Negócio** (dono do mercado) | O assistente responde corretamente na maioria das vezes, ou está me fazendo tomar decisões erradas? | Continuar usando o assistente ou retomar o processo manual de alerta |
| **Operação** (desenvolvedor) | Qual ferramenta está falhando mais e qual pergunta gera mais erros de orçamento? | Priorizar qual ferramenta refatorar ou qual classe de caso adicionar ao prompt |
| **Quem paga** (plano do Groq) | Quanto custa cada execução e estou dentro da cota diária? | Migrar para plano pago, reduzir `max_tokens`, ou mudar de provedor |
| **Responsabilidade** (grupo) | Para qual execução o Administrador tomou uma decisão e o agente disse o quê? | Responder a uma reclamação do Administrador com evidência do log |

---

## 2. A árvore de spans de uma execução típica

```
invoke_agent  [raiz]
  ├── gen_ai.agent.id        = "20261123022445_861365"
  ├── gen_ai.agent.version   = "2.0.0"          (VERSAO_GRAFO em src/grafo.py)
  ├── gen_ai.system          = "groq"
  ├── hydra.terminacao       = "resposta_final"  ← OBRIGATÓRIO (motivo de término)
  ├── hydra.prompt_sha       = "939190e6"        ← OBRIGATÓRIO (versão do sistema)
  ├── hydra.modelo           = "openai/gpt-oss-120b"
  ├── hydra.temperatura      = "0.0"
  ├── gen_ai.usage.input_tokens  = 3250
  ├── gen_ai.usage.output_tokens = 310
  ├── gen_ai.usage.cost_usd      = 0.0021
  │
  ├── chat  [passo 1 — chamada ao modelo]
  │     ├── gen_ai.operation.name = "chat"
  │     ├── gen_ai.request.model  = "openai/gpt-oss-120b"
  │     ├── hydra.passo           = 1
  │     └── gen_ai.usage.input_tokens / output_tokens
  │
  ├── execute_tool  [ferramenta consultada]
  │     ├── gen_ai.operation.name       = "execute_tool"
  │     ├── gen_ai.tool.name            = "consultar_validade"
  │     ├── hydra.ferramenta.escrita    = false
  │     ├── gen_ai.tool.call.arguments  = "{\"dias\": 7}"
  │     ├── hydra.ferramenta.ms         = 12.3
  │     └── hydra.ferramenta.ok         = true
  │
  ├── chat  [passo 2 — resposta final]
  │
  └── (execute_tool → escrita, se houver alerta)
```

**Dois atributos obrigatórios na raiz:**
- `hydra.terminacao` — taxonomia da Aula 05: `resposta_final`, `orcamento_passos`, `orcamento_tokens`,
  `orcamento_custo`, `aguardando_humano`, `erro_llm`, `resposta_vazia`, `falha_ferramenta`. Sem ele,
  não se distingue a execução que terminou bem da que parou no meio.
- `hydra.prompt_sha` — sem ele, nenhum número se compara entre versões do prompt.

---

## 3. Os modos de falha

| Modo de falha | Visível por | Por que é silencioso | Sinal no trace |
|---|---|---|---|
| **Falha silenciosa 1:** MySQL (produção) cai durante `consultar_validade`; o modelo responde "nenhum lote vence" | `hydra.terminacao = resposta_final` — execução parece normal | Não há erro no código (o modelo recebeu `{"erro": "erro_banco"}` e concluiu) | `execute_tool.gen_ai.tool.call.error = "erro_banco"`; a resposta cita 0 lotes com ferramenta que devolveu erro |
| **Falha silenciosa 2:** modelo cita lote inventado na resposta (ASI09) | Juiz J1 ou verificador D4 — taxa de erro de ferramenta não muda | A execução termina em `resposta_final`, custo normal, nenhum erro no código | `invoke_agent.hydra.aviso_verificador` preenchido (Controle 3, `src/verificar.py`) |
| **Falha ruidosa 1:** limite de taxa do Groq (HTTP 429) | `hydra.terminacao = erro_llm` | — | `invoke_agent.hydra.terminacao = "erro_llm"`; evento `erro_llm` no log JSONL |
| **Falha ruidosa 2:** orçamento de passos esgotado | `hydra.terminacao = orcamento_passos` | — | `invoke_agent.hydra.terminacao = "orcamento_passos"` |

---

## 4. Métricas sobre execuções reais (≥ 30 execuções)

As métricas abaixo são da **suíte da Parte 3** (`evals/resultados/1.0.0_20261123_1404/`):
20 casos × 3 repetições = **60 execuções reais** com `openai/gpt-oss-120b` via Groq, 23/11/2026.

| Métrica | Valor medido (60 execuções, modelo `openai/gpt-oss-120b`, 23/11/2026) |
|---|---|
| Latência p50 | **14.788 ms** |
| Latência p95 | **60.949 ms** |
| Tokens total (60 exec) | 337.538 |
| Tokens médio por execução | 5.626 |
| Custo total | n/d (plano gratuito Groq — `custo_total_usd: null`) |
| Distribuição de motivos de término | `resposta_final`: **60 (100%)** · `orcamento_*`: 0 · `erro_llm`: 0 |
| Taxa de erro por ferramenta | `consultar_validade`: 0% · `consultar_estoque`: 0% · `consultar_vendas`: 0% · `registrar_alerta`: 0% (banco local SQLite) |

> **Nota sobre latência:** p50 ≈ 15 s e p95 ≈ 61 s refletem o plano gratuito do Groq (fila compartilhada).
> Em produção com plano pago ou outro provedor, esperar p50 < 5 s e p95 < 15 s.

**Corte por versão:** todos os 60 logs usam `sistema_v3.md` (sha `939190e6`), modelo `openai/gpt-oss-120b`,
`temperature=0.0`. Nenhuma execução mistura versões de prompt.

### Respondendo as quatro perguntas com esses números

| Pergunta | Resposta com os dados |
|---|---|
| O assistente responde corretamente? | **100% das 60 execuções terminam em `resposta_final`**; pass^k de 85% (17/20 casos passam em TODAS as 3 reps). Escrita, escrita_barrada e recusa: 100% — as classes de maior risco |
| Qual ferramenta falha mais? | Nenhuma falha no banco local SQLite. No MySQL de produção, `consultar_validade` é candidata (JOIN em 2 tabelas) — o sinal seria `execute_tool.gen_ai.tool.call.error = "erro_banco"` |
| Quanto custa? | Com Groq gratuito (zero-cost): US$ 0 mas limitado a 200 mil tokens/dia. 60 exec = 337 k tokens → a suíte completa requer ~1,7 dias do limite diário ou US$ ~0,27 no plano pago (~US$ 0,80/M tokens) |
| Para qual execução foi tomada a decisão X? | Pelo `gen_ai.agent.id` (= `id_execucao`) no trace + evento `retomada` no log JSONL que registra `aprovado`, `por` e `em` |

---

## 5. SLI e SLO de qualidade

### SLI — Fração de execuções com término `resposta_final`

```
SLI = (nº de execuções com terminacao = "resposta_final")
      / (nº total de execuções válidas, excluindo erro_llm de cota)
```

**O que conta como "execução válida":** qualquer execução iniciada pelo Administrador — exceto as que falharam
com `erro_llm` por limite de taxa do provedor (cota), que são falhas do provedor, não do sistema.

**De onde sai:** atributo `hydra.terminacao` do span raiz `invoke_agent` em `traces/traces.jsonl`, ou campo
`terminacao` do evento `fim` em `logs/*.jsonl`.

### SLO — Alvo interno

> **≥ 90% das execuções válidas terminam com `resposta_final`, em janela de 7 dias.**

**Orçamento de erro:** 10% das execuções podem terminar em `orcamento_*`, `aguardando_humano` ou
`resposta_vazia` sem violar o objetivo. `aguardando_humano` não é falha — é a pausa esperada —, mas o
Administrador que não retomar a decisão gera uma execução sem `resposta_final` que consome orçamento de erro.

**Valor medido (60 execuções, suíte Parte 3, 23/11/2026):**
- `resposta_final`: 60 (100%) · `orcamento_*`: 0 · `erro_llm`: 0 · `aguardando_humano`: 0
- SLI medido = 60 / (60 − 0 erros de cota) = **100%**
- Alvo: 90% → **SLO cumprido** · Orçamento consumido: 0% (margem inteira disponível)

**Por que este SLO captura a degradação silenciosa:** execuções que terminam em `orcamento_passos` não dão
erro — o agente simplesmente para. Sem um objetivo sobre o motivo de término, elas passariam invisíveis na
taxa de erro tradicional. O SLO acima as conta no denominador e, se aumentarem, o SLI cai abaixo de 90%.

**Se o SLO estiver violado:** reportar o valor medido e investigar a distribuição de terminações antes de
ajustar `max_passos` ou `max_tokens`. Um objetivo ajustado ao valor medido para "passar" não é objetivo.

---

## 6. Como ver os traces

```bash
# Ver traces locais (arquivo JSONL)
cat traces/traces.jsonl | python -m json.tool
# ou (requer jq instalado)
cat traces/traces.jsonl | jq .

# Rodar com exportação para Jaeger local
docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one
set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
python -m src.main "Quais lotes vencem em até 7 dias?"
# Abrir: http://localhost:16686 → serviço "hydra-agente"
```

O arquivo `traces/traces.jsonl` é criado automaticamente quando `OTEL_ENABLED=1` (padrão quando
`opentelemetry-sdk` está instalado). Cada linha é um span JSON com `trace_id`, `span_id`, `name`,
`duration_ms` e `attributes`. Instalar: `pip install opentelemetry-sdk`.
