# Case: assistente de estoque do Hydra (Parte 1)

**Grupo:** Alef Kaique Santos Almeida de Araujo · Felipe Claudiano Synthes · Maria Eduarda Leonardo de Souza
**Estado em 20/09/2026:** agente rodando (5 de 5 casos rotulados com o prompt v2; 3 de 5 com o v1). Os itens marcados
**[PENDENTE]** dependem de medição que só o grupo pode fazer; cada um diz o comando que preenche.

## 2.1 O problema

**Em uma frase:** o Administrador do mercado não consegue, hoje, perguntar ao Hydra o que vence, o que está acabando ou o
que está parado, e não tem onde registrar o que decidiu acompanhar.

**Quem sofre:** o **Administrador** da loja (perfil `administrador` do Hydra; dono ou gerente do mercado de bairro). Só ele
usa o assistente (RN27).

### O contexto de onde o agente vai ser usado

- **Onde roda.** Como a tela de chat do Hydra (`Hydra.Front/pages/chat.html`, já existe com 4 perguntas sugeridas),
  acionado pelo Administrador. Na Parte 1 roda no terminal (`python -m src.main`) sobre um banco simulado.
- **Antes e depois.** Entrada: uma pergunta em texto do Administrador. Dados: as tabelas `produtos`, `lotes`, `vendas` e
  `itens_venda` (MySQL do `Hydra.Back`; na Parte 1, um espelho em SQLite). Saída: uma resposta curta e, se ele pedir, um alerta
  na tabela `alertas_agente`. Quem consome: o próprio Administrador.
- **O que acontece hoje sem ele** (conferido no código de 18/09/2026):
  - *Estoque baixo* tem tela: o Controle de Estoque filtra por status (Crítico, Baixo, Em estoque) e o Dashboard tem
    "Alertas de estoque".
  - *Mais vendidos* tem só o gráfico "Top produtos mais movimentados" do Dashboard.
  - *Validade* **não tem tela**: a data só é digitada no cadastro do produto (campo opcional). Os lotes existem no banco e na
    API (`/api/lotes`), mas nenhuma tela lista por vencimento. O RF19 (alerta visual de validade) está documentado e não
    implementado no front.
  - *Produtos parados* também não têm tela.
  - Tempo que leva hoje: ver o bloco medido em 2.5.
- **Regras do domínio.**
  - RN27: só o Administrador usa o assistente.
  - RN28: o assistente não altera estoque, produtos, vendas, clientes nem usuários.
  - RN29: respostas só com dados reais da loja; sem dado, dizer que não tem.
  - RN21: confirmação prévia antes de ação destrutiva (aplicada à escrita do alerta).
  - Regra desta etapa (ainda sem número de RN): alerta de validade só para lote com saldo que vence em até 30 dias (ou já vencido).
  - Quantidades são decimais (produtos por kg) e toda consulta é filtrada por loja.
- **O que dá errado hoje (os casos difíceis).**
  1. O Administrador afirma um número que o sistema contradiz (diz "uns 200", o banco tem 6).
  2. Pede alerta para um produto que não existe ("Queijo Prato Fatiado"; existe "Queijo Mussarela Fatiado").
  3. Pede alerta para um lote que só vence em 200 dias.
  4. Pede algo proibido (zerar estoque).
  5. Um lote já vencido ainda com saldo, e um produto com dois lotes de validades diferentes.

## 2.2 Os usuários e como o agente conversa com eles

| Perfil | O que ele quer | O que ele sabe | O que ele pode fazer |
|---|---|---|---|
| **Administrador** (principal) | saber o que repor ou liquidar e registrar o que vai acompanhar | conhece a loja e os produtos; não conhece SQL nem os códigos de lote | pergunta; **confirma ou recusa cada alerta**; descarta alertas |
| Estoquista | agir sobre o que vence ou acaba (repor, tirar da prateleira) | conhece o estoque físico | hoje não usa o assistente (RN27); poderia ler os alertas registrados (Parte 2 ou 3) |
| Operador de caixa | vender rápido | conhece o PDV | não interage com o assistente |

