# Hydra — Assistente de estoque com agente de IA

**Grupo:** Alef Kaique Santos Almeida de Araujo · Felipe Claudiano Synthes · Maria Eduarda Leonardo de Souza
**Disciplina:** Agentes de IA — **Parte 3** (avaliação, governança, segurança e observabilidade) · Centro Universitário Senac

**O problema em uma frase:** o Administrador do mercado não consegue, hoje, perguntar ao Hydra o que vence, o que está acabando ou o que está parado, e não tem onde registrar o que decidiu acompanhar.

O repositório também guarda o sistema Hydra (TCC): `Hydra.Front`, `Hydra.Back` e `Hydra.Agent`. Para rodar o sistema
completo, veja [`COMO-RODAR.md`](COMO-RODAR.md). **Este README trata só do agente (`src/`).**

## Parte 3: o que mudou

| Peça | Onde | Documento |
|---|---|---|
| **Controle 1** (regex na mensagem — ASI02/ASI01) | `src/ferramentas.py:_validar_mensagem` | [`docs/seguranca.md`](docs/seguranca.md) §Controles |
| **Controle 2** (SQLite somente leitura — ASI03) | `src/db.py:conectar_leitura` | [`docs/seguranca.md`](docs/seguranca.md) §Controles |
| **Controle 3** (lotes da resposta vieram de ferramenta — ASI09) | `src/verificar.py` | [`docs/seguranca.md`](docs/seguranca.md) §Controles |
| **Testes dos controles** (21 testes) | `tests/test_seguranca.py` | — |
| **Golden dataset** v1.0.0 (20 casos, 6 classes) | `dados/golden.json` | [`docs/evals.md`](docs/evals.md) |
| **Suíte de avaliação** (`evals.rodar` + `evals.comparar` + `evals.juiz`) | `evals/` | [`docs/evals.md`](docs/evals.md) |
| **OpenTelemetry GenAI** (spans `invoke_agent`, `chat`, `execute_tool`) | `src/otel.py`, `src/grafo.py` | [`docs/observabilidade.md`](docs/observabilidade.md) |
| **Model card** (12 campos) | — | [`docs/model-card.md`](docs/model-card.md) |

## Parte 2: o que mudou

| Peça | Onde | Documento |
|---|---|---|
| **Grafo explícito** (7 nós; o motor recusa transição fora das arestas) | `src/grafo.py` | [`docs/arquitetura.md`](docs/arquitetura.md) |
| **Estado e checkpoint** a cada passo (`checkpoints/<id>.json`) | `src/grafo.py`, `src/checkpoint.py` | [`docs/arquitetura.md`](docs/arquitetura.md) §2 |
| **RAG** sobre as RN01–RN29 e RF01–RF24 do TCC (BM25, 53 trechos), ferramenta `consultar_regras` | `src/rag.py`, `dados/corpus/` | [`docs/rag.md`](docs/rag.md) |
| **Memória** semântica (`lembrar_fato`, com aprovação) e episódica (escrita pelo código), com contradição e decaimento | `src/memoria.py` | [`docs/memoria.md`](docs/memoria.md) |
| **Humano no laço com pausa**: a escrita para o grafo e a aprovação chega depois, de outro processo | `--confirmar pausar`, `--retomar` | [`docs/humano-no-laco.md`](docs/humano-no-laco.md) |
| **Prompt v3** (regras 8 a 10) | `prompts/sistema_v3.md` | [`docs/arquitetura.md`](docs/arquitetura.md) §5 |
| **8 casos novos** de demonstração (06 a 13) | `dados/casos.json` | [`docs/demonstracao.md`](docs/demonstracao.md) |

Nenhuma dependência nova: o BM25 é escrito em Python puro. Um `dados/hydra_demo.db` criado na Parte 1 é recriado sozinho na
primeira execução, porque não tem as tabelas novas.

## Como rodar

