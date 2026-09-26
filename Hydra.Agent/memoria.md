# Memória do assistente de estoque do Hydra

**Exercício 8, rascunho de `docs/memoria.md` (Parte 2, §4)**
**Grupo:** Alef Kaique Santos Almeida de Araujo · Felipe Claudiano Synthes · Maria Eduarda Leonardo de Souza
**Estado em 25/09/2026:** decisão de projeto, sem código novo. Os itens **[PENDENTE]** dependem das medições do
`08-complementar.md`, e cada um diz o que falta medir.

**Escopo.** Este documento vale para o agente do case, o laço de `src/agente.py` com o prompt `prompts/sistema_v2.md`. Esse
agente vai substituir o chat somente leitura de `Hydra.Agent/app.py`. **Ponto de partida:** hoje nenhum dos dois lembra de nada.
O `src/main.py` guarda o histórico numa lista em memória, que some quando o terminal fecha. O `Hydra.Agent` recebe o histórico
do navegador (`let historico = []` em `chat.js`), e ele some quando a página recarrega. O agente só deixa rastro nos logs
`logs/*.jsonl` e na tabela `alertas_agente`. As duas estruturas entram na Decisão 2, porque também guardam dado.

> Ordem de leitura sugerida pelo enunciado: a Decisão 2 foi decidida primeiro. A lista de exclusão do §1.4 saiu dela.

---

## Decisão 1: como o agente lembra

### 1.1 Os dois níveis, no domínio do case

| | **Curto prazo** | **Longo prazo** |
|---|---|---|
| **O que é** | a janela de contexto de **uma execução**, ou seja, uma pergunta do Administrador, do evento `inicio` ao `fim` | o que atravessa execuções da **mesma loja** (`id_loja`) |
| **Conteúdo no case** | o prompt `sistema_v2.md` com os 4 schemas; a pergunta; os turnos anteriores do chat; as chamadas de ferramenta com os resultados; os trechos de regra RN/RF recuperados (RAG, Parte 2) | **episódica**: o que aconteceu em execuções passadas. **Semântica**: fatos da loja que o banco não tem. **Procedural**: as regras do prompt versionado |
| **Persistido como** | checkpoint: um arquivo JSON por execução, `checkpoints/<id_execucao>.json`, gravado a cada passo | episódica: tabela `memoria_episodica` + matriz `.npz` de embeddings. Semântica: tabela `memoria_semantica`. Procedural: `prompts/sistema_vN.md` |
| **Lido** | uma vez, na retomada | a cada volta do laço: a semântica inteira da loja (é pequena) e a episódica pelos 3 mais parecidos com a pergunta |
| **Acesso** | por `id_execucao` | episódica por similaridade; semântica por chave; procedural sempre inteira |
| **Ciclo de vida** | morre com a execução. O arquivo é apagado 7 dias depois do `fim`, e a execução que parou em `pendente_confirmacao` fica guardada até ser resolvida | acumula, com decaimento (§2.2) e remoção (§2.3) |

**O que vai exatamente para o checkpoint.** O `Estado` de `agente.py` mais o que falta nele para retomar:

