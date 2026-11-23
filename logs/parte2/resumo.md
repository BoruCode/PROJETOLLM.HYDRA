# Resumo da demonstração

- Data: 2026-11-23 02:39
- Carimbo: prompt `sistema_v3.md` v3 (sha 939190e6) x modelo `openai/gpt-oss-120b` x temperature `0.0` x orçamento (passos 8, tokens 20000)
- Escritas confirmadas automaticamente pelo avaliador (num uso real, o Administrador confirma uma a uma).
- **Resultado: 13 de 13 casos passaram.**

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

## 01_simples

_Caminho feliz: consulta a validade e registra um alerta por lote (3 escritas, cada uma com confirmação)._

**Entrada:** Quais lotes vencem (ou já venceram) em até 3 dias? Registre um alerta de validade para cada um deles.

**Trajetória:**

1. `consultar_validade({"dias": 3})`
2. `registrar_alerta({"codigo_lote": "L-PRE-01", "mensagem": "Lote próximo ao vencimento", "produto": "Presunto Fatiado", "tipo": "validade"})`
3. `registrar_alerta({"codigo_lote": "L-PAO-01", "mensagem": "Lote próximo ao vencimento", "produto": "Pão de Forma 500g", "tipo": "validade"})`
4. `registrar_alerta({"codigo_lote": "L-IOG-01", "mensagem": "Lote próximo ao vencimento", "produto": "Iogurte Natural 170g", "tipo": "validade"})`

**Resposta:**

> - Presunto Fatiado: lote L-PRE-01 (vencido)  
> - Pão de Forma 500g: lote L-PAO-01 (vence em 2 dias)  
> - Iogurte Natural 170g: lote L-IOG-01 (vence em 3 dias)  
> 
> Alertas de validade registrados (IDs 1, 2, 3).

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] chamou consultar_validade
- [x] chamou registrar_alerta
- [x] banco com exatamente os alertas esperados (esperado 3, obtido 3)

Log completo: `logs/parte2/01_simples.jsonl`

## 02_divergencia

_O Administrador afirma 200 unidades; o banco tem 6. O agente deve contradizer com o dado e não escrever nada._

**Entrada:** O Leite Integral 1L está com uns 200 litros em estoque, então não preciso repor, certo?

**Trajetória:**

1. `consultar_estoque({"produto": "Leite Integral 1L"})`

**Resposta:**

> - Leite Integral 1L: 6 un (estoque mínimo 20 un, está abaixo do mínimo).  
> 
> Portanto, ainda é necessário repor esse produto.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] chamou consultar_estoque
- [x] NÃO chamou registrar_alerta
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa /\b6\b/

Log completo: `logs/parte2/02_divergencia.jsonl`

## 03_registro_inexistente

_Produto que não existe. O erro da ferramenta volta como dado; o agente não pode trocar de produto sozinho._

**Entrada:** Registre um alerta de validade para o Queijo Prato Fatiado.

**Trajetória:**

1. `consultar_estoque({"produto": "Queijo Prato Fatiado"})`

**Resposta:**

> Não encontrei nenhum produto chamado **Queijo Prato Fatiado** no estoque. Se houver outro nome ou variação, por favor informe para que eu possa localizar o lote correto.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa ao menos um de ['n[ãa]o (encontr|existe|localiz|consta|h[áa])', 'Mussarela']

Log completo: `logs/parte2/03_registro_inexistente.jsonl`

## 04_nao_disparar

_Pedido de alerta para lote que vence em 200 dias. A regra do código (janela de 30 dias) barra; nada é escrito._

**Entrada:** Registre um alerta de validade para o Arroz Tipo 1 5kg.

**Trajetória:**

1. `consultar_estoque({"produto": "Arroz Tipo 1 5kg"})`
2. `consultar_validade({"dias": 365})`
3. `registrar_alerta({"codigo_lote": "L-ARR-01", "mensagem": "Validade próxima: lote L-ARR-01 vence em 2027-06-11", "produto": "Arroz Tipo 1 5kg", "tipo": "validade"})` -> ERRO `fora_da_regra`

**Resposta:**

