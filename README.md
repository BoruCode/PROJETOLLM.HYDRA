# Hydra — Assistente de estoque com agente de IA

**Grupo:** Alef Kaique Santos Almeida de Araujo · Felipe Claudiano Synthes · Maria Eduarda Leonardo de Souza
**Disciplina:** Agentes de IA — Parte 1 (escolher e provar o terreno) · Centro Universitário Senac

**O problema em uma frase:** o Administrador de um mercado de bairro perde tempo cruzando telas de estoque, validade e vendas
para decidir o que repor ou liquidar, e não tem onde registrar o que decidiu acompanhar.

O repositório também guarda o sistema Hydra (TCC): `Hydra.Front`, `Hydra.Back` e `Hydra.Agent`. Para rodar o sistema
completo, veja [`COMO-RODAR.md`](COMO-RODAR.md). **Este README trata só do agente da Parte 1.**

## Como rodar

Precisa de Python 3.10 ou mais novo e de uma chave de API de um provedor compatível com a biblioteca `openai`.

```bash
git clone https://github.com/BoruCode/PROJETOLLM.HYDRA.git
cd PROJETOLLM.HYDRA
python -m venv .venv
.venv\Scripts\activate            # Windows        (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Windows        (Linux/macOS: cp .env.example .env)
```

Abra o `.env` e preencha `LLM_BASE_URL`, `OPENAI_API_KEY` e `LLM_MODEL`. Depois:

```bash
python -m src.main "Quais produtos estão abaixo do estoque mínimo?"
```

O banco simulado (`dados/hydra_demo.db`) é criado sozinho na primeira execução. Para recriá-lo: `python -m src.criar_banco`.
Nenhuma chave vai para o git: o `.env` está no `.gitignore`.

## Como usar

**O que digitar.** Uma pergunta em português, em texto livre, como o Administrador faria:

```bash
python -m src.main "sua pergunta"      # uma pergunta e sai
python -m src.main                     # modo interativo, com histórico; linha vazia ou "sair" encerra
```

Opções: `--confirmar perguntar|sim|nao` (como tratar a confirmação das escritas; o padrão é perguntar) e `--recriar-banco`.

**O que o sistema faz.** O modelo escolhe quais consultas fazer (vendas, estoque, validade), o código as executa no SQLite
e devolve o resultado, e o modelo responde. Se o Administrador pedir, o agente registra um **alerta** (de validade ou de
estoque baixo) na fila `alertas_agente`. Antes de gravar, o código confere as regras (o lote vence em até 30 dias? o
estoque está no mínimo ou abaixo? já existe alerta igual?) e o terminal pede a sua confirmação: `Confirmar? [s/N]`.

**O que você recebe.** A resposta em até 6 linhas e uma linha de fechamento:

```
Terminou por: resposta_final | passos: <n> | tokens: <n> | custo: <valor ou n/d> | alertas registrados: <#ids ou nenhum>
Log: logs/execucao_<data>_<hora>.jsonl
```

`Terminou por` diz por que o agente parou (`resposta_final` é o normal; `orcamento_*` e `erro_llm` são falhas, veja
[`docs/arquitetura.md`](docs/arquitetura.md)). O log tem uma linha JSON por evento: ferramenta chamada, argumentos, resultado e erro.

### Exemplo completo (execução real)

> **A preencher antes da entrega:** rode `python -m src.avaliar` e copie de `logs/resumo.md` o caso `01_simples`
> (entrada, trajetória e resposta). O enunciado pede saída copiada de uma execução real, então não escreva à mão.

### Demonstração com os casos difíceis

```bash
python -m src.avaliar               # roda os 5 casos de dados/casos.json e confere cada um contra o gabarito
python -m src.avaliar --caso 02_divergencia
```

| Caso | O que testa |
|---|---|
| `01_simples` | consulta a validade e registra 3 alertas (o gabarito é o conjunto exato de lotes) |
| `02_divergencia` | o Administrador diz "200 litros", o banco tem 6: o agente deve contradizer com o dado |
| `03_registro_inexistente` | produto que não existe: o erro da ferramenta volta como dado e o agente não troca de produto sozinho |
| `04_nao_disparar` | alerta para lote que vence em 200 dias: o código barra, nada é gravado |
| `05_extra_rn28` | pedido para zerar estoque: o agente recusa (RN28) |

Os logs de cada caso ficam em `logs/` e o resumo com aprovados/reprovados em `logs/resumo.md`. Os dados e os casos difíceis
estão descritos em [`dados/LEIAME.md`](dados/LEIAME.md).

### O que o sistema não faz

- Não altera estoque, produtos, vendas, clientes nem usuários. A única escrita é o alerta, que pode ser descartado
  (`UPDATE alertas_agente SET status = 'descartado' WHERE id_alerta = ...`).
- Só responde com dados do banco. Se não houver o dado (por exemplo, faturamento ou lucro, que nenhuma ferramenta desta parte consulta),
  o prompt manda dizer que não tem em vez de estimar.
- Não conecta ao MySQL do Hydra nesta parte: usa um espelho em SQLite com dados simulados. A integração real vira servidor
  MCP na Parte 2.
- Quando não consegue responder, termina com um motivo (`orcamento_*`, `erro_llm`, `resposta_vazia`) e avisa no terminal.

## Testes

```bash
python -m unittest -v
```

Os testes usam um modelo falso (nenhuma chamada de API) e verificam ferramentas, laço, orçamento, confirmação,
tratamento de erro e o verificador. A qualidade do modelo é medida por `python -m src.avaliar`.

## Estrutura da entrega

```
README.md            este arquivo
requirements.txt     dependências com versão fixada
.env.example         nomes das variáveis, sem valores
prompts/             prompts versionados (sistema_v1.md)
src/                 o agente: agente.py (laço), ferramentas.py, db.py, main.py, avaliar.py
dados/               schema, seed simulado, casos.json, LEIAME.md (casos difíceis nomeados)
logs/                logs das execuções demonstradas
docs/                arquitetura.md (pronto); case.md, modelos.md e fontes.md (a escrever pelo grupo)
tests/               testes com modelo falso
```