| Campo | Para que serve |
|---|---|
| `id_execucao`, `id_loja`, `id_usuario` do Administrador | chave da retomada; filtro de loja; quem pode aprovar |
| `mensagens`: a lista exata enviada ao modelo, com cada resultado de ferramenta **como foi devolvido** | reproduzir: o banco muda a cada venda, e consultar de novo daria outra resposta |
| `data_referencia`: o `date('now')` usado nas consultas | `consultar_validade` e `_preparar_alerta` calculam dias a partir de hoje, e sem a data o lote "vence em 2 dias" vira "vencido" na reprodução |
| `passo`, `tokens_entrada`, `tokens_saida`, `custo_usd` | a retomada continua o orçamento, sem zerá-lo |
| `chamadas[]`, cada uma com `chave_idempotencia = id_execucao:passo:indice` e `status` (`proposta`, `validada`, `aguardando_confirmacao`, `executada`, `recusada`) | **não reaplicar efeito colateral**: uma `registrar_alerta` que está `executada` não roda de novo. O `INSERT` grava a chave numa coluna `UNIQUE` de `alertas_agente`, então uma queda entre o `INSERT` e o checkpoint também não gera alerta duplicado |
| `escritas[]` (ids de alerta) | dizer o que foi registrado |
| `pendente`: `{chave_idempotencia, descricao, argumentos, pedido_em}` | **aprovação horas depois, vinda de outro processo**: a tela do Hydra lê o pendente pelo `id_execucao`, e o aprovador grava `{aprovado, por, em}`. O laço recarrega o checkpoint, **valida a regra de novo** (em 4 horas o lote pode ter sido vendido) e só então escreve |
| `carimbo`: arquivo, versão e sha do prompt, modelo, `temperature`, orçamento, **hash da memória de longo prazo lida** | **depurar um estado defeituoso**: carregar o arquivo e rodar o próximo passo com a mesma entrada. O hash da memória mostra se o que o agente lembrava mudou desde então |

O checkpoint **não guarda** a chave da API, a string de conexão nem o `.env`. Esses dados vêm do ambiente na retomada.

### 1.2 O orçamento da janela

Medido nos logs de 20/09/2026 (`gpt-oss-120b`, prompt v2), por chamada ao modelo. Os logs registram o valor acumulado, e a
diferença entre dois passos dá o valor de cada chamada:

- o prompt com os 4 schemas e uma pergunta curta ocupa **1.027 a 1.040 tokens** (primeiro passo dos 5 casos);
- a maior chamada foi de **2.388 tokens** (caso 04, passo 4). A consulta de validade de 365 dias, com 16 linhas, custou
  **~1.100 tokens** sozinha.

Hoje o código só limita o **acumulado** por execução (`MAX_TOKENS=20000`), e nada limita a chamada. Com memória e RAG, a janela
passa a ter cinco fontes, e o teto por chamada fica assim:

| Fonte | Teto (tokens) | Justificativa | Ordem de descarte |
|---|---|---|---|
| System prompt com os schemas (procedural) | 1.200 | medido ~1.000, com folga para mais uma regra | **nunca**: sem ele o agente perde as regras RN28 e RN29 |
| Objetivo (a pergunta atual) | 300 | as perguntas dos casos têm 20 a 40 tokens | **nunca**. Acima de 300, o código recusa e pede uma pergunta mais curta, sem truncar calado |
| Memória de longo prazo | 600 | semântica ≤ 200 (até 10 fatos de ~20 tokens); episódica ≤ 400 (até 3 episódios de ~130) | **1º**: episódios de menor similaridade. **5º**: a semântica, e só se nada mais couber |
| Trechos recuperados (RAG, Parte 2) | 1.500 | 3 chunks de até 1.500 caracteres (~400 tokens), como define `base-de-conhecimento-v1.md` | **3º**: o chunk de menor score |
| Trajetória (turnos anteriores do chat + chamadas e resultados desta execução) | 2.400 | o pico medido na execução foi de ~1.400 | **2º**: turnos anteriores do chat, dos mais antigos para os mais novos. **4º**: resultados de ferramenta antigos **desta** execução, trocados por um resumo feito em código (`consultar_validade(dias=365) -> 16 linhas; lotes: L-ARR-01, ...`) |
| **Total por chamada** | **6.000** | cerca de 2,5 vezes o pico medido. A janela de 131 mil do modelo não é o limite que importa: o que pesa é o custo e a atenção do modelo | se, depois do 5º, ainda estourar: para com a terminação nova `orcamento_janela` |

**Regra que não se negocia:** o **último** resultado de ferramenta nunca é cortado nem resumido. O corte é feito no meio da
trajetória, e nunca no fim. Truncar no fim é o comportamento padrão de quem não decide, e é justamente ali que está o código de
lote que o modelo vai copiar na próxima chamada (regra 4 do prompt).

**[PENDENTE, 08-complementar]** medir o tamanho real de um episódio e de um fato semântico gravados, e reajustar os 600.

### 1.3 O longo prazo: as três memórias no case