Precisa de Python 3.10 ou mais novo e de uma chave de API de um provedor compatível com a biblioteca `openai`.

```bash
git clone https://github.com/BoruCode/PROJETOLLM.HYDRA.git
cd PROJETOLLM.HYDRA
python -m venv .venv
.venv\Scripts\activate            # Windows        (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Windows        (Linux/macOS: cp .env.example .env)
```

Abra o `.env` e preencha `LLM_BASE_URL`, `OPENAI_API_KEY` e `LLM_MODEL`. O grupo testou com o Groq (plano gratuito, sem cartão): `LLM_BASE_URL=https://api.groq.com/openai/v1` e `LLM_MODEL=openai/gpt-oss-120b`. O nome `OPENAI_API_KEY` é o da biblioteca, mesmo com chave de outro provedor. Depois:

```bash
python -m src.main "Quais produtos estão abaixo do estoque mínimo?"
```

O banco simulado (`dados/hydra_demo.db`) é criado sozinho na primeira execução. Para recriá-lo: `python -m src.criar_banco`.
Nenhuma chave vai para o git: o `.env` está no `.gitignore`.

## Como usar

**O que digitar.** Uma pergunta em português, em texto livre, como o Administrador faria:

```bash
python -m src.main "sua pergunta"      # uma pergunta e sai
python -m src.main                     # modo interativo, com histórico; linha vazia ou "sair" encerra
```

Opções: `--confirmar perguntar|sim|nao|pausar` (como tratar a confirmação das escritas; o padrão é perguntar),
`--sem-memoria` e `--recriar-banco`.

**Aprovar depois (Parte 2).** Com `--confirmar pausar`, o agente valida a escrita, grava o checkpoint e para
(`Terminou por: aguardando_humano`). A decisão vem de outro terminal, quando o Administrador puder:

```bash
python -m src.main "Registre um alerta de estoque baixo para o Feijão Carioca 1kg." --confirmar pausar
python -m src.main --pendentes
python -m src.main --retomar <id_execucao> --aprovar --por "Felipe"     # ou --recusar
```

Na retomada o código valida a regra de novo (o estoque pode ter mudado), continua o orçamento de onde parou e grava com uma
chave de idempotência, para não duplicar o alerta. Esses três comandos rodados com o modelo real, com a saída completa:
`logs/parte2/terminal/pausa_pendentes_retomar.txt`. O que cada garantia testa: [`docs/humano-no-laco.md`](docs/humano-no-laco.md).

**Perguntar sobre as regras do Hydra (Parte 2).** "Quem pode alterar preços?", "Em quanto tempo expira o código de
recuperação?": o agente busca nas RN/RF da documentação do TCC e cita o identificador. **Pedir para lembrar:** "Lembre que
quando eu falar 'o queijo' é o Queijo Mussarela Fatiado": o fato é validado, você confirma e ele passa a valer nas próximas
perguntas. Manutenção diária da memória: `python -m src.manutencao`.

**O que o sistema faz.** O modelo escolhe quais consultas fazer (vendas, estoque, validade), o código as executa no SQLite
e devolve o resultado, e o modelo responde. Se o Administrador pedir, o agente registra um **alerta** (de validade ou de
estoque baixo) na fila `alertas_agente`. Antes de gravar, o código confere as regras (o lote vence em até 30 dias? o
estoque está no mínimo ou abaixo? já existe alerta igual?) e o terminal pede a sua confirmação: `Confirmar? [s/N]`.

**O que você recebe.** A resposta em até 6 linhas e uma linha de fechamento:

```
Terminou por: resposta_final | passos: <n> | tokens: <n> | custo: <valor ou n/d> | alertas registrados: <#ids ou nenhum> | fatos guardados: <#ids ou nenhum>
Execução: <id_execucao> | Log: logs/execucao_<data>_<hora>.jsonl
```