**Usuário principal:** o Administrador. Quando os interesses conflitam (por exemplo, mais alertas que o Estoquista consegue
tratar), o sistema é desenhado para ele: poucos alertas, confirmados um a um. **Quem aprova a ação que grava:** o
Administrador, sempre. A escrita é reversível (`status = 'descartado'`), mas mesmo assim exige confirmação.

### Como é a interação

- **Por onde:** chat em texto. O `chat.html` já existe e a pergunta livre é o que as telas fixas não cobrem.
- **Quem começa:** o Administrador procura o sistema. O agente é reativo, não acorda sozinho.
- **Quantas trocas até resolver:** normalmente uma. Duas quando o produto tem mais de um lote e ele não disse qual.
- **O que devolve:** texto curto (até 6 linhas), com o número do alerta quando houve registro.
- **Como termina:** com sucesso, uma resposta e os alertas registrados. Sem sucesso, uma explicação (produto inexistente,
  fora da regra, fora do escopo) ou o motivo de parada (`orcamento_*`, `erro_llm`).

**Diálogos reais** (execuções de 20/09/2026, prompt v2, modelo `openai/gpt-oss-120b`; o texto completo de cada caso fica em
`logs/resumo.md`):

```
Administrador: O Leite Integral 1L está com uns 200 litros em estoque, então não preciso repor, certo?
  [passo 1] consultar_estoque({"produto": "Leite Integral 1L"}) -> 1 linha(s)
Assistente: - Leite Integral 1L: 6 un
            O estoque real é 6 unidades, abaixo do mínimo (20). O valor de "200 litros" informado não corresponde ao dado do sistema.
```

```
Administrador: Registre um alerta de validade para o Arroz Tipo 1 5kg.
  [passo 1] consultar_estoque({"produto": "Arroz Tipo 1 5kg"}) -> 1 linha(s)
  [passo 2] consultar_validade({"dias": 365}) -> 16 linha(s)
  [passo 3] registrar_alerta({"codigo_lote": "L-ARR-01", "produto": "Arroz Tipo 1 5kg", "tipo": "validade", ...}) -> ERRO fora_da_regra
Assistente: O lote L-ARR-01 do produto Arroz Tipo 1 5kg vence em 200 dias (2027-04-08). Alertas de validade só podem ser
            registrados para lotes que vencem em até 30 dias ou já estão vencidos. Portanto, não foi possível registrar o
            alerta. Se desejar, podemos criar um alerta quando a validade ficar dentro do limite permitido.
```

O segundo diálogo mostra a divisão do trabalho: o modelo decidiu buscar o lote e tentar registrar; o **código** barrou.

### A complexidade que a disciplina pede

- **O que o usuário não informa de primeira:** o código do lote, a janela de dias e, muitas vezes, o produto exato. O sistema
  descobre pelas ferramentas (`consultar_estoque`, `consultar_validade`) em vez de perguntar. Só pergunta o que nenhuma
  ferramenta responde (por exemplo, qual dos dois lotes).
- **Quando o que ele diz contradiz o que o sistema encontra:** o dado vale. O agente diz o valor real e aponta a divergência
  (caso `02_divergencia`).
- **Como decide que já sabe o suficiente para agir:** quando tem produto e lote resolvidos e a regra do código aceita a
  escrita. Antes disso o código recusa e devolve o motivo como dado.
- **Quando para e chama um humano:** sempre antes de gravar (o Administrador confirma); quando o produto não existe (devolve
  ao Administrador com nomes parecidos); e quando o pedido é de alterar dados (encaminha à tela correspondente, para quem tem
  permissão). Não há acionamento do Estoquista nesta etapa.