| Tipo | O que guarda no case | Estrutura | Como é recuperada |
|---|---|---|---|
| **Episódica** | uma linha por execução encerrada: data, `id_loja`, a pergunta, as ferramentas chamadas (nome e argumentos), os erros (`produto_nao_encontrado`, `fora_da_regra`, `nao_confirmado`), os alertas gravados e a terminação. Exemplo: *"20/09: pediu alerta de validade do Arroz Tipo 1 5kg; L-ARR-01 recusado por fora_da_regra (200 dias)"* | tabela `memoria_episodica` com embedding da pergunta numa matriz numpy `.npz` (a mesma escolha do RAG: com poucos milhares de linhas, a matriz supera um banco vetorial) | por **similaridade** com a pergunta atual, filtrada por `id_loja`, com os 3 primeiros acima de um limiar. Serve para "você já me disse isso ontem", para não repetir a busca que falhou e para lembrar que um alerta já foi recusado |
| **Semântica** | fatos da loja que **o banco não tem** e o Administrador **confirmou**: apelidos (`apelido:"o queijo"` → `Queijo Mussarela Fatiado`), janela preferida (`preferencia:janela_validade` = 7), prazo do fornecedor (`fornecedor:laticinios:prazo_dias` = 5), produto que ele decidiu descontinuar | tabela chave-valor `memoria_semantica(id_loja, chave, valor, valido_desde, fonte, confirmado_por)`. **Não há chave única**: cada mudança é uma nova linha (§2.1) | **por chave**: todos os fatos vigentes da loja entram na janela (são poucos). Se passarem de 10, entram só as chaves citadas na pergunta, por casamento de nome em código |
| **Procedural** | como o agente deve agir, aprendido com o erro. A v1 perguntava "quantos dias?" nos casos 03 e 04, e a v2 ganhou as regras 5 e 7 | texto em `prompts/sistema_vN.md`, com versão e sha no evento `inicio` do log | sempre inteira, como system prompt. Nunca por similaridade: uma regra que só às vezes entra na janela não é uma regra |

**Por que cada estrutura.** O apelido "o queijo" é uma pergunta com resposta exata. Buscá-lo por similaridade traria também
"Queijo Prato", que é justamente o caso 03. A episódica é o contrário: ninguém pergunta "o episódio 184", e sim algo *parecido*
com o que já aconteceu.

### 1.4 Quem escreve, e o que não entra

| Memória | Quem escreve | Volume por execução |
|---|---|---|
| Episódica | **o código, por regra**, no evento `fim`. Nada é escrito se a terminação for `erro_llm` ou `orcamento_*`, porque uma execução interrompida não é um fato | 0 ou 1 registro, texto ≤ 500 caracteres + 1 vetor de 1.536 dimensões (~6 KB) |
| Semântica | **o agente propõe e o humano confirma**: uma ferramenta `lembrar_fato(chave, valor)`. O código valida a chave numa lista fechada (`apelido:*`, `preferencia:*`, `fornecedor:*:prazo_dias`, `produto:*:descontinuado`), e o Administrador confirma como confirma um alerta | 0 a 2 registros, valor ≤ 200 caracteres |
| Procedural | **o humano (o grupo)**, lendo os logs e publicando uma nova versão do prompt, que o `src.avaliar` testa antes | 0 por execução |

Com 20 perguntas por dia (**[PENDENTE]** o volume real sai do `src.baseline`), 90 dias de episódica dão ~1.800 linhas, ou seja,
uma matriz de ~11 MB.

**O que o sistema não guarda:**