`Terminou por` diz por que o agente parou (`resposta_final` é o normal; `orcamento_*` e `erro_llm` são falhas, veja
[`docs/arquitetura.md`](docs/arquitetura.md)). O log tem uma linha JSON por evento: ferramenta chamada, argumentos, resultado e erro.

### Exemplo completo (execução real)

Execução de 20/09/2026, modelo `openai/gpt-oss-120b` (Groq), prompt `sistema_v2.md`, banco simulado. A pergunta e a saída abaixo
foram transcritas do terminal (o modelo escreve o hífen dos códigos de lote como hífen não separável; aqui está normalizado). Os logs das demonstrações, com escrita e confirmação, estão em `logs/resumo.md`.

```
> python -m src.main "Quais lotes vencem em até 3 dias?"
  [passo 1] consultar_validade({"dias": 3}) -> 3 linha(s)

- Presunto Fatiado: 1 kg (lote L-PRE-01, validade 2026-09-19, vencido)
- Pão de Forma 500g: 5 un (lote L-PAO-01, validade 2026-09-22, vence em 2 dias)
- Iogurte Natural 170g: 12 un (lote L-IOG-01, validade 2026-09-23, vence em 3 dias)

Terminou por: resposta_final | passos: 2 | tokens: 2559 | custo: n/d (sem preços no .env) | alertas registrados: nenhum
```

Como ler: o agente fez uma consulta (`passo 1`), respondeu na segunda chamada ao modelo (`passos: 2`), gastou 2.559 tokens e
não gravou nada, porque a pergunta não pediu alerta. Com "Registre um alerta para cada um", o terminal pede `Confirmar? [s/N]`
antes de cada gravação.

### Exemplos da Parte 2 (execuções reais)

Rodada de 23/11/2026, modelo `openai/gpt-oss-120b` (Groq), prompt `sistema_v3.md`, `temperature` 0, rodada pelo
`src.avaliar`. A pergunta, os argumentos, os resultados, a resposta e os números foram copiados dos eventos do log, e estão
mostrados no formato do terminal; o JSON longo foi cortado (`…`).

**Pergunta sobre regra do Hydra (RAG)**: `logs/parte2/rodada2/06_regra_rag.jsonl`

```
> Em quanto tempo expira o código de recuperação de senha?
  [passo 1] consultar_regras({"pergunta": "tempo de expiração do código de recuperação de senha", "tipo": "regra"})
            -> trechos: [{"id": "RN26", "titulo": "Prazo de expiração do código de recuperação", "texto": "O código de
               recuperação de senha expira 15 minutos após sua geração, …"}, …]

O código de recuperação de senha expira **15 minutos** após sua geração (RN26).

Terminou por: resposta_final | passos: 2 | tokens: 3559 | alertas registrados: nenhum
```

**Pausa e retomada (caso 12)**: `logs/parte2/rodada2/12_pausa_aprovada.jsonl`. O primeiro processo para antes de gravar; a
aprovação vem depois, pela mesma função que o `--retomar` usa:

```
> Registre um alerta de estoque baixo para o Feijão Carioca 1kg.        (--confirmar pausar)
  [passo 1] consultar_estoque({"produto": "Feijão Carioca 1kg"}) -> quantidade 8, estoque_minimo 15, abaixo_do_minimo: true
  [pausa] aguardando aprovação: Registrar alerta de estoque_baixo para 'Feijão Carioca 1kg':
          "Estoque abaixo do mínimo (8 unidades, mínimo 15)."
Terminou por: aguardando_humano | passos: 2 | alertas registrados: nenhum
Execução: 20261123022445_861365

> python -m src.main --retomar 20261123022445_861365 --aprovar
  [passo 2] registrar_alerta({"produto": "Feijão Carioca 1kg", "tipo": "estoque_baixo", "codigo_lote": null, …})
            -> {"ok": true, "id_alerta": 1}  [confirmado por administrador (src.avaliar)]

- Feijão Carioca 1kg: 8 un (abaixo do mínimo 15)
Alerta de estoque baixo registrado (id 1).

Terminou por: resposta_final | passos: 3 | tokens: 5296 | alertas registrados: #1
```

