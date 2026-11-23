-- ============================================================
-- Espelho em SQLite das tabelas do Hydra.Back/schema.sql (MySQL)
-- que o agente consulta: lojas, produtos, lotes, vendas, itens_venda.
-- Mesmos nomes de tabela e de coluna; só os tipos foram simplificados.
--
-- alertas_agente é a ÚNICA tabela nova: a fila de alertas que o agente
-- escreve para o Administrador revisar. Não altera estoque, produtos,
-- vendas, clientes nem usuários.
-- ============================================================
PRAGMA foreign_keys = ON;

CREATE TABLE lojas (
    id_loja   INTEGER PRIMARY KEY,
    nome_loja TEXT NOT NULL
);

CREATE TABLE produtos (
    id_produto     INTEGER PRIMARY KEY,
    id_loja        INTEGER NOT NULL REFERENCES lojas(id_loja) ON DELETE CASCADE,
    codigo_externo TEXT NOT NULL,
    nome           TEXT NOT NULL,
    categoria      TEXT,
    preco_custo    NUMERIC NOT NULL DEFAULT 0,
    preco_venda    NUMERIC NOT NULL DEFAULT 0,
    quantidade     NUMERIC NOT NULL DEFAULT 0,
    estoque_minimo NUMERIC NOT NULL DEFAULT 0,
    unidade        TEXT NOT NULL DEFAULT 'un',
    UNIQUE (id_loja, codigo_externo)
);

CREATE TABLE lotes (
    id_lote     INTEGER PRIMARY KEY,
    id_produto  INTEGER NOT NULL REFERENCES produtos(id_produto) ON DELETE CASCADE,
    codigo_lote TEXT,
    validade    TEXT NOT NULL,            -- 'YYYY-MM-DD'
    quantidade  NUMERIC NOT NULL DEFAULT 0
);
CREATE INDEX idx_lotes_validade ON lotes (validade);

CREATE TABLE vendas (
    id_venda        INTEGER PRIMARY KEY,
    id_loja         INTEGER NOT NULL REFERENCES lojas(id_loja) ON DELETE CASCADE,
    codigo_externo  TEXT NOT NULL,
    forma_pagamento TEXT,
    total           NUMERIC NOT NULL DEFAULT 0,
    data_venda      TEXT NOT NULL,        -- 'YYYY-MM-DD HH:MM:SS'
    UNIQUE (id_loja, codigo_externo)
);
CREATE INDEX idx_vendas_data ON vendas (id_loja, data_venda);

CREATE TABLE itens_venda (
    id_item        INTEGER PRIMARY KEY,
    id_venda       INTEGER NOT NULL REFERENCES vendas(id_venda) ON DELETE CASCADE,
    id_produto     INTEGER REFERENCES produtos(id_produto) ON DELETE SET NULL,
    nome_produto   TEXT NOT NULL,
    quantidade     NUMERIC NOT NULL,
    preco_unitario NUMERIC NOT NULL
);

-- Escrita do agente. Reversível: descartar = UPDATE ... SET status = 'descartado'.
CREATE TABLE alertas_agente (
    id_alerta  INTEGER PRIMARY KEY,
    id_loja    INTEGER NOT NULL REFERENCES lojas(id_loja) ON DELETE CASCADE,
    id_produto INTEGER NOT NULL REFERENCES produtos(id_produto) ON DELETE CASCADE,
    id_lote    INTEGER REFERENCES lotes(id_lote) ON DELETE CASCADE,
    tipo       TEXT NOT NULL CHECK (tipo IN ('validade', 'estoque_baixo')),
    mensagem   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto', 'descartado')),
    criado_em  TEXT NOT NULL,
    -- Parte 2: id_execucao:passo:id_da_chamada. Uma retomada que repete a escrita não duplica o alerta.
    chave_idempotencia TEXT UNIQUE
);

-- ============================================================
-- Parte 2: memória de longo prazo (docs/memoria.md)
-- ============================================================

-- Semântica: fatos da loja que o banco não tem e que o Administrador CONFIRMOU.
-- Sem chave única de propósito: cada mudança é uma linha nova; na leitura vale o maior valido_desde (contradição).
CREATE TABLE memoria_semantica (
    id             INTEGER PRIMARY KEY,
    id_loja        INTEGER NOT NULL REFERENCES lojas(id_loja) ON DELETE CASCADE,
    chave          TEXT NOT NULL,
    valor          TEXT NOT NULL,
    valido_desde   TEXT NOT NULL,          -- obrigatório: é o critério de desempate
    fonte          TEXT NOT NULL,          -- ex.: 'lembrar_fato'
    confirmado_por TEXT NOT NULL,          -- quem aprovou a gravação
    id_execucao    TEXT
);
CREATE INDEX idx_mem_sem ON memoria_semantica (id_loja, chave, valido_desde);

-- Episódica: uma linha por execução encerrada com resposta_final, escrita pelo CÓDIGO.
-- Guarda o que as ferramentas devolveram e o que o código decidiu; nunca o texto do modelo.
CREATE TABLE memoria_episodica (
    id            INTEGER PRIMARY KEY,
    id_loja       INTEGER NOT NULL REFERENCES lojas(id_loja) ON DELETE CASCADE,
    id_execucao   TEXT NOT NULL UNIQUE,
    criado_em     TEXT NOT NULL,
    pergunta      TEXT NOT NULL,
    resumo        TEXT NOT NULL,           -- montado em código a partir das chamadas e resultados
    terminacao    TEXT NOT NULL,
    prompt_versao TEXT,
    limite_dias   INTEGER                  -- regra de validade em vigor (para marcar [regra anterior])
);
CREATE INDEX idx_mem_epi ON memoria_episodica (id_loja, criado_em);