| Não guarda | Exemplos no case | Por quê |
|---|---|---|
| **Dado sensível** | CPF e e-mail de `clientes`, `senha` e `reset_token` de `usuarios`, a chave `OPENAI_API_KEY`, nome de pessoa citado na pergunta ("o João do caixa esqueceu de dar baixa") | as ferramentas já não leem `clientes` nem `usuarios` (case §2.9), e a memória não pode reabrir essa porta. Um nome de pessoa não é valor aceito em nenhuma chave semântica, e o código recusa. Na episódica ele pode entrar pela pergunta, e por isso a remoção do §2.3 precisa alcançá-la |
| **Conteúdo de fora sem verificação** | "o Leite está com uns 200 litros" (caso 02); a resposta em texto do modelo; um trecho do RAG | a afirmação do Administrador perde para o dado (regra 2). Se entrasse na memória, sairia amanhã como fato. A resposta do modelo também não entra, porque ele pode ter errado. A episódica guarda **o que as ferramentas devolveram e o que o código decidiu**, nunca o que o modelo concluiu |
| **O que é derivável** | saldo, validade e dias para vencer, ranking de vendas, se está abaixo do mínimo, estoque mínimo, custo e tokens da execução | tudo sai do banco ou do log a qualquer momento. Guardar "Leite tem 6 un" cria uma segunda verdade, que fica errada na próxima venda, e aí a memória passa a competir com o banco |

---

## Decisão 2: como o agente esquece

| Causa | O que aconteceu no case | Apaga? | Quando decide |
|---|---|---|---|
| Contradição | o prazo do fornecedor mudou; a regra de alerta mudou | não | na leitura |
| Decaimento | o episódio sobre um lote que já saiu da prateleira | episódica: rebaixa aos 30 dias e **apaga** aos 90 | rotina diária |
| Remoção | o Administrador (ou uma pessoa citada) pede para sair | sim, em todas as estruturas | sob demanda |

### 2.1 Contradição: o fato que mudou

**Dois fatos verdadeiros, em datas diferentes, que respondem à mesma pergunta** ("em quantos dias chega o leite?"):

| id | chave | valor | valido_desde | fonte |
|---|---|---|---|---|
| 12 | `fornecedor:laticinios:prazo_dias` | 3 | 2026-08-10T09:14 | confirmado pelo Administrador |
| 47 | `fornecedor:laticinios:prazo_dias` | 5 | 2026-09-15T17:02 | confirmado pelo Administrador |

Existe um segundo par, já presente no projeto: a regra `LIMITE_DIAS_ALERTA_VALIDADE`, que é 30 hoje e pode mudar. Com ela, um
episódio de 20/09 ("L-ARR-01 recusado, fora da janela de 30 dias") contradiz a regra nova, se ela passar a ser 45. A base de RAG
tem o mesmo problema com as RN que mudaram em 17/09/2026 e com a RN12, que foi removida.

Os dois textos são igualmente parecidos com a pergunta, porque o vetor não representa anterioridade. **A regra de desempate é
determinística e fica no código:**

1. todo fato semântico e todo episódio tem `valido_desde` **obrigatório** (a coluna é `NOT NULL`, e o `INSERT` sem carimbo falha);
2. na leitura, agrupa por `chave` e fica com `max(valido_desde)`. Em empate exato, fica com o maior `id`;
3. um episódio anterior à última mudança da regra que ele cita (o log guarda a versão do prompt e o `limite_dias` em vigor) entra
   na janela com a marca `[regra anterior]`, ou não entra.

Não delegamos o desempate ao modelo. Ele erraria às vezes, custaria uma chamada a mais, e o `src.avaliar` não conseguiria testar.

**O descarte é registrado.** Cada fato preterido gera, na trajetória, o evento
`{"evento": "memoria_descartada", "motivo": "contradicao", "chave": ..., "id_descartado": 12, "id_vigente": 47}`.
Sem esse evento, um agente que ignorou o prazo de 3 dias é indistinguível, no log, de um que nunca o recuperou.

### 2.2 Decaimento: o fato que envelheceu sem ser contradito

