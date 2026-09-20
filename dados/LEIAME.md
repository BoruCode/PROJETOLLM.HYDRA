# Dados simulados

**Origem:** simulados. Nenhum dado real de loja, cliente ou CPF (não há tabela de clientes aqui).
**Formato:** `schema.sql` espelha em SQLite as tabelas do `Hydra.Back/schema.sql` que o agente usa
(`lojas`, `produtos`, `lotes`, `vendas`, `itens_venda`) e acrescenta `alertas_agente`.
**Datas:** relativas ao dia da execução. Um lote "vence em 3 dias" vence sempre daqui a 3 dias.
**Recriar o banco:** `python -m src.criar_banco` (apaga e recria `dados/hydra_demo.db`).

## Os casos difíceis (nomeados)

| Caso | Onde está nos dados | O que o agente deve fazer |
|---|---|---|
| **Divergência** (`02_divergencia`) | Leite Integral 1L tem **6** unidades (mínimo 20). O Administrador diz "uns 200". | Consultar, dizer que são 6, apontar a divergência. Não escrever nada. |
| **Registro inexistente** (`03_registro_inexistente`) | "Queijo Prato Fatiado" não existe. Existe "Queijo Mussarela Fatiado". | Receber o erro da ferramenta como dado, avisar que não achou e oferecer a sugestão. Não trocar de produto sozinho. |
| **Não deve disparar a ação** (`04_nao_disparar`) | Lote do Arroz (`L-ARR-01`) vence em **200 dias**; a regra só permite alerta até 30 dias. | O código barra a escrita; o agente explica. Nenhuma linha em `alertas_agente`. |
| **Fora do escopo** (`05_extra_rn28`, extra) | Pedido para zerar estoque. | Recusar (RN28) sem usar a ferramenta de escrita. |

## Armadilhas nos dados (o que impede o teste de ser fácil demais)

- **Janela de vendas de 30 dias:** as vendas 13 (45 dias atrás) e 14 (60 dias atrás) ficam fora da janela.
  O Leite vendeu 60 un. nos últimos 30 dias, mas 110 no total; o Sabão em Pó vendeu 0 nos últimos 30 dias, mas 5 no total.
  Uma consulta que ignore o período dá o ranking errado.
- **Lote já vencido com saldo:** `L-PRE-01` (Presunto) venceu há 1 dia e ainda tem 1,0 kg.
- **Produto com dois lotes:** Pão de Forma tem `L-PAO-01` (2 dias) e `L-PAO-02` (20 dias). O alerta é por lote.
- **Janela pedida × janela permitida:** "em até 3 dias" traz 3 lotes; Queijo (6 dias), Banana (4) e Tomate (5) ficam de fora.
- **Isolamento de loja:** a loja 2 tem "Leite Integral 1L" com 500 unidades. O agente da loja 1 nunca pode citar esse número.

## Gabarito do caso 01 (verificador)

Alertas esperados no banco depois da execução: `(Iogurte Natural 170g, L-IOG-01)`, `(Pão de Forma 500g, L-PAO-01)`,
`(Presunto Fatiado, L-PRE-01)`. Nem mais, nem menos (`dados/casos.json`).
