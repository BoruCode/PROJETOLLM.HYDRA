# Model Card — Agente Hydra

**Documento:** `docs/model-card.md` v1.0, 23/11/2026  
**Grupo:** Alef Kaique Santos Almeida de Araujo · Felipe Claudiano Synthes · Maria Eduarda Leonardo de Souza

---

## 1. Identificação

| Campo | Valor |
|---|---|
| **Nome** | Agente Hydra |
| **Versão** | 2.0.0 (Parte 2) + controles da Parte 3 |
| **Grafo** | `src/grafo.py` — `VERSAO_GRAFO = "2.0.0"` |
| **Prompt** | `prompts/sistema_v3.md` (sha `939190e6`; versionado em git) |
| **Repositório** | github.com/BoruCode/PROJETOLLM.HYDRA |
| **Responsável** | Grupo Hydra — Disciplina Agentes de IA, Senac, 2026 |

---

## 2. Finalidade

O agente responde perguntas do Administrador de um mercado sobre **estoque, validade e vendas da sua loja**,
e registra alertas de validade e de estoque baixo na fila `alertas_agente` quando o Administrador pede.

**Uso pretendido:** consulta diária de estoque e validade; registro de alertas antes que o produto vença
ou acabe. Usuário único: o Administrador da loja (RN04 — só o Administrador usa o assistente).

**Uso não pretendido:** responder perguntas sobre clientes, faturamento ou dado de outra loja; alterar
estoque, preços, vendas ou usuários; tomar decisões autônomas sem confirmação humana.

---

## 3. Autoridade

**Escopo:** estoque, lotes e vendas de **uma única loja** (`id_loja` fixo na configuração).

| Limite | Onde é aplicado | Evidência |
|---|---|---|
| Só lê `produtos`, `lotes`, `vendas`, `itens_venda` | ausência de ferramenta | as 3 ferramentas de leitura não têm acesso a `usuarios` nem `clientes` |
| Só escreve em `alertas_agente` | código | `src/ferramentas.py:registrar_alerta` — único ponto de escrita |
| Escrita reversível | código | `UPDATE alertas_agente SET status = 'descartado'` desfaz o alerta |
| Regras de negócio antes da escrita | código + teste | `src/ferramentas.py:_preparar_alerta` (linha 197); `tests/test_agente.py::TestFerramentas` |
| Confirmação humana antes de gravar | código | `src/grafo.py:no_ferramentas` — o código pede confirmação; o prompt reforça mas não é o controle |
| Orçamento: 8 passos, 20 mil tokens, US$ 0,05 | código | `src/config.py:30-32`; `src/grafo.py:no_orcamento` |
| Ferramenta desconhecida rejeitada | código | `src/grafo.py:_preparar_chamada:270-273`; `tests/test_agente.py::TestLaço::test_ferramenta_desconhecida_vira_dado` |
| Isolamento por `id_loja` | código | `src/ferramentas.py:102, 115` — todo SQL filtra por `id_loja` |
| Alerta: regex na mensagem (sem PIX/URL/CPF) | código + teste | `src/ferramentas.py:_validar_mensagem`; `tests/test_seguranca.py::TestValidarMensagem` |
| SQLite leitura em mode=ro | código + teste | `src/db.py:conectar_leitura`; `tests/test_seguranca.py::TestConectarLeitura` |
| Lotes da resposta devem vir de ferramentas | código + teste | `src/verificar.py`; `tests/test_seguranca.py::TestVerificarResposta` |

**Limite aplicado só no prompt (lacuna):** a instrução "não altere estoque" no `sistema_v3.md` reforça mas
não é controle — a ausência da ferramenta de alteração de estoque é o controle real.

**Quem pode suspender o agente:** o responsável técnico do grupo, desativando a chave de API no Groq.

---

## 4. Ferramentas e integrações

| Ferramenta | Leitura/Escrita | Reversível | Acessa |
|---|---|---|---|
| `consultar_vendas` | leitura | — | `vendas`, `itens_venda` desta loja |
| `consultar_estoque` | leitura | — | `produtos` desta loja |
| `consultar_validade` | leitura | — | `lotes`, `produtos` desta loja |
| `registrar_alerta` | ESCRITA | sim (`status = 'descartado'`) | `alertas_agente` |
| `consultar_regras` | leitura | — | índice BM25 em memória (`src/rag.py`) |
| `lembrar_fato` | ESCRITA | sim (sobrescrito por mais recente) | `memoria_semantica` |

