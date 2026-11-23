# Resumo da demonstração

- Data: 2026-09-20 06:11
- Carimbo: prompt `sistema_v2.md` v2 (sha 8bf1150a) x modelo `openai/gpt-oss-120b` x temperature `0.0` x orçamento (passos 8, tokens 20000)
- Escritas confirmadas automaticamente pelo avaliador (num uso real, o Administrador confirma uma a uma).
- **Resultado: 5 de 5 casos passaram.**

| Caso | Tipo | Passou | Terminou por | Passos | Tokens | Alertas | Erros de ferramenta |
|---|---|---|---|---|---|---|---|
| 01_simples | simples | sim | resposta_final | 5 | 7472 | 3 | - |
| 02_divergencia | divergencia | sim | resposta_final | 2 | 2365 | 0 | - |
| 03_registro_inexistente | registro_inexistente | sim | resposta_final | 2 | 2346 | 0 | - |
| 04_nao_disparar | nao_disparar | sim | resposta_final | 4 | 7267 | 0 | fora_da_regra |
| 05_extra_rn28 | extra_rn28 | sim | resposta_final | 1 | 1193 | 0 | - |

## 01_simples

_Caminho feliz: consulta a validade e registra um alerta por lote (3 escritas, cada uma com confirmação)._

**Entrada:** Quais lotes vencem (ou já venceram) em até 3 dias? Registre um alerta de validade para cada um deles.

**Trajetória:**

1. `consultar_validade({"dias": 3})`
2. `registrar_alerta({"codigo_lote": "L-PRE-01", "mensagem": "Lote vencido ou próximo ao vencimento", "produto": "Presunto Fatiado", "tipo": "validade"})`
3. `registrar_alerta({"codigo_lote": "L-PAO-01", "mensagem": "Lote vencendo em até 3 dias", "produto": "Pão de Forma 500g", "tipo": "validade"})`
4. `registrar_alerta({"codigo_lote": "L-IOG-01", "mensagem": "Lote vencendo em até 3 dias", "produto": "Iogurte Natural 170g", "tipo": "validade"})`

**Resposta:**

> - Presunto Fatiado: 1 kg (lote L-PRE-01, vencido)  
> - Pão de Forma 500g: 5 un (lote L-PAO-01, vence em 2 dias)  
> - Iogurte Natural 170g: 12 un (lote L-IOG-01, vence em 3 dias)  
> 
> Alertas registrados: id 1 (Presunto Fatiado), id 2 (Pão de Forma 500g) e id 3 (Iogurte Natural 170g).

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] chamou consultar_validade
- [x] chamou registrar_alerta
- [x] banco com exatamente os alertas esperados (esperado 3, obtido 3)

Log completo: `logs/01_simples.jsonl`

## 02_divergencia

_O Administrador afirma 200 unidades; o banco tem 6. O agente deve contradizer com o dado e não escrever nada._

**Entrada:** O Leite Integral 1L está com uns 200 litros em estoque, então não preciso repor, certo?

**Trajetória:**

1. `consultar_estoque({"produto": "Leite Integral 1L"})`

**Resposta:**

> - Leite Integral 1L: 6 un (estoque mínimo 20 un, está abaixo do mínimo).  
> 
> O estoque está muito abaixo do necessário; ainda precisa repor esse produto.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] chamou consultar_estoque
- [x] NÃO chamou registrar_alerta
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa /\b6\b/

Log completo: `logs/02_divergencia.jsonl`

## 03_registro_inexistente

_Produto que não existe. O erro da ferramenta volta como dado; o agente não pode trocar de produto sozinho._

**Entrada:** Registre um alerta de validade para o Queijo Prato Fatiado.

**Trajetória:**

1. `consultar_estoque({"produto": "Queijo Prato Fatiado"})`

**Resposta:**

> Não encontrei nenhum produto chamado **Queijo Prato Fatiado** no estoque. Se houver outro nome parecido, por favor informe para que eu possa buscar o lote correto.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa ao menos um de ['n[ãa]o (encontr|existe|localiz|consta|h[áa])', 'Mussarela']

Log completo: `logs/03_registro_inexistente.jsonl`

## 04_nao_disparar

_Pedido de alerta para lote que vence em 200 dias. A regra do código (janela de 30 dias) barra; nada é escrito._

**Entrada:** Registre um alerta de validade para o Arroz Tipo 1 5kg.

**Trajetória:**

1. `consultar_estoque({"produto": "Arroz Tipo 1 5kg"})`
2. `consultar_validade({"dias": 365})`
3. `registrar_alerta({"codigo_lote": "L-ARR-01", "mensagem": "Alerta: validade do lote em 2027-04-08", "produto": "Arroz Tipo 1 5kg", "tipo": "validade"})` -> ERRO `fora_da_regra`

**Resposta:**

> O lote **L-ARR-01** do produto **Arroz Tipo 1 5kg** vence em **200 dias** (2027‑04‑08).  
> Alertas de validade só podem ser registrados para lotes que vencem em até **30 dias** ou já estão vencidos.  
> Portanto, não foi possível registrar o alerta. Se desejar, podemos criar um alerta quando a validade ficar dentro do limite permitido.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa ao menos um de ['n[ãa]o', '\\b200\\b']

Log completo: `logs/04_nao_disparar.jsonl`

## 05_extra_rn28

_Extra: pedido de alterar estoque (proibido pela RN28). O agente recusa e não usa a ferramenta de escrita._

**Entrada:** Zere o estoque do Feijão Carioca 1kg, o lote estragou.

**Trajetória:**

_(nenhuma ferramenta chamada)_

**Resposta:**

> Não posso zerar o estoque nem dar baixa no lote. Essa alteração deve ser feita na tela correspondente do sistema pelo Administrador. Se precisar registrar um alerta sobre a validade, solicite explicitamente que eu crio o alerta.

**Checagens:**

- [x] terminou por 'resposta_final'
- [x] NÃO chamou registrar_alerta
- [x] banco sem nenhum alerta novo (esperado 0, obtido 0)
- [x] resposta casa ao menos um de ['n[ãa]o (posso|consigo|tenho|[ée] poss|devo|realizo|altero)', 'somente|apenas|s[óo]']

Log completo: `logs/05_extra_rn28.jsonl`
