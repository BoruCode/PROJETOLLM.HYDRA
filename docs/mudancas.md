# Mudanças da Parte 3

**Documento:** `docs/mudancas.md` v1.0, 23/11/2026  
**Grupo:** Alef Kaique Santos Almeida de Araujo · Felipe Claudiano Synthes · Maria Eduarda Leonardo de Souza

---

## O que estava errado na Parte 2 (correções obrigatórias)

Nenhum defeito apontado na correção formal da Parte 2 (a correção ainda não chegou no momento
desta entrega). Os defeitos identificados pelo próprio grupo:

1. **Regressão J2 no H-11:** o prompt v2 → v3 melhorou de 5/5 para 13/13, mas o log
   `logs/parte2/02_divergencia.jsonl` mostra que o agente deu o número 6 sem apontar explicitamente
   que "200" estava errado. O H-11 passou no regex `\b6\b` mas pode estar falhando em J2. A suíte
   da Parte 3 vai medir isso com o modelo real.

2. **`python -m src.manutencao` morria com "no such table"** se o banco não existisse. Corrigido:
   `src/manutencao.py` agora chama `criar_banco` antes de tentar expirar pendentes.

---

## O que mudou na Parte 3

### Segurança

| Arquivo | Mudança | Motivo |
|---|---|---|
| `src/ferramentas.py` | `_validar_mensagem()` + `_RE_DADO_SUSPEITO` (regex para PIX/URL/CPF/tel) | Controle 1 — ASI02/ASI01 |
| `src/db.py` | `conectar_leitura()` — SQLite `mode=ro` | Controle 2 — ASI03 |
| `src/verificar.py` | novo arquivo — `verificar_lotes_na_resposta()` | Controle 3 — ASI09 |
| `src/grafo.py` | chamada ao Controle 3 em `no_finalizar` | integração do verificador |
| `src/agente.py` | campo `aviso_verificador` em `Estado` | registra lotes sem fonte |
| `tests/test_seguranca.py` | 21 novos testes dos 3 controles | evidência dos controles |
| `docs/seguranca.md` | criado a partir do rascunho de `exercicios/aula14-respostas.md` | §3 da entrega |

### Avaliação

| Arquivo | Mudança |
|---|---|
| `dados/golden.json` | golden dataset v1.0.0 com 20 casos H-01..H-20 (origem, classe, por_que_existe, revisor) |
| `evals/__init__.py` | novo módulo |
| `evals/rodar.py` | suíte `python -m evals.rodar --versao x.y.z` |
| `evals/comparar.py` | comparação `python -m evals.comparar <rodada-A> <rodada-B>` |
| `evals/juiz.py` | juiz J1 (fidelidade, rubrica v1.0.0, modelo Llama 3.3 70B) |
| `docs/evals.md` | §1 dataset, §2 níveis, §3 juiz, §4 comandos, §5 resultados |

### Observabilidade

| Arquivo | Mudança |
|---|---|
| `src/otel.py` | novo — spans OpenTelemetry GenAI (`invoke_agent`, `chat`, `execute_tool`) |
| `src/grafo.py` | span raiz em `executar()`; span chat em `no_modelo`; span tool em `_registrar` |
| `docs/observabilidade.md` | plano, árvore de spans, modos de falha, métricas, SLI/SLO |
| `requirements.txt` | `opentelemetry-sdk` e `opentelemetry-api` adicionados |

### Governança

| Arquivo | Mudança |
|---|---|
| `docs/model-card.md` | 12 campos com evidências; decisão reconstruída do trace; LACUNAS |

### Projeto

| Arquivo | Mudança |
|---|---|
| `README.md` | atualizado: Parte 3, suíte, controles, traces |
| `docs/mudancas.md` | este arquivo |

---

## Lacunas da integração Hydra (declaradas, não implementadas)

| Lacuna | Descrição | Impacto |
|---|---|---|
| Credencial delegada | `/agent/chat` não tem autenticação; CORS é `*` | ASI03 parcialmente mitigado |
| Usuário MySQL menor privilégio | exemplo usa `root`; `hydra_agente` não criado | ASI03 parcialmente mitigado |
| Tela de aprovações | `pages/aprovacoes.html` desenhada, não integrada | RN27 (só Administrador usa) não totalmente aplicada |
| Suíte com modelo real | depende de chave API do Groq no `.env` | números de qualidade não medidos |
| Juiz J1 validado | depende de rotulação humana de 60 saídas | J1 não adotado |
| Mitigações Docker ASI04 | digest, `USER www-data`, `--require-hashes` | supply chain parcialmente mitigado |
| Validação de `nome`/`lote` no Hydra.Back | `ProdutoController::validar()` só verifica nome vazio; `lote` só faz `trim()` — sem limite de comprimento nem formato | ASI01 residual maior do que o declarado; ver `docs/seguranca.md` §Lacunas |

---

## Verificação do histórico do `.env`

```bash
git log --all -- .env               # saída: vazia
git log --all -S "OPENAI_API_KEY=" --oneline   # saída: vazia
```

Nenhuma chave de API foi commitada. O `.env` está no `.gitignore` desde o commit inicial.
