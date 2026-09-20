# Arquitetura básica — Parte 1

## Diagrama

```
  Administrador (terminal)
          |  pergunta em texto livre
          v
  src/main.py        lê .env, abre o SQLite, escolhe como confirmar as escritas
          |
          v
  src/agente.py  (laço com Estado + Orçamento)
  +-> [orçamento estourou?] --sim--> PARA: orcamento_passos | orcamento_tokens | orcamento_custo
  |        | não
  |        v
  |   MODELO  (prompts/sistema_v2.md + schemas das 4 ferramentas)
  |        |-- texto final ---------------> PARA: resposta_final
  |        |-- erro do provedor ----------> PARA: erro_llm
  |        `-- pede ferramenta(s)
  |                 v
  |   CÓDIGO: despachar cada chamada
  |        leitura ----------------------------> SQLite (SELECT ... ?)
  |        escrita: 1. VALIDAR regras ---violou---> erro devolvido ao modelo
  |                 2. CONFIRMAR (humano) --recusou--> erro devolvido ao modelo
  |                 3. ESCREVER ---------------> tabela alertas_agente
  |                 |
  +-----------------'  resultado (ou erro, como dado) volta ao MODELO
          |
          v
  logs/<execução>.jsonl   eventos: inicio, passo, ferramenta, fim
```

## Workflow (quem decide em cada passo)

```
1. ENTRADA     o Administrador digita a pergunta no terminal              [decide: HUMANO]
2. PLANEJAR    escolhe quais consultas fazer, com que parâmetros          [decide: MODELO]
3. CONSULTAR   executa SQL parametrizado no SQLite (leitura)              [decide: CÓDIGO]
4. ANALISAR    compara o que o Administrador disse com os dados;
               decide se há alerta a registrar (só se ele pediu)          [decide: MODELO]
5. VALIDAR     produto existe? lote/estoque dentro da regra? já há
               alerta aberto igual?                                       [decide: CÓDIGO]
