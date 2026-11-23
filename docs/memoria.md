# Memória do agente — o que foi implementado

**Implementa:** o rascunho do Exercício 8 (`Hydra.Agent/memoria.md`, mantido como histórico da decisão).
**Código:** `src/memoria.py` (longo prazo) · `src/checkpoint.py` (curto prazo) · `lembrar_fato` em `src/ferramentas.py` ·
`no_preparar` e `no_finalizar` em `src/grafo.py` · `src/manutencao.py` (esquecimento por tempo)
**Tabelas:** `memoria_semantica` e `memoria_episodica` em `dados/schema.sql`
**Testes:** `TestMemoriaSemantica` e `TestMemoriaEpisodica` em `tests/test_parte2.py`

Cada linha abaixo diz se está **[IMPLEMENTADO]**, com onde, ou **[PENDENTE]**, com o que falta.

---

## 1. Os dois níveis

| | Curto prazo | Longo prazo |
|---|---|---|
| **O que é** | a janela de **uma execução** (do `inicio` ao `fim`, atravessando uma pausa) | o que atravessa execuções da mesma loja (`id_loja`) |
| **Persistido como** | `checkpoints/<id_execucao>.json`, gravado a cada nó que muda o estado **[IMPLEMENTADO]** (`grafo._salvar`) | `memoria_semantica`, `memoria_episodica` e o prompt versionado **[IMPLEMENTADO]** |
| **Lido** | na retomada (`grafo.retomar`) | no nó `preparar`, uma vez por execução |
| **Ciclo de vida** | `aguardando_humano` fica até ser decidido; `encerrada` é apagado após 7 dias (`python -m src.manutencao`) **[IMPLEMENTADO]** | §3 |

O que vai no checkpoint, campo a campo, está em `docs/arquitetura.md` §2. Ele não guarda chave de API nem nada do `.env`.

## 2. O longo prazo

| Tipo | O que guarda | Quem escreve | Como é lida | Estado |
|---|---|---|---|---|
| **Semântica** | fatos que o banco não tem e que o Administrador confirmou: apelido de produto, janela de validade preferida, prazo de fornecedor, produto descontinuado | o **modelo propõe** (`lembrar_fato`), o **código valida**, o **humano confirma** | todos os fatos vigentes da loja entram no bloco `MEMÓRIA DA LOJA` (até 10; acima disso, só os citados na pergunta) | **[IMPLEMENTADO]** |
| **Episódica** | uma linha por execução terminada em `resposta_final`: a pergunta e um resumo **montado em código** com as ferramentas, os argumentos, o resumo de cada resultado, os alertas e os fatos gravados | o **código**, no nó `finalizar` | os 3 episódios mais parecidos com a pergunta (BM25), acima de score 1,0 | **[IMPLEMENTADO]** |
| **Procedural** | as regras de comportamento | o grupo, numa nova versão de `prompts/sistema_vN.md` | sempre inteira, como prompt de sistema | **[IMPLEMENTADO]** (v3) |

**Desvio:** o rascunho previa embeddings numa matriz `.npz` para a episódica. Usamos o mesmo **BM25** do RAG, pelo mesmo
motivo (o Groq não tem endpoint de embeddings; ver `docs/rag.md` §4). Com isso não existe matriz para regravar na remoção, e o
§2.3 do rascunho fica mais simples.

### 2.1 A lista fechada de chaves semânticas **[IMPLEMENTADO]** (`CHAVES`, `validar_fato`)

| Chave | Valor | Validação em código |
|---|---|---|
| `apelido:<como ele chama>` | nome do produto | o produto precisa existir **nesta loja**, e o que se grava é o **nome exato do banco**, e não o texto do modelo |
| `preferencia:janela_validade` | dias | inteiro de 1 a 365 |
| `fornecedor:<nome>:prazo_dias` | dias | inteiro de 1 a 90 |
| `produto:<nome>:descontinuado` | sim/não | o produto precisa existir |

Fora dessa lista, a ferramenta devolve `chave_nao_permitida`, e o humano nem chega a ser consultado. O teste
`test_chave_fora_da_lista_e_saldo_nao_entram` tenta `saldo:leite`, `cliente:joao` e `instrucao` e confere a recusa.

### 2.2 Onde a memória muda o comportamento

O apelido é usado **pelo código**, e não só pelo modelo: `consultar_estoque(produto="o queijo")` e
`registrar_alerta(produto="o queijo", ...)` resolvem pelo apelido vigente (`_resolver_produto`). Com a memória desligada
(`MEMORIA=off`), o mesmo pedido volta vazio (`test_sem_memoria_o_apelido_nao_vale`). O caso de demonstração 08 mostra o efeito:
"registre um alerta de validade para o queijo" vira o alerta do lote L-QUE-01, sem a pergunta "qual queijo?".

## 3. O esquecimento

