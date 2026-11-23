# RAG — as regras do Hydra como base de conhecimento

**Implementa:** `docs/base-de-conhecimento-v1.md` (Exercício 6), com os desvios marcados abaixo.
**Código:** `src/rag.py` (índice e busca) · `consultar_regras` em `src/ferramentas.py` (a ferramenta) ·
`src/avaliar_rag.py` (a medição) · **Corpus:** `dados/corpus/base_v1.jsonl`

## 1. Para que serve

O banco responde saldo, validade e vendas. Ele não responde **como o Hydra funciona**: quem pode alterar preço (RN04), em
quanto tempo expira o código de recuperação (RN26), se produto vendido pode ser excluído (RN03), o que o assistente pode
fazer (RN27, RN28). O modelo conhece PDV em geral, mas não esses detalhes, e erraria "15 minutos" com a mesma confiança com
que acerta. O RAG entra no grafo como uma **ferramenta** (`consultar_regras`), e não como contexto fixo: o modelo decide
quando a pergunta é sobre regra, e as perguntas de estoque não pagam os tokens dos trechos.

## 2. O corpus

| Fonte | Trechos | Como foi extraído |
|---|---|---|
| Regras de negócio RN01–RN29 (Quadro 9 da documentação técnica do TCC) | 29 | uma linha da tabela = um trecho: `id`, `titulo`, `texto` |
| Requisitos funcionais RF01–RF24 | 24 | do `[RFxx] Título:` até o próximo, sem a linha de prioridade, até 600 caracteres |
| **Total** | **53** | extraídos do `.docx` do repositório (texto nativo; figuras e sumário fora) |

Cada trecho tem o metadado `estado`. O índice só carrega `estado == "ativo"` (`indice_padrao`), e por isso uma regra removida
nunca é citada.

**Desvio em relação ao Exercício 6:**

- **Ficaram de fora nesta versão** os capítulos 3 e 4 (telas) e os Apêndices E e F (Termo de Uso e Política de Privacidade).
  As perguntas do case são sobre regras e permissões, e as telas descrevem o fluxo de quem opera o caixa, não o Administrador.
  Fica como próximo passo, com o mesmo chunker por seção.
- **A RN12.** O Quadro 10 diz que a RN12 ("emitir comprovante") foi removida em 17/09/2026, mas o Quadro 9 atual traz uma RN12
  diferente ("Cancelamento de venda"). Indexamos o Quadro 9 como está, com a RN12 ativa. **A inconsistência é do documento do
  TCC** e precisa ser resolvida lá (Quadros 9 e 10).
- **A política interna de desconto/reposição por validade e o trecho do CDC** sobre produto vencido, citados no Exercício 6,
  **não entraram**: a política não existe escrita, e o grupo decidiu não indexar texto que ela ainda não aprovou.

## 3. Chunking

A unidade natural do documento é a linha da tabela (RN) e o bloco do requisito (RF). Um trecho = uma regra ou um requisito,
com o identificador e o título no próprio texto indexado. Assim ele faz sentido sozinho ("RN26 — Prazo de expiração do código
de recuperação: ..."). Nenhum trecho passou de 600 caracteres, então o corte por tamanho (1.500, com sobreposição) não foi
acionado. O teto de 1.500 caracteres por trecho continua no código (`MAX_CARACTERES`).

## 4. Indexação e busca: BM25, e não embeddings

**Desvio deliberado.** O Exercício 6 previa embeddings de 1.536 dimensões numa matriz numpy. Trocamos por **BM25** (busca
lexical, k1 = 1,5, b = 0,75), escrito em `src/rag.py` sem dependência nova, porque:

1. **o provedor do case (Groq, `docs/modelos.md`) não oferece endpoint de embeddings.** Usar embeddings exigiria um segundo
   provedor, uma segunda chave e mais um ponto de falha;
2. o corpus tem 53 trechos curtos, cheios de termos do domínio ("estoque mínimo", "Administrador", "CPF", "recuperação"), e
   a sobreposição de termos já separa bem os trechos (§5);
3. BM25 é determinístico e roda sem rede: a medição do §5 não depende de serviço externo.

Normalização (`normalizar`): minúsculas, sem acento, sem pontuação, sem stopwords, e um radical grosseiro (corta sufixos como
`-ção`, `-ido`, `-ar`, `-s` e a vogal final). Citar o identificador ("o que diz a RN12") soma +10 ao score do trecho.

**Corte por score:** `SCORE_MINIMO = 3,6`. Abaixo disso, a ferramenta devolve `trechos: []` e um `aviso` que manda o modelo
dizer que a documentação não trata do assunto.

## 5. A medição

`python -m src.avaliar_rag`, sobre `dados/perguntas_rag.json`: 14 perguntas com resposta conhecida (as 5 do teste do Exercício
6 §1, mais 9 sintéticas) e 3 fora da base.

| Medida | Resultado (23/11/2026) |
|---|---|
| recall@1 | **93%** (13 de 14) |
| recall@3 | **100%** (14 de 14) |
| perguntas fora da base sem trecho | **3 de 3** |

**Como o limiar foi escolhido, e o problema disso.** Com o limiar inicial de 1,0, as perguntas fora da base traziam ruído
("nota fiscal" → RF05, com score 2,95). Com 4,0, a pergunta "Quem pode ver o financeiro?" perdia a RN16 (score 3,86). O menor
acerto medido foi 3,86, o maior ruído foi 3,36, e escolhemos 3,6 entre os dois. **O limiar foi calibrado no mesmo conjunto
que o mede**, e por isso os 100% acima são otimistas. A correção é separar um conjunto de validação com as perguntas reais do
Administrador (Exercício 11, fonte 4) e medir nele.

**Um defeito do gabarito, achado pela medição.** "Dá para vender um produto sem estoque?" tinha gabarito RN01, e o índice
trouxe a RN08 em 3º lugar. A RN08 ("um produto só pode ser adicionado à venda se houver quantidade disponível") também responde.
O gabarito passou a aceitar as duas, e a mudança está anotada no campo `nota` da pergunta.

**O teste que trava a medição:** `test_recall_do_conjunto_de_referencia` (`tests/test_parte2.py`) falha se o recall@3 cair
abaixo de 90% ou se uma pergunta fora da base passar a trazer trecho.

## 6. Limites conhecidos

- **Sinônimo sem termo em comum.** "senha esquecida" recupera RN23 (tamanho da senha) antes da RN05 (recuperação), porque
  "esquecida" não aparece no corpus. Embeddings resolveriam esse caso, e BM25 não.
- **O limiar é frágil** (§5): uma pergunta curta e genérica pode ficar abaixo de 3,6 mesmo tendo resposta.
- **A busca não sabe de tempo.** Se uma RN mudar, o corpus precisa ser regerado. O identificador e a fonte vão em cada trecho
  para que a resposta possa ser conferida no documento.