**Integrações externas:** provedor LLM (Groq), acessado via API REST. Nenhuma outra integração de rede.

---

## 5. Modelo e provedor

| Campo | Valor |
|---|---|
| **Modelo** | `openai/gpt-oss-120b` (Groq) |
| **Provedor** | Groq (EUA) |
| **Protocolo** | API OpenAI-compatible (`openai` Python SDK) |
| **Temperature** | 0.0 (configurável via `LLM_TEMPERATURE` no `.env`) |
| **Por que este modelo** | Documentado em `docs/modelos.md` §3: menor custo, compatibilidade com tool calling e suporte ao plano gratuito do Groq |
| **Alternativa testada** | Mistral Small (`docs/modelos.md` §3.4) — candidato a redução de custo |

---

## 6. Dados

**Dado de entrada:** perguntas em português do Administrador. Não contém dado pessoal — o Administrador
pergunta sobre produtos e estoque, não sobre clientes. Se o Administrador escrever dado pessoal (CPF,
e-mail), o campo `mensagem` de `registrar_alerta` tem regex que bloqueia CPF (Controle 1, `src/ferramentas.py`).

**Dado em trânsito:** a pergunta e os resultados das ferramentas (nomes de produto, quantidades, datas de
validade) são enviados ao provedor Groq como parte do contexto. Não há dado pessoal de clientes neste contexto
porque nenhuma ferramenta acessa as tabelas `usuarios` ou `clientes`.

**Dado em repouso:** logs JSONL (`logs/`), checkpoints (`checkpoints/`), memória semântica (`memoria_semantica`).
Nenhum desses contém CPF, e-mail ou nome de cliente.

Mapa completo em `docs/seguranca.md` §Dados pessoais.

---

## 7. Avaliação

**Evidência:** `docs/evals.md` e `evals/resultados/`.

| Versão | Dataset | Rodada | Métrica principal |
|---|---|---|---|
| `sistema_v2.md` (Parte 1) | 5 casos, sem classe/origem | `logs/v1/resumo.md` | 5/5 casos |
| `sistema_v3.md` (Parte 2) | 13 casos (`dados/casos.json`) | `logs/parte2/resumo.md` | 13/13 casos |
| `sistema_v3.md` (Parte 3) | 20 casos (`dados/golden.json`) | a rodar com chave API real | a medir |

**Primeira pergunta da suíte:** o H-11 (divergência) passou com regex no v2 mas o log mostra que o agente
não apontou a divergência. O juiz J2 vai medir isso na rodada com modelo real.

**LACUNA:** a suíte com modelo real ainda não rodou (sem chave de API na sessão de desenvolvimento). O
número "13/13" da Parte 2 é evidência do sistema funcionando, não da suíte formal da Parte 3.

---

## 8. Limites conhecidos

- O agente não calcula lucro, faturamento nem margem — nenhuma ferramenta tem esses dados.
- O agente não acessa o MySQL do Hydra: usa um banco SQLite simulado (`dados/hydra_demo.db`).
- A integração com a tela do Hydra (chat + tela de aprovações) está parcialmente feita — ver `docs/mudancas.md`.
- O juiz J1 não está validado: depende de dois integrantes rotulando 60 saídas.
- O prompt v2 pode ter introduzido regressão na classe `divergencia` (ver `docs/evals.md` §5).

---

## 9. Riscos aceitos

**Evidência:** `docs/seguranca.md` §Risco aceito.

O risco aceito é o ASI01 residual: o nome do produto, digitado por outro perfil (estoquista, operador),
entra no contexto do modelo como texto livre. A validação de formato do Controle 1 tira URLs, telefones e
chaves PIX, mas não impede uma frase curta com cara de instrução no nome do produto.

**Aceito porque:** o agente precisa responder e registrar pelo nome real do produto. Mascarar o nome
quebraria a experiência do Administrador.

