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
    criado_em  TEXT NOT NULL
);
