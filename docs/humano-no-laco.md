# O ponto em que o agente para e espera uma pessoa

**Código:** `no_ferramentas`, `no_pausar` e `no_retomar` em `src/grafo.py` · `src/checkpoint.py` · `--confirmar pausar`,
`--pendentes` e `--retomar` em `src/main.py` · **Testes:** `TestPausaERetomada` em `tests/test_parte2.py`

## 1. Onde ele para

Em **toda escrita** — `registrar_alerta` (fila de alertas) e `lembrar_fato` (memória da loja) — e **só depois de o código
validar a regra**. Leitura nunca para.

```
modelo pede uma escrita
   └─> VALIDAR (código): produto existe? lote na janela de 30 dias? saldo ≤ mínimo? já existe alerta aberto?
                          chave na lista fechada? dado pessoal?
         ├─ violou ──> o erro volta ao modelo como dado. O humano NÃO é incomodado
         └─ válida ──> CONFIRMAR (humano)
                         ├─ modo sincrono: pergunta no terminal, "Confirmar? [s/N]"
                         └─ modo pausar:  grava o checkpoint, terminação aguardando_humano, o processo termina
```

**Por que nas escritas, e não no fim.** O agente só causa efeito no mundo por essas duas ferramentas. Aprovar a resposta final
seria aprovar texto. Aprovar a escrita é aprovar a ação, uma de cada vez: com três alertas na mesma resposta do modelo, são
três aprovações (`test_duas_escritas_na_mesma_resposta_pausam_uma_de_cada_vez`).

**Por que validar antes.** Pedir aprovação para uma escrita que o código vai recusar treina o humano a aprovar sem ler.

## 2. Os dois modos

| | `sincrono` (padrão) | `pausar` |
|---|---|---|
| Como ativar | `--confirmar perguntar` (ou `sim`/`nao` para automatizar) | `--confirmar pausar`, ou `MODO_CONFIRMACAO=pausar` no `.env` |
| O processo | espera o `s/N` no terminal | termina; a terminação é `aguardando_humano` (código de saída 0) |
| Quem aprova | quem está no terminal | qualquer processo que tenha acesso aos checkpoints: outro terminal hoje, a tela do Hydra na Parte 3 |
| Quando | na hora | horas depois |

## 3. A retomada

```bash
python -m src.main "Registre um alerta de estoque baixo para o Feijão Carioca 1kg." --confirmar pausar
python -m src.main --pendentes                           # lista o que espera aprovação, com o texto da ação
python -m src.main --retomar <id> --aprovar --por "Felipe"    # ou --recusar
```

O que `grafo.retomar` faz, e o teste de cada garantia:

| Garantia | Por quê | Teste |
|---|---|---|
| Recusa se a execução não está `aguardando_humano` | a mesma aprovação não roda duas vezes | `test_retomar_duas_vezes_e_recusado` |
| Recusa se o **prompt mudou** desde a pausa (sha diferente) | a aprovação foi pedida sob outras regras | `test_retomada_recusa_se_o_prompt_mudou` |
| Recusa se a execução é de **outra loja** | isolamento de loja | (verificação em `retomar`) |
| **Valida a regra de novo** antes de escrever | em 4 horas o feijão pode ter sido reposto; o resultado volta com `revalidado_na_retomada: true` | `test_retomada_revalida_a_regra_porque_o_mundo_mudou` |
| Escreve com a **chave de idempotência** `id_execucao:passo:id_da_chamada` (coluna `UNIQUE`) | uma queda entre o `INSERT` e o checkpoint, seguida de nova retomada, não duplica o alerta | `test_idempotencia_a_mesma_chave_nao_duplica` |
| **Continua o orçamento**, sem zerar | a pausa não é um jeito de ganhar passos | `test_retomada_aprovada_escreve_uma_vez_e_continua_o_orcamento` |
| Registra **quem** aprovou, **quando** e quando foi pedido | prova da decisão humana no log (`confirmacao.por`, `em`, `pedido_em`) | idem |
| A recusa vira o erro `nao_confirmado` para o modelo, com a dica "não insista" | o agente diz que nada foi feito | `test_retomada_recusada_nao_escreve` |

## 4. O que o humano vê

O texto da confirmação é montado **pelo código** a partir do banco (`descrever_alerta`, `descrever_fato`), com o nome exato do
produto resolvido e, no fato, o que ele substitui: "Guardar na memória da loja: apelido:o leite = Leite Integral 1L (substitui
o fato #3)". A mensagem livre do alerta (até 200 caracteres) é a única parte escrita pelo modelo que aparece na tela.

## 5. Limites conhecidos

- **Quem aprova não é autenticado.** O `--por` é texto livre, e qualquer um com acesso à pasta `checkpoints/` e ao terminal
  aprova. A RN27 (só o Administrador usa o assistente) só vai valer na aprovação quando ela vier da tela do Hydra, com a sessão
  do usuário. **Lacuna para a Parte 3.**
- **Não há prazo de expiração** para uma pausa: um pendente esquecido fica no disco até alguém decidir. A revalidação protege a
  regra, mas não o contexto (o Administrador pode nem lembrar mais da pergunta). Candidato: expirar após 24 h, como recusa.
- **A mensagem do alerta** vem do modelo e é mostrada como está, só com o limite de tamanho.