| Memória | Corte | Efeito | Justificativa no domínio |
|---|---|---|---|
| Episódica | **30 dias**: rebaixa (score × 0,5). **90 dias**: apaga a linha e o vetor | rebaixa, depois remove | a validade dos perecíveis do seed se conta em dias (pão, iogurte, presunto), e a janela de vendas padrão é de 30 dias. Um episódio sobre um lote costuma perder o assunto em semanas, porque o lote vence, é vendido ou é descartado. 90 dias cobre um trimestre de sazonalidade e nada além disso |
| Semântica | **180 dias** sem nova confirmação | rebaixa: entra na janela com a marca `[não confirmado há 180+ dias]`, e o agente pergunta se continua valendo **antes de agir com base nele**. Não apaga | prazo de fornecedor e apelido mudam devagar e são baratos de reconfirmar. Apagar um apelido sozinho faria o caso 03 voltar |
| Procedural | não decai | só é trocada por uma versão nova do prompt | uma regra não envelhece. Quando ela deixa de valer, é revogada por decisão humana |

**A consequência para a remoção** decidiu o formato. Rebaixar sem apagar deixaria o identificador na episódica para sempre. Com a
remoção aos 90 dias, existe um limite máximo para o tempo em que um nome citado numa pergunta sobrevive, mesmo que ninguém
peça a remoção. Aos logs e checkpoints se aplica a mesma lógica (§2.3).

**[PENDENTE, 08-complementar]** medir quantos episódios de mais de 30 dias ainda são recuperados e aproveitados, e confirmar ou
mover os cortes.

### 2.3 Remoção: o titular solicitou

**Quem é o titular no case.** O Administrador (`id_usuario`, nome e e-mail em `usuarios`) e qualquer pessoa citada por nome
numa pergunta, como um funcionário, um fornecedor pessoa física ou um cliente. Numa loja de MEI, o nome da loja pode ser o nome
do dono.

**Onde o identificador pode ter caído.** São 12 estruturas, e só 3 delas são as memórias:

| # | Estrutura | Como o identificador chega lá | Como sai |
|---|---|---|---|
| 1 | `memoria_episodica` (texto) | pela pergunta gravada | `DELETE` por `id_usuario` e por busca do nome no texto |
| 2 | Matriz `.npz` da episódica | o vetor foi calculado a partir da pergunta com o nome | apaga as linhas pelo id do episódio e regrava o `.npz`. Com ~1.800 linhas isso leva segundos: **não exige reconstruir o índice**, só regravar a matriz sem as linhas |
| 3 | `memoria_semantica` | `confirmado_por` = id do Administrador. O valor não deveria ter nome, por causa da lista fechada | `DELETE` por `confirmado_por`, mais a varredura |
| 4 | **Procedural**, `prompts/sistema_vN.md` | uma regra aprendida com o erro de alguém que mencione essa pessoa | **proibido na origem**: a revisão do prompt barra nomes próprios. Se algum passar, é preciso reescrever o arquivo **e o histórico do git** (`git filter-repo`), porque cada versão antiga continua no repositório |
| 5 | **Checkpoint**, `checkpoints/*.json` | guarda `mensagens` (a pergunta) e os argumentos de cada passo | apaga o arquivo inteiro. Se houver um pendente, a execução é cancelada |
| 6 | **Log**, `logs/*.jsonl` | o evento `inicio` guarda a `pergunta`, o evento `ferramenta` guarda os `argumentos` e o evento `fim` guarda a `resposta` | apaga o arquivo da execução. Não dá para editar só uma linha e manter o log como prova. Retenção padrão: 90 dias |
| 7 | `logs/resumo.md`, `logs/v1/` | cópias das trajetórias de demonstração | regerar pelo `src.avaliar`, que usa perguntas sintéticas |
| 8 | `alertas_agente.mensagem` | texto livre de até 200 caracteres escrito pelo modelo | varredura; troca a mensagem por `[removido]` e mantém o alerta, porque ele é da loja e não do titular |
| 9 | `dados/casos.json` | uma pergunta real que virou caso de teste | regra: os casos são sintéticos; a varredura confirma |
| 10 | Histórico do chat no navegador (`chat.js`) e no corpo do `/chat` | a conversa corrente | some ao recarregar a página. O `Hydra.Agent` não grava o corpo da requisição (**o `debug` do Flask precisa ficar desligado em produção**) |
| 11 | Backups do SQLite e do `.npz` | cópias de 1 a 11 | a retenção do backup precisa ser ≤ 90 dias, ou a remoção não se cumpre até ele expirar. **Declarado**: o backup sai no próximo ciclo |
| 12 | O provedor do modelo (Groq/OpenAI) | cada chamada enviou a pergunta | **fora do nosso alcance**. Fica registrado qual provedor recebeu, a política de retenção dele (**[PENDENTE]** conferir) e o aviso no Termo de Uso |