| Causa | Regra | Estado |
|---|---|---|
| **Contradição** | por chave vale o maior `valido_desde`, e no empate o maior `id`. O preterido continua gravado, e cada descarte vira o evento `memoria_descartada` no log com `id_descartado` e `id_vigente` | **[IMPLEMENTADO]** (`ler_fatos`; teste `test_contradicao_...`; caso 11) |
| **Decaimento, episódica** | com mais de 30 dias pesa a metade; com mais de 90 não é recuperada, e `src.manutencao` apaga a linha | **[IMPLEMENTADO]** (`buscar_episodios`, `apagar_episodios_antigos`) |
| **Decaimento, semântica** | sem nova confirmação há 180 dias, entra marcada "não confirmado há 180+ dias: pergunte se continua valendo". Não é apagada | **[IMPLEMENTADO]** (`bloco_de_contexto`) |
| **Regra que mudou** | um episódio gravado com outro `limite_dias` entra com a marca `[regra anterior]` | **[IMPLEMENTADO]** (coluna `limite_dias`) |
| **Remoção a pedido do titular** | o procedimento das 12 estruturas e o `varrer_titular.py` independente | **[PENDENTE]**: nenhum dos dois scripts existe ainda. Hoje a remoção é manual (`DELETE` nas duas tabelas, mais apagar o checkpoint e o log da execução) |

## 4. O orçamento da janela

| Fonte | Teto | Estado |
|---|---|---|
| Fatos semânticos | 10 fatos e 800 caracteres (~200 tokens) | **[IMPLEMENTADO]** (`MAX_FATOS`, `MAX_CARACTERES_SEMANTICA`) |
| Episódios | 3 episódios e 1.600 caracteres (~400 tokens); descarta primeiro o de menor score | **[IMPLEMENTADO]** (`MAX_EPISODIOS`, `MAX_CARACTERES_EPISODICA`) |
| Resumo de cada episódio | 500 caracteres | **[IMPLEMENTADO]** |
| Trechos de RAG | 3 trechos de até 1.500 caracteres | **[IMPLEMENTADO]** (`rag.K`, `rag.MAX_CARACTERES`) |
| **Teto total por chamada (6.000 tokens), resumo dos resultados antigos e a terminação `orcamento_janela`** | | **[PENDENTE]**: continua valendo só o teto acumulado por execução (`MAX_TOKENS`). **Medido com o modelo real** (`openai/gpt-oss-120b`, 13 casos da Parte 2): a maior chamada teve **2.923 tokens de entrada** (`logs/parte2/rodada1/08_memoria_apelido.jsonl`, linha 8, passo 4; 2.918 e 2.923 no mesmo ponto das rodadas 2 e 3). É menos da metade do teto planejado de 6.000. Como o log grava `tokens_entrada` acumulado, a chamada isolada é a diferença entre dois eventos `passo` seguidos. Ressalva: nenhum caso encheu a memória (10 fatos) nem trouxe 3 trechos longos ao mesmo tempo, então o pior caso continua sem medição |

## 5. O que a memória não guarda

| Não guarda | Onde isso é garantido |
|---|---|
| Saldo, validade, vendas (o que o banco responde) | não existe chave para isso na lista fechada; regra 10 do prompt |
| Dado pessoal e credencial no fato: CPF, e-mail, telefone, chave de API, "senha"/"token" | `dado_sensivel` em `validar_fato`, que recusa **antes** de pedir confirmação (`test_dado_sensivel_e_recusado_antes_de_pedir_confirmacao`) |
| Pergunta com dado pessoal na episódica | grava `[pergunta com dado pessoal omitida]` (`test_pergunta_com_dado_pessoal_e_omitida`) |
| O texto do modelo | o resumo do episódio é montado só com chamadas e resultados (`test_grava_episodio_so_com_o_que_as_ferramentas_devolveram`) |
| Afirmação do Administrador sem conferência ("o leite tem uns 200") | não há chave para quantidade; o episódio guarda o que a ferramenta devolveu, e não o que ele disse |
| Execução interrompida (`erro_llm`, `orcamento_*`, pausa) | `gravar_episodio` só grava `resposta_final` (`test_execucao_interrompida_nao_vira_episodio`) |

**O limite do filtro de dado pessoal:** ele pega formatos (CPF, e-mail, telefone), e não nomes. "O João do caixa" pode entrar
pela pergunta na episódica. A lista fechada impede que um nome vire valor de fato semântico (exceto o nome de um produto que
existe), mas na episódica a defesa contra nomes é só o prazo de 90 dias.

## 6. O preço: o agente deixou de ser reprodutível

Com memória, a mesma pergunta responde diferente amanhã. Por isso, a demonstração (`src.avaliar`) roda com **memória desligada**
por padrão, e só os casos marcados `"memoria": true` a ligam, partindo de um banco recriado e de uma `fixture_sql` fixa. O hash
da memória lida vai no carimbo do checkpoint (`memoria.hash_memoria`). Um resultado sem esse hash não se compara com outro.