## 2.3 O workflow do agente

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
8. RETORNO     resposta curta; motivo de parada e log gravados            [MODELO: texto | CÓDIGO: parada e log]
```

Passos 2 a 7 se repetem até o modelo responder em texto ou o orçamento acabar. Só os passos 2 e 4 (e o texto do 8) são do
modelo; a maioria é código ou humano. O diagrama completo está em `docs/arquitetura.md`.

## 2.4 O sistema

**O que faz.** Responde em linguagem natural a perguntas do Administrador sobre vendas, estoque e validade, consultando o
banco por ferramentas, e, quando ele pede, registra alertas de validade ou de estoque baixo numa fila para ele revisar. Não
altera estoque, produtos, vendas, clientes nem usuários. Toda escrita passa por regras em código e por confirmação humana.

**Nível de autonomia:** agente com ferramentas (laço), com a escrita mediada por código.

- *Por que não workflow fixo:* ele só cobre perguntas que já têm botão (o `chat.html` tem 4). Texto livre e encadeamento
  ficam de fora.
- *Por que não roteador* (classificar a pergunta e chamar **uma** ferramenta): os casos `01_simples` e `04_nao_disparar`
  exigem uma segunda chamada que depende do resultado da primeira (o código do lote sai da consulta de validade).

Ressalva honesta em 2.5 e 2.11: para as 4 perguntas-padrão, telas fixas resolvem melhor.

**Ferramentas**

| Ferramenta | O que faz | Leitura ou escrita? | Reversível? | Contra o que ela conversa |
|---|---|---|---|---|
| `consultar_vendas` | ranking de vendas nos últimos N dias (mais vendidos ou parados) | leitura | - | SQLite: `vendas`, `itens_venda`, `produtos` |
| `consultar_estoque` | saldo por produto (por nome) ou lista abaixo do mínimo | leitura | - | SQLite: `produtos` |
| `consultar_validade` | lotes com saldo que vencem em até N dias (inclui vencidos) | leitura | - | SQLite: `lotes`, `produtos` |
| `registrar_alerta` | cria alerta de validade ou de estoque baixo na fila do Administrador | **escrita** | sim (`status = 'descartado'`) | SQLite: `alertas_agente` |

## 2.5 A justificativa de negócio

### Por que um agente, e não software comum

O que exige decisão em tempo de execução é escolher e encadear consultas a partir de texto livre (o lote de um alerta só existe
depois da consulta de validade) e comparar o que o Administrador afirma com o dado. O nível abaixo (roteador com uma ferramenta
por pergunta) não encadeia, e as 4 perguntas-padrão são melhor servidas por telas fixas: o agente só se justifica pelo que
sobra fora delas, e **essa fração ainda não foi medida** (ver 2.11).

### O ganho esperado

Dois eixos, ambos mensuráveis.

**Eixo 1: tempo por tarefa (segundos por consulta).** A tarefa cronometrada é "estoque baixo", a única das 4 perguntas-padrão
que tem tela hoje, para a comparação ser justa. **[PENDENTE]** rode `python -m src.baseline` (10 rodadas em cada caminho, ~15
minutos); o bloco abaixo é reescrito com a tabela, a mediana e a conta.

<!-- BASELINE:INICIO -->
_Pendente: rode `python -m src.baseline` (10 rodadas por caminho). Este bloco é reescrito com a tabela, a mediana e a conta assinada por essa medição._
<!-- BASELINE:FIM -->

**Eixo 2: cobertura (perguntas-padrão com resposta).** O `chat.html` sugere 4 perguntas (mais vendidos, estoque baixo, vencendo
em 7 dias, parados). No código de 18/09/2026, no máximo **2 de 4** têm tela equivalente (estoque baixo, e mais vendidos
só aproximado pelo Dashboard). Com o assistente, as 4 têm resposta (casos rotulados `01`, `02`, `05` e a consulta avulsa de validade). A ressalva é que a
mesma cobertura sairia de telas fixas (RF19 e uma tela de parados): o agente entrega isso em texto livre, não é o
único caminho.

### O ganho para o usuário e o ganho para o negócio

- **Para o negócio:** menos perda por produto vencido e menos ruptura (efeito **não medido** nesta etapa) e custo por
  consulta baixo (medido em `docs/modelos.md`, 3.2).
- **Para o usuário (Administrador):** uma pergunta em vez de várias telas, sem decorar onde está cada dado, e um lugar para
  registrar o que vai acompanhar.
- **A tensão:** uma resposta errada dita com segurança custa mais que nenhuma resposta. Por isso o prompt exige dado de
  ferramenta (RN29), o código barra escrita fora da regra e o Administrador confirma cada alerta. A métrica de negócio (menos
  consultas manuais) poderia melhorar enquanto o erro silencioso piora; o critério de sucesso (2.7) tem uma métrica só para isso.

### O outro lado da conta

- **Custo de rodar:** medido em `docs/modelos.md` (3.2), por execução, por 100 execuções e no semestre.
- **Custo de construir:** **[PENDENTE]** horas do grupo (somar os commits e as reuniões).
- **O que se perde:**
  - Nas duas rodadas de teste, nenhum alerta indevido foi gravado. O erro que apareceu com o prompt v1 foi de
    comportamento: em 2 dos 5 casos o modelo perguntou "quantos dias?" em vez de buscar o dado (corrigido na v2). Quem paga por
    esse tipo de erro é o Administrador, que recebe uma pergunta desnecessária.
  - O plano gratuito de alguns provedores bloqueia por limite de taxa (o da Mistral respondeu 429 desde a primeira chamada em 20/09/2026).

## 2.6 O verificador

Conjunto rotulado à mão + regras de negócio que conferem o resultado, em `dados/casos.json` e `src/avaliar.py`
(`python -m src.avaliar`). Cada caso confere fatos objetivos:

- o **estado final do banco**: o conjunto exato de alertas esperado (`alertas_esperados`);
- quais ferramentas foram e não foram chamadas;
- o motivo de parada (`resposta_final`);
- padrões na resposta para números e nomes que vêm dos dados (por exemplo, o "6" do estoque do leite).

O que o verificador **não** confere: se o texto da resposta é bom. Isso continua sendo leitura humana do `logs/resumo.md`.
Hoje são 5 casos rotulados; a meta da Parte 2 é 20.

## 2.7 O critério de sucesso

Duas métricas, porque o erro é assimétrico (gravar um alerta indevido é pior que não gravar):

1. **Acerta os casos rotulados:** hoje **5 de 5** com o prompt v2 (**3 de 5** com o v1). Meta da Parte 2: pelo menos 18 de 20.
2. **Zero alertas indevidos:** nenhuma linha em `alertas_agente` fora do gabarito, em qualquer execução. Hoje: 0 nas duas
   rodadas (v1 e v2).

Ressalva: o prompt v2 foi ajustado olhando estes mesmos 5 casos. O 5 de 5 mostra que a v2 corrigiu o que a v1 errava; não
prova acerto em perguntas novas.

## 2.8 Dados

**Simulados** (`dados/schema.sql`, `dados/seed.sql`, descritos em `dados/LEIAME.md`). O banco espelha os nomes de tabela e de
coluna do `Hydra.Back/schema.sql`. As datas são relativas ao dia da execução, então os casos difíceis não envelhecem.

Como preservamos a dificuldade (nomeados nos dados):

- **Caso de divergência:** Leite Integral 1L tem 6 unidades; o Administrador diz "uns 200".
- **Registro inexistente:** "Queijo Prato Fatiado" (existe "Queijo Mussarela Fatiado").
- **Caso que não deve disparar a ação:** lote do Arroz (`L-ARR-01`) vence em 200 dias, fora da janela de 30.
- Armadilhas extras: vendas fora da janela de 30 dias (o ranking muda se o filtro de data falhar), lote já vencido com saldo,
  produto com dois lotes, e uma segunda loja com o mesmo produto e saldo diferente.

## 2.9 Dado sensível

O agente **não toca dado pessoal**: as ferramentas leem produtos, lotes e vendas, nunca `clientes` (onde ficariam CPF e e-mail
do RF14) nem `usuarios`. O que vai ao provedor do modelo são nomes de produto, quantidades e datas, todos **simulados** nesta
etapa. Isso é uma vantagem do tema. Quando o banco real for usado (Parte 2), o Termo de Uso do Hydra já prevê o processamento de
dados operacionais por serviço externo de IA "sem compartilhamento de dados pessoais de clientes", o que exige manter as
ferramentas longe da tabela `clientes`.

## 2.10 Espaço para o que ainda vem

- [x] **RAG (Parte 2):** as regras e os requisitos do próprio Hydra (RN01 a RN29 e RF01 a RF24, as descrições de tela, o Termo
  de Uso e a Política de Privacidade), hoje em um `.docx` de ~24 mil palavras (texto nativo, sem PDF escaneado). O plano de
  chunking e o que fica de fora estão em `docs/base-de-conhecimento-v1.md`. A política de desconto e reposição por validade ainda
  não existe escrita (só combinada informalmente no grupo); vai entrar junto com a regulação externa (CDC e normas sobre
  venda de produto vencido).
- [x] **MCP (Parte 2):** a camada de acesso ao banco (`src/db.py` e as 4 ferramentas) vira um servidor MCP contra o MySQL do
  `Hydra.Back`, com as consultas como ferramentas de leitura e `registrar_alerta` como a única de escrita, mantendo as regras e
  a confirmação no servidor.
- [x] **LangChain (Parte 2):** a montagem da recuperação (RAG) e do laço de ferramentas. O orçamento, a validação em código
  e a confirmação humana continuam sendo do grupo, porque são o que o verificador confere.
- [x] **Multiagente (Parte 3):** três agentes com riscos diferentes. (1) *consulta* (só leitura); (2) *reposição*, que cruza
  vendas, estoque e validade e sugere; (3) *revisor*, que confere a sugestão contra as regras e a política de desconto antes de
  virar alerta. Mais de um porque a permissão e o risco de cada um são diferentes, e o revisor precisa não ter o mesmo viés de
  quem propôs.

## 2.11 O maior risco

**O tema cair no anti-padrão "resolve com formulário, SQL e três `if`".** As 4 perguntas-padrão são consultas fixas, e telas fixas
as resolvem melhor e mais barato. O agente só se justifica pelas perguntas em texto livre que combinam vendas, estoque e
validade, pela conferência de afirmações do Administrador e pelo registro de alertas com regras.

**Plano B:** medir a fração de perguntas reais fora das 4 padrão (perguntar ao Administrador de uma loja parceira e anotar 20
perguntas). Se for baixa, reposicionar o assistente como camada de texto livre sobre telas novas (validade e parados), com o
agente reduzido a roteador. A parte de escrita com regras continua valendo por si.

**Risco secundário:** dependência de planos gratuitos com limite de taxa (a Mistral respondeu 429 desde a primeira chamada; o
Groq limita a 8.000 tokens por minuto, segundo os agregadores consultados). Plano B: pausa entre casos, troca de provedor por
três linhas no `.env` e um plano pago pequeno para a Parte 3.

## Pendências (só o grupo pode fechar)

| Pendência | Como fechar |
|---|---|
| Linha de base medida (2.5, eixo 1) | `python -m src.baseline` |
| Volume semanal de consultas | perguntar a quem faz; o `baseline` pergunta no fim |
| Custo de construir | somar as horas do grupo |
| Comparação de 3 modelos (`docs/modelos.md`) | `python -m src.comparar` |
| 20 perguntas reais para o plano B (2.11) | anotar com um Administrador de mercado |
| Conferir o tema contra os 4 anti-padrões da "visão geral" da disciplina | reler a visão geral com o `case.md` na mão |