**Verificação, independente da remoção.** O script de remoção não se autoaprova. Um segundo script, `varrer_titular.py`, que
não reaproveita o código da remoção, procura o identificador em todas as estruturas: nas colunas de texto do SQLite, em
`checkpoints/`, `logs/`, `prompts/`, `dados/`, no histórico do git (`git log -S "<nome>" --all`) e nos ids de metadados do `.npz`.
Um vetor não se procura com grep: verifica-se que nenhum id de episódio removido continua na matriz e que o número de linhas da
matriz é igual ao número de linhas de `memoria_episodica`.

O procedimento de teste, que vai para o `08-complementar`:

1. grava um titular sintético, `Titular Teste 7F3A` com `id_usuario = 9999`, em **cada uma** das 12 estruturas que o repositório
   controla (1 a 11): uma pergunta, um fato, um alerta, um checkpoint e um log;
2. roda `varrer_titular.py`, que precisa achar ≥ 1 ocorrência em cada estrutura (isso prova que a varredura enxerga);
3. roda a remoção;
4. roda `varrer_titular.py` de novo, e o resultado esperado é **0 ocorrências**. A remoção só é declarada concluída com essa
   saída, que é anexada ao registro do pedido.

**Remoção para recuperar um incidente.** Um episódio envenenado (por exemplo, um fato falso vindo de uma pergunta maliciosa) sai
com o mesmo `DELETE`, mais a regravação da matriz, sem esperar uma janela de manutenção. O único item que exige reconstrução é o
histórico do git na procedural, e por isso nome e conteúdo de fora não entram lá.

### 2.4 O preço: o sistema deixou de ser reprodutível

Com memória, a mesma pergunta ("registre um alerta para o queijo"), no mesmo modelo, com `temperature=0` e o mesmo prompt,
responde diferente amanhã: hoje o agente pergunta qual queijo, e amanhã resolve pelo apelido que aprendeu. Isso é consequência da
Decisão 1, escolhida de propósito, e não defeito.

Para a avaliação da aula 11 conviver com isso:

- o `src.avaliar` roda por padrão com a **memória desligada** (`MEMORIA=off`), e assim continua medindo só prompt e modelo. O
  5 de 5 atual continua comparável;
- a avaliação **com** memória parte de um **snapshot fixo** (`dados/memoria_seed.json`), e o hash desse snapshot entra no
  carimbo, ao lado do sha do prompt. Um resultado sem esse hash não é comparável com outro;
- a diferença entre as duas rodadas é o efeito da memória. Separar prompt de memória é trabalho, e esse é o trabalho.

---

## A questão: o que o agente não guarda, e o que ele perde quando perde

**Não guarda** nada que o banco responde (saldo, validade, vendas), porque isso seria uma segunda verdade envelhecendo. Não
guarda o que o Administrador afirmou sem conferência, nem o que o modelo concluiu, porque a memória é durável e o erro sairia
dela muitas vezes. Não guarda dado pessoal: CPF, e-mail, senha, chave de API e nome de pessoa em fato semântico ou em regra.

**Quando perde**, perde assim:

- **Por contradição**, o fato antigo deixa de ser usado mas continua gravado. O agente perde só a versão velha, com o descarte
  registrado no log.
- **Por decaimento**, perde os episódios de mais de 90 dias, ou seja, o "já tentamos isso em junho". Os fatos semânticos só
  ficam marcados como duvidosos.
- **Por remoção**, perde tudo o que citava o titular: os episódios, os fatos que ele confirmou, os checkpoints e os logs dessas
  execuções. O que **não** perde são os alertas da loja, que ficam sem o texto. E o que já foi enviado ao provedor do modelo
  está fora do alcance de qualquer remoção nossa, e está declarado aqui.
