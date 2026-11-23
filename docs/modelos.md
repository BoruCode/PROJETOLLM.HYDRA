# Análise de modelos: Parte 1

Objetivo: justificar uma escolha, não catalogar o mercado. Os números da 3.2 e da 3.3 vêm de `python -m src.comparar`
(bloco marcado abaixo); o resto foi consultado ou medido e a fonte está em `docs/fontes.md`.

## 3.1 Os candidatos

| Candidato | Por que entra |
|---|---|
| **gpt-oss-120b** (Groq) | o modelo usado nos testes do grupo; tool calling; 5 de 5 casos com o prompt v2 |
| **gpt-oss-20b** (Groq) | mesma família e metade do preço: a pergunta é se o menor sustenta os 5 casos |
| **Mistral Small** (Mistral, `mistral-small-latest`) | o modelo dos laboratórios da disciplina; provedor europeu |

Os eixos abaixo são os que mudam a decisão **neste caso**. Contexto e multimídia ficaram de fora do peso porque não decidem: o
prompt mais o histórico de uma pergunta têm ~1,3 a 2,5 mil tokens, e o caso é só texto.

| Eixo | Por que importa no nosso caso | gpt-oss-120b | gpt-oss-20b | Mistral Small |
|---|---|---|---|---|
| Tool calling e saída estruturada | pré-requisito: sem isso não há agente | sim | sim (\*) | sim |
| Capacidade de raciocínio | 1 a 3 passos: encadear o lote e comparar afirmação com dado | modelo de raciocínio | modelo de raciocínio, menor | medido em 3.3 |
| Custo por 1M de tokens (entrada / saída) | multiplica o número de chamadas por execução | US$ 0,15 / 0,60 | US$ 0,075 / 0,30 | US$ 0,15 / 0,60 |
| Latência | há alguém esperando na frente da tela | medida em 3.3 | medida em 3.3 | medida em 3.3 |
| Janela de contexto | histórico pequeno: não decide | 131 mil | 131 mil | 262 mil |
| Onde roda | API pública | Groq (EUA) | Groq (EUA) | Mistral (UE) |
| Limite do plano gratuito | a demonstração faz 10 a 15 chamadas | 8.000 tokens/min e 200.000/dia (\*\*) | idem | respondeu 429 desde a 1ª chamada em 20/09/2026 |
| Política de dados | hoje só trafegam dados simulados | conferir os termos do provedor antes de enviar dados reais | idem | idem |

(\*) Suporte a ferramentas do 20b inferido da família gpt-oss; só fica confirmado se `comparar` rodar os casos com chamada de
ferramenta sem erro do provedor.
(\*\*) Segundo agregadores; o console do Groq (página Limits) é a fonte oficial.

## 3.2 A conta

```
tokens de entrada por chamada  x  nº de chamadas por execução  x  preço de entrada
+ tokens de saída por chamada  x  nº de chamadas por execução  x  preço de saída
= custo por execução
```

**Medição avulsa** (20/09/2026, gpt-oss-120b, prompt v2): a pergunta "Quais lotes vencem em até 3 dias?" usou **2 chamadas e
2.559 tokens** no total. Sem a separação entre entrada e saída, o custo por execução fica entre **US$ 0,0004** (tudo entrada)
e **US$ 0,0015** (tudo saída). A tabela do bloco abaixo traz o valor exato, por candidato, com as duas partes separadas.

## 3.3 A verificação mínima

Cinco casos do domínio (`dados/casos.json`), o mesmo prompt em todos os candidatos, temperature 0. Não são uma medição
estatística: são o embrião do benchmark próprio da Parte 3.

<!-- COMPARACAO:INICIO -->
_Pendente: rode `python -m src.comparar` (precisa de `GROQ_API_KEY` e, para o terceiro candidato, `MISTRAL_API_KEY` no `.env`).
Este bloco é reescrito com a tabela de casos, o tempo, os tokens e o custo por execução, por 100 execuções e no semestre._
<!-- COMPARACAO:FIM -->

**Histórico do prompt com o gpt-oss-120b (medido pelo grupo em 20/09/2026; logs em `logs/v1/` e `logs/`):**

| Prompt | 01 | 02 | 03 | 04 | 05 | Passaram |
|---|---|---|---|---|---|---|
| v1 (`sistema_v1.md`) | OK | OK | FALHOU | FALHOU | OK | 3 de 5 |
| v2 (`sistema_v2.md`) | OK | OK | OK | OK | OK | 5 de 5 |

Nos casos 03 e 04 a v1 respondia "quantos dias?" sem chamar nenhuma ferramenta (nada foi gravado). A v2 manda achar produto e lote
sozinho. **Ressalva:** a v2 foi ajustada olhando estes mesmos casos; com 5 casos não dá para afirmar que generaliza.

## 3.4 A decisão

**Decisão provisória: `openai/gpt-oss-120b` via Groq**, o único candidato com 5 de 5 medido pelo grupo (em 20/09/2026). Vale
reavaliar depois de `python -m src.comparar`.

**Em que condições mudaríamos de ideia:**

1. Se o **gpt-oss-20b** passar 5 de 5 com tempo igual ou menor, troca para ele: custa metade.
2. Se o **Mistral Small** passar 5 de 5 e a Parte 3 exigir dados de clientes ou provedor na UE, ele passa a ser o candidato.
3. Se o limite do plano gratuito (8.000 tokens/min) travar o benchmark maior da Parte 3, migrar para plano pago do mesmo provedor
   (só mudam preços e limites, não o código).
4. Se a Parte 3 multiplicar as chamadas por execução (multiagente), refazer a conta da 3.2 antes de manter o modelo.
5. Se algum candidato deixar de chamar ferramentas de forma válida numa atualização do provedor, o verificador acusa (queda
   de 5 de 5) antes de a demonstração quebrar.
