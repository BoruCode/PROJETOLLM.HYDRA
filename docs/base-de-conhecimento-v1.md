# Base de conhecimento do Hydra — v1

Projeto: Hydra, PDV e controle de estoque para pequenos comércios. O assistente de IA atende só o Administrador (RF24, RN27) e hoje responde apenas por consulta ao banco; ainda não tem base de documentos. Este texto define o que entra nela.

## 1. Qual informação especializada o agente precisa, e por que ela não está no modelo

A pergunta do Administrador decide o documento que a responde:

| Pergunta do usuário (exemplo) | Onde está a resposta | Por que não vem do modelo |
|---|---|---|
| "Quanto tenho de X?", "O que vence esta semana?", "Qual o mais vendido no mês?" | Banco MySQL (`produtos`, `lotes`, `vendas`, `itens_venda`) | **Privado**, e muda a cada venda. |
| "Quem pode aplicar desconto?", "Em quanto tempo expira o código de recuperação?", "Posso excluir um produto já vendido?" | Regras de negócio RN01–RN29 | **Específico demais**: o modelo conhece PDV em geral, mas não que aqui o código expira em 15 min (RN26) ou que produto vendido só se inativa (RN03). Ele erraria o detalhe com a mesma confiança com que acerta. |
| "O Assistente pode alterar o estoque?", "O que o Administrador pode fazer?" | Requisitos RF01–RF24 e RN04, RN16, RN27–RN29 | **Privado e recente**: RN22–RN29 e RF24 foram acrescentadas em 17/09/2026. |
| "O que o Hydra faz com o CPF do cliente?" | Termo de Uso e Política de Privacidade (Apêndices E e F) | **Privado**: texto próprio da equipe. |
| "Como faço uma venda com PIX?" | Cap. 4 (descrição das telas) | **Privado**: é o fluxo do Hydra, não do mercado. |

**O que o modelo já sabe e não será indexado:** conceitos gerais de gestão de estoque (giro, estoque mínimo, curva ABC), o que é um PDV e boas práticas de reposição. É o Cap. 2 (Referencial Teórico). Indexá-lo seria pagar contexto que não acrescenta nada.

**Teste a executar antes de fechar a lista:** perguntar ao modelo, sem contexto, (1) o prazo de expiração do código de recuperação, (2) quem pode alterar preços, (3) se produto vendido pode ser excluído, (4) quais formas de pagamento o Hydra aceita e (5) se o Assistente pode editar estoque; conferir contra RN26, RN04, RN03, RN10 e RN28. Se o modelo acertar tudo, o índice de regras perde a razão de existir.

## 2. Onde esses dados estão, e em que estado

| Fonte | Onde vive | Formato | Dono e frequência de mudança | Acesso |
|---|---|---|---|---|
| Documentação técnica (regras, requisitos, telas, apêndices) | Repositório do projeto, arquivo `SISTEMA HYDRA TCC- DOCUMENTAÇÃO_TÉCNICA_PROJETO_TCC2.docx` | Word: ~24 mil palavras, 28 tabelas, 39 figuras | Equipe do TCC; muda até a entrega (última alteração de regras em 17/09/2026) | Sim, está no repositório |
| Termo de Uso e Política de Privacidade | Dentro do mesmo `.docx` (Apêndices E e F) | Word | Equipe | Sim |
| Estoque, lotes e vendas | MySQL do back-end (`schema.sql`) | Registros | Operação da loja; a cada venda | Sim, o serviço do assistente já conecta ao banco |
| Manual de uso do PDV | **Não existe** | — | — | **Lacuna:** o mais próximo é o Cap. 4. Sem manual, o assistente só responde "como faço X" com o que o Cap. 4 descrever. |
| Faturamento, custo, lucro e margem (citados no RF24) | Banco, se `itens_venda` guardar custo | Registros | Operação | **A verificar** no `schema.sql` |

Nenhuma fonte é PDF escaneado: o `.docx` tem texto nativo e as 39 figuras são capturas de tela, que ficam de fora. O sumário, o índice de ilustrações e as referências somam cerca de 170 parágrafos sem valor para as perguntas e serão descartados na extração.