6. CONFIRMAR   o Administrador aprova cada escrita                        [decide: HUMANO]
7. REGISTRAR   INSERT em alertas_agente                                   [ESCRITA reversível]
8. RETORNAR    resposta curta; motivo de parada e log gravados            [MODELO: texto | CÓDIGO: parada e log]
```

Os passos 2 a 7 repetem até o modelo responder em texto ou o orçamento acabar. A maioria dos passos é código ou humano:
só o 2 e o 4 (e o texto do 8) são decisão do modelo.

## Ferramentas

| Ferramenta | O que faz | Leitura ou escrita? | Reversível? | Contra o que conversa |
|---|---|---|---|---|
| `consultar_vendas` | ranking de vendas nos últimos N dias (mais vendidos ou parados) | leitura | — | SQLite: `vendas`, `itens_venda`, `produtos` |
| `consultar_estoque` | saldo por produto (por nome) ou lista abaixo do mínimo | leitura | — | SQLite: `produtos` |
| `consultar_validade` | lotes com saldo que vencem em até N dias (inclui vencidos) | leitura | — | SQLite: `lotes`, `produtos` |
| `registrar_alerta` | cria alerta de validade ou de estoque baixo na fila do Administrador | **escrita** | sim (`status = 'descartado'`) | SQLite: `alertas_agente` |

O banco simulado espelha as tabelas do `Hydra.Back/schema.sql` (MySQL) com os mesmos nomes. Na Parte 2 esta camada vira um
servidor MCP.

## Onde está a decisão que justifica um agente

Nos passos 2 e 4. O modelo escolhe em tempo de execução quais consultas fazer e em que ordem, e o que fazer com o resultado:
no caso 01 a segunda chamada (um alerta por lote) só pode ser montada com os códigos de lote que vieram da primeira; no caso 02
ele precisa comparar a afirmação do Administrador com o dado; no caso 03 ele precisa reagir a um erro de ferramenta sem trocar
de produto por conta própria. O nível de baixo (roteador: classificar a pergunta e chamar **uma** ferramenta fixa) não cobre os
casos 01 e 03, que dependem do resultado de uma chamada para montar a seguinte.

**Ressalva honesta:** as perguntas simples ("o que vence esta semana?") um roteador ou até um botão do dashboard resolve.
O que decide se o laço vale o custo é a fração das perguntas reais que precisam de encadeamento. Essa medição pertence à
justificativa de negócio (`docs/case.md`, §2.5) e ainda não foi feita.

## O que é regra do código e o que é escolha do modelo

| Garantia | Onde vive | Depende do modelo? |
|---|---|---|
| SQL só com parâmetros `?`; `ordem` vem de um enum validado | `ferramentas.py` | não |
| Consulta sempre filtrada por `id_loja` | `ferramentas.py` | não |
| Alerta de validade só para lote com saldo que vence em até 30 dias (ou já vencido) | `_preparar_alerta` | não |
| Alerta de estoque só se saldo ≤ mínimo; sem duplicata aberta | `_preparar_alerta` | não |
| Confirmação humana antes de toda escrita | `_executar` em `agente.py` | não |
| Teto de passos, tokens e custo; motivo de parada registrado | `executar` em `agente.py` | não |
| Erro de ferramenta vira dado com `dica` | `erro()` e `_executar` | não |
| Não inventar número; contradizer o usuário com o dado; recusar alterar estoque | `prompts/sistema_v2.md` | **sim** (medido pelos casos 02, 03 e 05) |

Consequência: mesmo que o modelo tente registrar um alerta indevido, o código barra (caso 04). O que só o prompt garante é
verificado pela demonstração, não assumido.

## Prompt: o que cada regra impede

Regra de ouro da disciplina: se apagar uma frase e não souber dizer o que ela impedia, ela não estava fazendo nada.
A v1 (`sistema_v1.md`, 3 de 5 casos) virou a v2 (5 de 5) mudando as regras 5, 6 e 7; o motivo está no cabeçalho do arquivo.

| Regra em `prompts/sistema_v2.md` | O que impede |
|---|---|
| 1. Só nomes e números vindos das ferramentas | número inventado (RN29) |
| 2. Conferir antes de concordar; o dado vale | concordar com afirmação errada do Administrador (caso 02) |
| 3. Não alterar estoque, produtos, vendas, clientes, usuários | pedido fora do escopo virar ação (RN28, caso 05) |
| 4. `registrar_alerta` só se pedido; copiar nome e lote como vieram | alerta por iniciativa própria; lote inventado |
| 5. Achar produto (`consultar_estoque`) e lote (`consultar_validade`, `dias=365` se a janela não foi dita) antes de registrar | código de lote adivinhado; pergunta desnecessária de "quantos dias?" (o erro da v1 nos casos 03 e 04) |
| 6. Erro: corrigir no máximo uma vez; produto inexistente não se troca; recusa por `fora_da_regra` se explica e não se insiste | laço de tentativas; troca silenciosa de produto (caso 03); insistir contra a regra do código (caso 04) |
| 7. Só perguntar o que nenhuma ferramenta responde | perguntas que o próprio agente resolve consultando |
| Formato: até 6 linhas, sem tabelas | resposta longa demais para o terminal |

## Orçamento e terminação

Checado antes de cada chamada ao modelo (uma chamada pode passar do teto pelo tamanho dela). Padrões no `.env.example`:
8 passos, 20.000 tokens, US$ 0,05 (o teto de custo só vale se os preços do modelo estiverem no `.env`).

| `terminacao` | Significa |
|---|---|
| `resposta_final` | o modelo respondeu em texto |
| `resposta_vazia` | o modelo respondeu sem texto |
| `orcamento_passos` / `orcamento_tokens` / `orcamento_custo` | um teto foi atingido; sem resposta, e as escritas já feitas ficam registradas |
| `erro_llm` | o provedor falhou (chave, rede, modelo inexistente, limite de taxa) |

## Relação com o `Hydra.Agent` (chat do Hydra)

`Hydra.Agent/app.py` continua sendo o chat somente leitura da tela do Hydra (RN28) e **não foi alterado**. O agente desta
entrega é a versão de linha de comando com SQLite, e é o único com a ferramenta de escrita. O RN28 diz que o Assistente IA
"não pode criar, editar, excluir ou alterar registros de estoque, produtos, vendas, clientes ou usuários": a fila
`alertas_agente` não é nenhum desses, mas se a escrita for para o produto, vale acrescentar uma ressalva ao RN28 e uma
linha ao histórico de alterações da documentação.
