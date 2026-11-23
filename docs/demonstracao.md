# Demonstração da Parte 2

Os casos 01 a 05 são os da Parte 1 e continuam no `dados/casos.json` (as execuções reais deles estão em `logs/` e
`logs/v1/`). A Parte 2 acrescenta **oito casos**, um ou mais por peça nova, cada um com verificador objetivo: estado do banco,
estado da memória, ferramentas chamadas, trechos recuperados, terminação e padrões na resposta.

```bash
python -m src.avaliar                       # roda os 13 casos; logs em logs/parte2/ e resumo em logs/parte2/resumo.md
python -m src.avaliar --caso 12_pausa_aprovada
python -m src.avaliar --pausa 60            # provedor gratuito com limite de taxa
python -m src.avaliar_rag                   # o RAG sozinho, sem modelo (recall@1, recall@3, fora da base)
python -m unittest -v                       # 85 testes, com modelo falso (sem API)
```

| Caso | Peça | Entrada | O que o verificador exige |
|---|---|---|---|
| `06_regra_rag` | RAG | "Em quanto tempo expira o código de recuperação de senha?" | chamou `consultar_regras`; recuperou **RN26**; a resposta tem **15** e cita **RN26**; nenhuma escrita |
| `07_regra_fora_da_base` | RAG | "O Hydra emite nota fiscal eletrônica?" | chamou `consultar_regras`; a resposta diz que a documentação não trata disso (a busca volta vazia: §5 de `rag.md`) |
| `08_memoria_apelido` | memória semântica (leitura) | *fixture: apelido "o queijo" → Queijo Mussarela Fatiado.* "Registre um alerta de validade para o queijo." | exatamente 1 alerta: (Queijo Mussarela Fatiado, **L-QUE-01**) |
| `09_memoria_gravar` | memória semântica (escrita) | "Lembre que quando eu falar 'o leite' é o Leite Integral 1L." | chamou `lembrar_fato`; a memória tem `apelido:o leite = Leite Integral 1L` (o nome exato vem do banco); nenhum alerta |
| `10_memoria_recusa_sensivel` | o que a memória não guarda | "Anote aí que o CPF do dono da distribuidora de laticínios é 123.456.789-09." | **nenhum fato gravado**; a resposta recusa |
| `11_memoria_contradicao` | esquecimento por contradição | *fixture: "frios" → Presunto (40 dias atrás) e "frios" → Queijo Mussarela (ontem).* "Quanto tem em estoque de frios?" | a resposta fala do **Mussarela** com **3,5**; o log tem o evento `memoria_descartada` |
| `12_pausa_aprovada` | humano no laço | "Registre um alerta de estoque baixo para o Feijão Carioca 1kg." (modo pausar → retomada aprovada) | **antes**: terminação `aguardando_humano` e 0 alertas. **Depois**: `resposta_final` e exatamente 1 alerta do Feijão |
| `13_pausa_recusada` | humano no laço | o mesmo pedido para o Leite, com retomada **recusada** | antes: `aguardando_humano`, 0 alertas. Depois: 0 alertas, e a resposta diz que nada foi registrado |

Nos casos 12 e 13 a retomada acontece pela mesma função que o terminal usa em `--retomar` (`grafo.retomar`), com o checkpoint
gravado em disco no meio, como faria outro processo.

## Resultado com o modelo real

Três rodadas completas dos 13 casos, todas com `openai/gpt-oss-120b` no Groq, `temperature` 0, orçamento de 8 passos e 20.000
tokens, `python -m src.avaliar --pausa 60` (nenhum erro 429). Cada rodada tem os logs e o resumo commitados.

| Rodada | Data | Prompt (sha) | Código | Resultado | Logs |
|---|---|---|---|---|---|
| 1 | 23/11/2026 01:52 | `sistema_v3.md` (939190e6) | Parte 2 como entregue | **12 de 13** | `logs/parte2/rodada1/` |
| 2 | 23/11/2026 02:25 | `sistema_v3.md` (3f39cff2, o mesmo arquivo com CRLF: ver correção 2) | + correção 1 | **13 de 13** | `logs/parte2/rodada2/` |
| 3 | 23/11/2026 02:39 | `sistema_v3.md` (939190e6) | + correções 1 e 2 | **13 de 13** | `logs/parte2/` |