## 3. O que vai para o índice, e o que não vai

**Entra** (estimativa de 150 a 300 chunks, contada por seção e por linha de tabela, ainda não medida com o chunker rodando):
- Regras de negócio RN01–RN29: 29 chunks.
- Requisitos funcionais RF01–RF24: 24 chunks.
- Cap. 3 (descrição, casos de uso, arquitetura, acessibilidade) e Cap. 4 (uma tela por seção): 60 a 100 chunks.
- Termo de Uso e Política de Privacidade: 20 a 40 chunks.
- Histórico de alterações de regras e requisitos: poucos chunks, marcados como histórico.

**Fica de fora:** Cap. 2 (o modelo já sabe), benchmarking, SWOT, orçamento, referências, sumário, atas de reunião (Apêndices B e C) e figuras. Nenhum deles responde a uma pergunta do Administrador sobre a loja ou o sistema.

**Vira consulta estruturada, nunca busca por similaridade:**

| Pergunta | Mecanismo |
|---|---|
| Saldo e status de um produto | SQL: `produtos.quantidade <= estoque_minimo` |
| O que vence em N dias | SQL: `lotes.validade <= CURDATE() + N` |
| Mais vendidos ou parados no período | SQL: agregação em `itens_venda` e `vendas` |
| Regra ativa ou removida (a RN12 foi removida) | **Filtro de metadado** `estado == "Ativo"` sobre a base de regras |

**Escala e ferramenta:** ~200 chunks × 1536 dimensões cabem em uma matriz de numpy em memória (poucos MB), calculada na subida do serviço e guardada em arquivo `.npz`. Não vou usar banco vetorial: nessa escala ele perde para a matriz. Só reavalio se o corpus passar de dezenas de milhares de chunks, o que este projeto não deve atingir.

## 4. Estratégia de chunking

São cinco tipos de documento e cinco cortes, não uma estratégia só:

| Documento | Unidade natural | Corte | Faz sentido sozinho? | Metadados |
|---|---|---|---|---|
| Regras de negócio (tabela) | Uma linha (RNxx) | 1 chunk por linha: `RN04 — Restrição de Acesso: <texto>` | Sim, o identificador e o título vão junto | `id`, `tipo=regra`, `estado` (ativo ou removido), `perfil`, `versao` |
| Requisitos (RFxx) | Do `[RFxx] Título:` até o próximo | 1 chunk por requisito, com a prioridade (Essencial, Importante, Desejável) | Sim | `id`, `tipo=requisito`, `perfil`, `prioridade` |
| Cap. 3 e 4 (prosa com títulos) | Seção (Título 2 e 3) | Por seção; se passar de ~1.500 caracteres, divide por parágrafo com 1 de sobreposição | Só com o cabeçalho herdado (`Cap. 4 > 4.8 Tela do Caixa`), pois "esta tela" sozinho não diz qual | `tipo=tela` ou `arquitetura`, `capitulo`, `secao` |
| Termo de Uso e Política de Privacidade | Seção ou cláusula | Por seção, herdando o nome do documento | Sim, com o cabeçalho herdado | `tipo=juridico`, `documento`, `secao` |
| Histórico de alterações | Uma linha de alteração | 1 chunk por linha | Sim | `tipo=historico`, `id` afetado, `data` |

**Fallback:** trecho sem título é cortado por 1.200 caracteres (~200 palavras, um parágrafo argumentativo) com 150 de sobreposição. Deve ser exceção.

**Extração:** ler o `.docx` com `python-docx`, guiado pelos estilos de parágrafo (`Título 1/2/3`), descartando os estilos de sumário e de índice de ilustrações. As tabelas são lidas por linha, não como texto corrido.

**Uso do metadado:** o filtro `estado == "Ativo"` vale por padrão, para nunca citar a RN12 removida; `tipo` restringe a busca a regras, telas ou textos jurídicos conforme a pergunta.