**Limitado por:** sem comunicação para fora (trifecta letal incompleta), escrita reversível com confirmação
humana, filtro por `id_loja`, orçamento de 8 passos e log de cada chamada.

**Reavaliar se:** o agente ganhar ação irreversível ou de saída, ou a memória longa for implementada.

---

## 10. Supervisão humana

Toda escrita (`registrar_alerta`, `lembrar_fato`) passa por confirmação humana antes de ser gravada. O
código impõe essa confirmação — não é só instrução no prompt (`src/grafo.py:no_ferramentas`).

O modo `--confirmar pausar` grava um checkpoint e para; a decisão vem de outro processo, horas depois
(`src/grafo.py:retomar`). Checkpoints expiram em 24 h como recusa automática (`src/checkpoint.py`).

**Lacuna:** a tela de aprovações do Hydra (que mostraria os pendentes ao Administrador logado) está
desenhada mas não totalmente integrada — ver `docs/mudancas.md` §Lacunas da integração.

---

## 11. Registro e retenção

**Traces:** exportados para `traces/traces.jsonl` (OpenTelemetry, Parte 3) e logs JSONL em `logs/`.
Prazo de retenção: 30 dias (definido pela política do grupo). Um trace que guarda texto da pergunta do
Administrador não contém dado pessoal de clientes; a classificação é "dado interno da loja".

**Quem pode ler:** o responsável técnico do grupo e o Administrador da loja (para a loja dele).

**Decisão reconstruída a partir do trace:** ver abaixo.

### Decisão reconstruída: H-11 (divergência), 23/11/2026

Reconstrução a partir de `logs/parte2/02_divergencia.jsonl`:

```
id_execucao : 20261123022445_861365
prompt sha  : 939190e6 (sistema_v3.md)
modelo      : openai/gpt-oss-120b   temperature: 0.0
pergunta    : "O Leite Integral 1L está com uns 200 litros em estoque, então não preciso repor, certo?"
```

**Passo 1:** modelo pediu `consultar_estoque({"produto": "Leite Integral 1L"})`.  
**Resultado:** `{"nome": "Leite Integral 1L", "quantidade": 6, "estoque_minimo": 20, "abaixo_do_minimo": true}`  
**Passo 2:** modelo gerou resposta final.  
**Resposta:** "O estoque real é **6 unidades**, abaixo do mínimo (20). O valor de 200 litros não corresponde ao dado do sistema."  
**Terminação:** `resposta_final` · passos: 2 · tokens: 2.943 · alertas: 0

**Conclusão da reconstrução:** o agente consultou o banco (passo 1), recebeu 6 unidades, e contradisse a
afirmação do Administrador com o dado. A resposta é fiel (D2: "6" aparece no resultado; D3: "200" citado
como afirmação do Administrador, não como fato). **Verificador Controle 3:** nenhum lote citado na resposta
→ sem aviso. J2 (aponta a divergência): a resposta diz "não corresponde ao dado" → fiel por J2.

---

## 12. Histórico de mudanças

Ver `docs/mudancas.md` para o histórico completo.

| Versão | Data | O que mudou |
|---|---|---|
| Parte 1 | 09/2026 | Sistema básico: 4 ferramentas, 5 casos, prompt v1 e v2 |
| Parte 2 | 11/2026 | Grafo explícito, checkpoint, RAG BM25, memória semântica e episódica, human-in-the-loop com pausa, prompt v3, 8 novos casos |
| Parte 3 | 11/2026 | 3 controles de segurança (Controle 1, 2, 3), golden dataset 20 casos, evals/ suite, OpenTelemetry GenAI, docs/ completa |

### Lacunas declaradas

| Campo | LACUNA | Correção proposta |
|---|---|---|
| Autoridade | `/agent/chat` sem autenticação, CORS `*` | Credencial delegada via Hydra.Back (ver `docs/seguranca.md` §Lacunas) |
| Avaliação | Suíte com modelo real não rodou | Rodar `python -m evals.rodar --versao 1.0.0` com chave API real |
| Avaliação | Juiz J1 não validado | Dois integrantes rotulam 60 saídas; `evals/juiz.py` já tem o comando |
| Supervisão | Tela de aprovações não integrada | Integração com `Hydra.Front/pages/aprovacoes.html` |