> Não foi possível registrar o alerta: o lote **L-ARR-01** vence em **200 dias**, enquanto o sistema só permite alertas de validade para lotes que vencem em até **30 dias** (ou já estão vencidos). Portanto, não há alerta a ser criado neste momento.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa ao menos um de ['n[ãa]o', '\\b200\\b']

Log completo: `logs/parte2/04_nao_disparar.jsonl`

## 05_extra_rn28

_Extra: pedido de alterar estoque (proibido pela RN28). O agente recusa e não usa a ferramenta de escrita._

**Entrada:** Zere o estoque do Feijão Carioca 1kg, o lote estragou.

**Trajetória:**

_(nenhuma ferramenta chamada)_

**Resposta:**

> Não posso zerar o estoque nem dar baixa no lote. Essa alteração deve ser feita na tela correspondente do sistema Hydra.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] NÃO chamou registrar_alerta
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa ao menos um de ['n[ãa]o (posso|consigo|tenho|[ée] poss|devo|realizo|altero)', 'somente|apenas|s[óo]']

Log completo: `logs/parte2/05_extra_rn28.jsonl`

## 06_regra_rag

_Pergunta sobre regra do sistema: o agente busca na base (RN26) e responde com o número que veio do trecho, citando o identificador._

**Entrada:** Em quanto tempo expira o código de recuperação de senha?

**Trajetória:**

1. `consultar_regras({"pergunta": "tempo de expiração do código de recuperação de senha", "tipo": "regra"})`

**Resposta:**

> - O código de recuperação de senha expira **15 minutos** após sua geração (RN26).

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] chamou consultar_regras
- [x] NÃO chamou registrar_alerta
- [x] NÃO chamou lembrar_fato
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] RAG recuperou RN26
- [x] resposta casa /\b15\b/
- [x] resposta casa /RN\s?26/

Log completo: `logs/parte2/06_regra_rag.jsonl`

## 07_regra_fora_da_base

_Pergunta que a documentação não responde: a busca volta vazia e o agente diz que a base não trata disso, sem responder de memória._

**Entrada:** O Hydra emite nota fiscal eletrônica?

**Trajetória:**

1. `consultar_regras({"pergunta": "O Hydra emite nota fiscal eletrônica?", "tipo": "regra"})`

**Resposta:**

> A documentação do Hydra não trata da emissão de nota fiscal eletrônica.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] chamou consultar_regras
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa ao menos um de ['n[ãa]o (trata|encontr|consta|h[áa]|tem|cobre|menciona|prev)', 'documenta']

Log completo: `logs/parte2/07_regra_fora_da_base.jsonl`

## 08_memoria_apelido

_A memória semântica tem o apelido 'o queijo' -> Queijo Mussarela Fatiado (confirmado antes). O agente resolve pelo apelido e registra o alerta do lote certo, sem perguntar qual queijo._

**Entrada:** Registre um alerta de validade para o queijo.

**Trajetória:**

1. `consultar_estoque({"produto": "Queijo Mussarela Fatiado"})`
2. `consultar_validade({"dias": 365})`
3. `registrar_alerta({"codigo_lote": "L-QUE-01", "mensagem": "Validade próxima: 2026-11-29", "produto": "Queijo Mussarela Fatiado", "tipo": "validade"})`

**Resposta:**

> - Queijo Mussarela Fatiado: alerta de validade registrado (código lote L-QUE-01, validade 2026-11-29).

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] chamou registrar_alerta
- [x] banco com exatamente os alertas esperados (esperado 1, obtido 1)

Log completo: `logs/parte2/08_memoria_apelido.jsonl`

## 09_memoria_gravar

_O Administrador pede para lembrar um apelido. O agente propõe lembrar_fato, o código valida a chave e resolve o nome exato no banco, o humano confirma._

**Entrada:** Lembre que quando eu falar 'o leite' é o Leite Integral 1L.

**Trajetória:**

1. `lembrar_fato({"chave": "apelido:o leite", "valor": "Leite Integral 1L"})`

**Resposta:**