O orçamento continuou de onde parou (passo 3, e não 1), e o alerta foi gravado uma vez só, com a chave de idempotência
`20261123022445_861365:2:fc_…`.

### Demonstração com os casos difíceis

O exemplo da Parte 1 usa o prompt v2. Os 8 casos novos da Parte 2 (RAG, memória e pausa) estão descritos em
[`docs/demonstracao.md`](docs/demonstracao.md), com o resultado das rodadas com o modelo real (logs em `logs/parte2/`).

```bash
python -m src.avaliar               # roda os 13 casos de dados/casos.json e confere cada um contra o gabarito (logs em logs/parte2/)
python -m src.avaliar_rag           # mede o RAG sozinho, sem modelo
python -m src.avaliar --caso 02_divergencia
python -m src.avaliar --pausa 60    # espera 60 s entre os casos (provedores gratuitos têm limite de taxa)
```

| Caso | O que testa |
|---|---|
| `01_simples` | consulta a validade e registra 3 alertas (o gabarito é o conjunto exato de lotes) |
| `02_divergencia` | o Administrador diz "200 litros", o banco tem 6: o agente deve contradizer com o dado |
| `03_registro_inexistente` | produto que não existe: o erro da ferramenta volta como dado e o agente não troca de produto sozinho |
| `04_nao_disparar` | alerta para lote que vence em 200 dias: o código barra, nada é gravado |
| `05_extra_rn28` | pedido para zerar estoque: o agente recusa (RN28) |

| `06` a `13` | Parte 2: RAG (06, 07), memória (08 a 11) e pausa com retomada aprovada e recusada (12, 13) |

Os logs de cada caso ficam em `logs/parte2/` e o resumo com aprovados/reprovados em `logs/parte2/resumo.md`. Os da Parte 1
continuam em `logs/` e `logs/v1/`.

### Medições que alimentam `docs/case.md` e `docs/modelos.md`

```bash
python -m src.baseline    # cronometra 10 rodadas no Hydra e 10 no agente; reescreve o bloco de linha de base do case.md
python -m src.comparar    # roda os 5 casos em cada candidato de dados/candidatos.json; reescreve as tabelas do modelos.md
```

O `comparar` lê `GROQ_API_KEY` e `MISTRAL_API_KEY` do `.env` (candidato sem chave aparece como "não medido"). O
`baseline` grava cada rodada em `docs/baseline.csv` e pode ser retomado se for interrompido. Os dados e os casos difíceis
estão descritos em [`dados/LEIAME.md`](dados/LEIAME.md).

### O que o sistema não faz

- Não altera estoque, produtos, vendas, clientes nem usuários. As únicas escritas são o alerta, que pode ser descartado
  (`UPDATE alertas_agente SET status = 'descartado' WHERE id_alerta = ...`), e o fato da memória, que pode ser substituído
  por outro mais recente. As duas passam por validação em código e por aprovação humana.
- Não guarda na memória saldo, validade, vendas nem dado pessoal (CPF, e-mail, telefone).
- Só responde com dados do banco. Se não houver o dado (por exemplo, faturamento ou lucro, que nenhuma ferramenta desta parte consulta),
  o prompt manda dizer que não tem em vez de estimar.
- Não conecta ao MySQL do Hydra: usa um espelho em SQLite com dados simulados. A integração com a tela do Hydra (chat e
  aprovação dos pendentes) fica para a Parte 3.
- Quando não consegue responder, termina com um motivo (`orcamento_*`, `erro_llm`, `resposta_vazia`) e avisa no terminal.
  `aguardando_humano` não é falha: é a pausa esperando a sua decisão.

## Suíte de avaliação (Parte 3)