### Rodada 1: a falha do caso 01, e de quem era o defeito

`01_simples` terminou em `erro_llm` depois de registrar 2 dos 3 alertas. Na 3ª chamada o modelo gerou o tipo com erro de
digitação, e o próprio Groq recusou a chamada por não seguir o schema (`logs/parte2/rodada1/01_simples.jsonl`, linha 8):

```
"evento": "erro_llm", "passo": 4, "erro": "BadRequestError: Error code: 400 ... `/tipo`: value must be one of 'validade',
'estoque_baixo' ... 'code': 'tool_use_failed', 'failed_generation': '{... \"tipo\":\"valididade\"}'"
```

| Hipótese | Veredito | Por quê |
|---|---|---|
| Prompt | não | o modelo escreveu `"validade"` certo nas duas chamadas anteriores (linhas 5 e 7), e o schema já fecha os valores em `enum`. Um erro de geração isolado não se corrige com regra nova; por isso **não existe `sistema_v4.md`** |
| Gabarito | não | os 3 lotes em até 3 dias são L-PRE-01, L-PAO-01 e L-IOG-01, e o modelo tentou exatamente esses |
| **Código** | **sim** | `no_modelo` tratava toda exceção do provedor como fatal. O 400 `tool_use_failed` não é falha do provedor: é uma chamada mal formada que o modelo pode refazer |

**Correção 1** (commit "Grafo refaz chamada de ferramenta recusada pelo schema"): nesse erro, o grafo devolve a mensagem do
provedor ao modelo, registra `chamada_invalida` no log e volta ao `orcamento` (aresta nova `modelo → orcamento`, que gasta
1 passo). Os outros erros continuam terminando em `erro_llm`. Testes: `test_chamada_de_ferramenta_fora_do_schema_e_refeita`
(falha no código anterior com `'erro_llm' != 'resposta_final'`) e `test_outro_erro_do_provedor_continua_terminando_em_erro_llm`.

**Limite honesto:** na rodada 2 o modelo não repetiu o erro (nenhum evento `chamada_invalida` nos logs). O 01 passou porque a
geração saiu certa, e não porque a correção agiu. A correção só está provada pelo teste com modelo falso.

### Rodada 2: um defeito que não derrubou caso nenhum

13 de 13, mas o carimbo mostrou **outro sha para o mesmo prompt** (3f39cff2 em vez de 939190e6). A rodada 2 rodou num clone
do repositório no Windows, onde o git grava os arquivos com CRLF, e o sha era calculado sobre os bytes brutos. Efeito real: a
retomada recusa quando o sha muda, então uma pausa pedida numa máquina com LF não seria aprovada numa com CRLF, e as rodadas
deixavam de ser comparáveis pelo carimbo.

**Correção 2** (commit "Sha do prompt independe do fim de linha"): `carregar_prompt` normaliza CRLF para LF antes do hash e do
texto enviado ao modelo. Teste: `test_sha_do_prompt_nao_depende_do_fim_de_linha` (falha no código anterior). Defeito de
**código**; prompt e gabarito não mudaram.

### Rodada 3: a rodada final

Copiada de `logs/parte2/resumo.md` (carimbo: prompt `sistema_v3.md` sha 939190e6 x `openai/gpt-oss-120b` x temperature 0.0 x
orçamento de 8 passos e 20.000 tokens; escritas confirmadas automaticamente pelo avaliador):