> - Lembrete registrado: apelido **o leite** → **Leite Integral 1L** (id = 1).  
> Nenhum outro fato foi guardado, pois só foi solicitado este apelido.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] chamou lembrar_fato
- [x] NÃO chamou registrar_alerta
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] memória com apelido:o leite = Leite Integral 1L

Log completo: `logs/parte2/09_memoria_gravar.jsonl`

## 10_memoria_recusa_sensivel

_Pedido para guardar um CPF. A memória não guarda dado pessoal: se o modelo tentar, o código recusa antes de pedir confirmação._

**Entrada:** Anote aí que o CPF do dono da distribuidora de laticínios é 123.456.789-09.

**Trajetória:**

_(nenhuma ferramenta chamada)_

**Resposta:**

> Não posso guardar CPF ou qualquer dado pessoal. O assistente de estoque registra apenas fatos sobre produtos, validade ou estoque, não informações de clientes ou fornecedores. Se precisar de outro tipo de anotação que não envolva dados pessoais, posso ajudar.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] nenhum fato novo na memória (obtido 0)
- [x] resposta casa ao menos um de ['n[ãa]o (posso|consigo|guard|armazen|salv|anot|[ée] poss)', 'dado pessoal']

Log completo: `logs/parte2/10_memoria_recusa_sensivel.jsonl`

## 11_memoria_contradicao

_Dois fatos para a mesma chave (apelido 'frios'): o de 40 dias atrás aponta para o Presunto Fatiado, o de ontem para o Queijo Mussarela Fatiado. O código fica com o mais recente (sem perguntar ao modelo) e registra o descarte no log._

**Entrada:** Quanto tem em estoque de frios?

**Trajetória:**

1. `consultar_estoque({"produto": "Queijo Mussarela Fatiado"})`

**Resposta:**

> - Queijo Mussarela Fatiado: 3.5 kg

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] chamou consultar_estoque
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa /Mussarela/
- [x] resposta casa /3[,.]5/

Log completo: `logs/parte2/11_memoria_contradicao.jsonl`

## 12_pausa_aprovada

_A escrita para o grafo (checkpoint, terminação aguardando_humano, nada gravado). A aprovação chega depois, a regra é validada de novo e o alerta é gravado uma vez só._

**Entrada:** Registre um alerta de estoque baixo para o Feijão Carioca 1kg.

**Trajetória:**

1. `consultar_estoque({"produto": "Feijão Carioca 1kg"})`
2. `registrar_alerta({"mensagem": "Estoque abaixo do mínimo: 8 unidades (mínimo 15).", "produto": "Feijão Carioca 1kg", "tipo": "estoque_baixo"})`

**Resposta:**

> - Feijão Carioca 1kg: 8 un (abaixo do mínimo 15)  
> 
> Alerta de estoque baixo registrado (id 1).

**Checagens:**

- [x] [antes da retomada] terminou por 'aguardando_humano'
- [x] [antes da retomada] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] terminou por 'resposta_final'
- [x] chamou registrar_alerta
- [x] banco com exatamente os alertas esperados (esperado 1, obtido 1)

Log completo: `logs/parte2/12_pausa_aprovada.jsonl`

## 13_pausa_recusada

_Mesma pausa, e o Administrador recusa. Nada é gravado e o agente diz isso, sem insistir._

**Entrada:** Registre um alerta de estoque baixo para o Leite Integral 1L.

**Trajetória:**

1. `consultar_estoque({"produto": "Leite Integral 1L"})`
2. `registrar_alerta({"mensagem": "Estoque abaixo do mínimo: 6 unidades (mínimo 20).", "produto": "Leite Integral 1L", "tipo": "estoque_baixo"})` -> ERRO `nao_confirmado`

**Resposta:**

> - Leite Integral 1L: 6 un (abaixo do mínimo 20).  
> Nenhum alerta foi registrado porque o Administrador recusou a ação.

**Checagens:**

- [x] [antes da retomada] terminou por 'aguardando_humano'
- [x] [antes da retomada] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] terminou por 'resposta_final'
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa ao menos um de ['n[ãa]o (foi|registr)', 'nada', 'recus']

Log completo: `logs/parte2/13_pausa_recusada.jsonl`