```bash
# Rodar o golden dataset (20 casos × 3 repetições, precisa de chave API no .env)
python -m evals.rodar --versao 1.0.0

# Rodar só uma classe (para economizar cota do provedor)
python -m evals.rodar --versao 1.0.0 --classe consulta --pausa 60

# Comparar duas rodadas (imprime tabela delta por classe)
python -m evals.comparar evals/resultados/1.0.0_20261123_1000 evals/resultados/1.1.0_20261123_1200

# Rodar o juiz J1 (fidelidade) nos logs de uma rodada
python -m evals.juiz --pasta logs/suite/1.0.0_20261123_1000 --saida evals/rotulos_juiz.json
```

## Testes dos controles de segurança (Parte 3)

```bash
# Roda os 21 testes dos 3 controles (não precisa de chave API — sem chamada LLM)
python -m unittest tests.test_seguranca -v
```

Controles testados:
- **Controle 1** (`TestValidarMensagem`): regex barra PIX/URL/CPF/tel no campo `mensagem`
- **Controle 2** (`TestConectarLeitura`): SQLite `mode=ro` impede INSERT/UPDATE/DELETE
- **Controle 3** (`TestVerificarResposta`): lotes da resposta devem vir de ferramenta

## Como ver os traces (OpenTelemetry — Parte 3)

```bash
# Ver traces locais (arquivo JSONL, gerado automaticamente com opentelemetry-sdk instalado)
# Instalar: pip install opentelemetry-sdk
cat traces/traces.jsonl | python -m json.tool

# Exportar para Jaeger local (interface visual)
docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one
# No .env: OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
# Abrir: http://localhost:16686 → serviço "hydra-agente"
```

## Testes

```bash
python -m unittest -v   # todos os testes (85 existentes + 21 de segurança = 106 total)
```

Os testes usam um modelo falso (nenhuma chamada de API) e verificam ferramentas, laço, orçamento, confirmação,
tratamento de erro e o verificador. Na Parte 2, `tests/test_parte2.py` (34 testes) cobre o grafo, a pausa e a retomada,
o RAG e as regras da memória: 85 testes no total. A qualidade do modelo é medida por `python -m src.avaliar`.

## Estrutura da entrega

```
README.md            este arquivo
requirements.txt     dependências com versão fixada (inclui opentelemetry-sdk para Parte 3)
.env.example         nomes das variáveis, sem valores

prompts/             prompts versionados (v1, v2, v3)
src/                 agente: grafo.py, agente.py, ferramentas.py, rag.py, memoria.py,
                     checkpoint.py, db.py, main.py, otel.py (Parte 3), verificar.py (Parte 3)
dados/               schema.sql, seed.sql, casos.json, golden.json (Parte 3), corpus/, LEIAME.md
evals/               suíte Parte 3: rodar.py, comparar.py, juiz.py, resultados/
logs/                execuções: Parte 1 em logs/, Parte 2 em logs/parte2/, suíte em logs/suite/
traces/              traces OpenTelemetry (gerado em tempo de execução, .gitignore exceto .gitkeep)
docs/
  case.md, modelos.md, fontes.md, base-de-conhecimento-v1.md  (Parte 1)
  arquitetura.md, rag.md, memoria.md, humano-no-laco.md, demonstracao.md  (Parte 2)
  mudancas.md         Parte 3 §0: o que mudou desde a Parte 2
  evals.md            Parte 3 §1: dataset, níveis, juiz, resultado das rodadas
  model-card.md       Parte 3 §2: 12 campos, autoridade, decisão do trace, LACUNAS
  seguranca.md        Parte 3 §3: canais, riscos, controles, risco aceito, dados pessoais
  observabilidade.md  Parte 3 §4: plano, spans, métricas, SLI/SLO
tests/               test_agente.py, test_parte2.py, test_seguranca.py (Parte 3)
checkpoints/         gerado em tempo de execução, fora do git
```