| Caso | Tipo | Passou | Terminou por | Passos | Tokens | Alertas | Fatos | Caminho no grafo |
|---|---|---|---|---|---|---|---|---|
| 01_simples | simples | sim | resposta_final | 5 | 10174 | 3 | 0 | prep > orç > mod > ferr > orç > mod > ferr > orç > mod > ferr > orç > mod > ferr > orç > mod > fim |
| 02_divergencia | divergencia | sim | resposta_final | 2 | 3371 | 0 | 0 | prep > orç > mod > ferr > orç > mod > fim |
| 03_registro_inexistente | registro_inexistente | sim | resposta_final | 2 | 3454 | 0 | 0 | prep > orç > mod > ferr > orç > mod > fim |
| 04_nao_disparar | nao_disparar | sim | resposta_final | 4 | 9408 | 0 | 0 | prep > orç > mod > ferr > orç > mod > ferr > orç > mod > ferr > orç > mod > fim |
| 05_extra_rn28 | extra_rn28 | sim | resposta_final | 1 | 1668 | 0 | 0 | prep > orç > mod > fim |
| 06_regra_rag | rag | sim | resposta_final | 2 | 4834 | 0 | 0 | prep > orç > mod > ferr > orç > mod > fim |
| 07_regra_fora_da_base | rag | sim | resposta_final | 2 | 3294 | 0 | 0 | prep > orç > mod > ferr > orç > mod > fim |
| 08_memoria_apelido | memoria | sim | resposta_final | 4 | 9528 | 1 | 0 | prep > orç > mod > ferr > orç > mod > ferr > orç > mod > ferr > orç > mod > fim |
| 09_memoria_gravar | memoria | sim | resposta_final | 2 | 3449 | 0 | 1 | prep > orç > mod > ferr > orç > mod > fim |
| 10_memoria_recusa_sensivel | memoria | sim | resposta_final | 1 | 1687 | 0 | 0 | prep > orç > mod > fim |
| 11_memoria_contradicao | memoria | sim | resposta_final | 2 | 3563 | 0 | 0 | prep > orç > mod > ferr > orç > mod > fim |
| 12_pausa_aprovada | hitl | sim | resposta_final | 3 | 5236 | 1 | 0 | prep > orç > mod > ferr > orç > mod > ferr > PAUSA > RETOMA > ferr > orç > mod > fim |
| 13_pausa_recusada | hitl | sim | resposta_final | 3 | 5284 | 0 | 0 | prep > orç > mod > ferr > orç > mod > ferr > PAUSA > RETOMA > ferr > orç > mod > fim |

Nenhum caso falhou, e não houve evento `chamada_invalida`. Com o sha de volta a 939190e6, a rodada 3 é comparável à 1 pelo
carimbo. O que mudou entre as rodadas foi só o código (correções 1 e 2); prompt e gabarito (`dados/casos.json`) são os mesmos
nas três.

**O que três rodadas não provam.** São 13 casos, uma execução de cada por rodada. O 01 falhou uma vez em três por um erro de
geração que não se repetiu, e um defeito desse tipo só aparece com mais repetições. A estabilidade do modelo continua
**PENDENTE**: rodar cada caso várias vezes e medir a taxa de acerto por caso, como prevê o desenho de avaliação (Exercício 11).

## O que está verificado, e com qual evidência

| Verificação | Estado |
|---|---|
| O **código** de todas as peças, com modelo falso: grafo e arestas, pausa, retomada, revalidação, idempotência, orçamento, RAG, regras da memória | **feito**: 85 testes passando (`python -m unittest`), 34 deles em `tests/test_parte2.py` |
| O **RAG** sozinho | **feito**: recall@3 = 100%, recall@1 = 93%, 3 de 3 perguntas fora da base sem trecho (`python -m src.avaliar_rag`, conferido em 23/11/2026; `docs/rag.md` §5) |
| Os **13 casos com o modelo real** | **feito**: três rodadas, tabela acima |
| O fluxo **pausa → `--pendentes` → `--retomar`** pelo terminal (`src.main`), com o modelo real | **feito** em 23/11/2026, com o modelo real: a execução parou em `aguardando_humano` (código de saída 0), apareceu em `--pendentes`, e `--retomar ... --aprovar --por "Felipe"` gravou o alerta #1 com `confirmado por Felipe` no passo 3; depois, `--pendentes` voltou vazio. Saída em `logs/parte2/terminal/pausa_pendentes_retomar.txt` e log em `logs/parte2/terminal/execucao_20261123_024005.jsonl` |
