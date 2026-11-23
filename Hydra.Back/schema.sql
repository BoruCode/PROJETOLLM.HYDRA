-- ============================================================
-- SISTEMA HYDRA - Schema do módulo de Cadastro de Usuário
-- e Permissões (Usuários + Loja)
-- Banco: MySQL 8
--
-- Telas cobertas por este schema:
--   - Cadastro (Fig. 13)        -> INSERT em lojas + INSERT em usuarios (perfil = administrador)
--   - Login (Fig. 14)           -> SELECT em usuarios (email, senha) + UPDATE ultimo_acesso
--   - Recuperar senha (Fig. 15) -> UPDATE reset_token / reset_token_expira_em
--   - Gerenciar Usuários        -> CRUD em usuarios (perfil = operador_caixa/estoquista)
--   - Configurações da Loja     -> UPDATE em lojas
--
-- Este arquivo é idempotente (CREATE TABLE IF NOT EXISTS) e reflete
-- exatamente o que já está aplicado no banco "hydra_db" local.
-- ============================================================

CREATE TABLE IF NOT EXISTS lojas (
    id_loja         INT AUTO_INCREMENT PRIMARY KEY,
    nome_loja       VARCHAR(120) NOT NULL,
    cnpj            VARCHAR(18)  NULL UNIQUE,
    telefone        VARCHAR(15)  NULL,
    endereco        VARCHAR(150) NULL,
    cidade          VARCHAR(60)  NULL,
    estado          VARCHAR(2)   NULL,
    cep             VARCHAR(10)  NULL,
    status          ENUM('ativa', 'inativa') NOT NULL DEFAULT 'ativa',
    data_criacao    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario              INT AUTO_INCREMENT PRIMARY KEY,
    id_loja                 INT NOT NULL,
    nome                    VARCHAR(100)  NOT NULL,
    email                   VARCHAR(100)  NOT NULL UNIQUE,
    senha                   VARCHAR(255)  NOT NULL,          -- hash (bcrypt), nunca texto puro
    perfil                  ENUM('administrador', 'operador_caixa', 'estoquista') NOT NULL,
    status                  ENUM('ativo', 'inativo') NOT NULL DEFAULT 'ativo',
    data_criacao            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ultimo_acesso           DATETIME NULL,

    -- suporte à tela de Recuperação de Senha (RN05)
    reset_token             VARCHAR(255) NULL,
    reset_token_expira_em   DATETIME NULL,

    -- suporte ao "Lembrar de mim" da tela de Login
    remember_token          VARCHAR(255) NULL,

    FOREIGN KEY (id_loja) REFERENCES lojas(id_loja)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- Índices de apoio às consultas mais frequentes do módulo
CREATE INDEX idx_usuarios_id_loja ON usuarios (id_loja);
CREATE INDEX idx_usuarios_perfil  ON usuarios (perfil);


-- ============================================================
-- Módulo de Clientes (PDV)
--   RF07 - Edição e Exclusão de Clientes
--   RF08 - Busca e Filtragem de Clientes (nome, CPF)
--   RF14 - Consentimento para inclusão de CPF
--   RN15 - Sem cadastro duplicado de clientes com o mesmo CPF (por loja)
--   RN16 - Associação de cliente à venda é opcional
--   RN18 - Coletar apenas o necessário para identificação do cliente
--
-- CPF é opcional e só pode ser preenchido com o consentimento explícito
-- do cliente (consentimento_cpf = TRUE). O e-mail é o identificador
-- alternativo quando não há CPF, permitindo rastrear o histórico do
-- cliente (via id_cliente nas vendas) mesmo sem dado documental.
-- ============================================================

CREATE TABLE IF NOT EXISTS clientes (
    id_cliente          INT AUTO_INCREMENT PRIMARY KEY,
    id_loja             INT NOT NULL,
    nome                VARCHAR(120) NOT NULL,
    cpf                 VARCHAR(14)  NULL,
    email               VARCHAR(100) NULL,
    telefone            VARCHAR(15)  NULL,
    consentimento_cpf   BOOLEAN NOT NULL DEFAULT FALSE,
    data_criacao        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (id_loja) REFERENCES lojas(id_loja)
        ON DELETE CASCADE,

    -- NULL não conta para UNIQUE em MySQL, então múltiplos clientes sem
    -- CPF na mesma loja são permitidos; só bloqueia CPF repetido.
    UNIQUE KEY uq_clientes_loja_cpf (id_loja, cpf)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_clientes_id_loja ON clientes (id_loja);
CREATE INDEX idx_clientes_email   ON clientes (email);


-- ============================================================
-- Regras de negócio aplicadas neste modelo (referência ao TCC)
--   RN04 - Restrição de Acesso: apenas perfil 'administrador'
--          altera preços/descontos/relatórios financeiros e acessa
--          Gerenciar Usuários / Configurações da Loja
--   RN05 - Recuperação de Senha Segura: token com validade
--          (reset_token_expira_em)
--   RN06 - Acesso ao sistema: apenas usuários autenticados,
--          conforme perfil (enum fechado)
--   RN07 - Permissão de venda: 'operador_caixa' ou 'administrador'
--   RN21 - Confirmação prévia antes de excluir usuário/produto/cliente
-- ============================================================


-- ============================================================
-- Módulo de Estoque e Vendas (PDV) — base do Agente de IA
--   produtos                 -> catálogo e quantidade atual
--   lotes                    -> validade por lote (consultar_validade)
--   vendas / itens_venda     -> histórico de vendas (consultar_vendas)
--   movimentacoes_estoque    -> entradas e saídas
--
-- codigo_externo guarda o id gerado pelo front (HydroStore, ex.: "p1",
-- "sale_xxx"), usado por PUT /api/sincronizar para fazer upsert sem
-- duplicar registros. Quantidades são DECIMAL porque há produtos
-- vendidos por peso (kg).
-- ============================================================

CREATE TABLE IF NOT EXISTS produtos (
    id_produto      INT AUTO_INCREMENT PRIMARY KEY,
    id_loja         INT NOT NULL,
    codigo_externo  VARCHAR(60)  NOT NULL,
    nome            VARCHAR(150) NOT NULL,
    descricao       VARCHAR(255) NULL,
    sku             VARCHAR(40)  NULL,
    plu             VARCHAR(20)  NULL,
    categoria       VARCHAR(60)  NULL,
    preco_custo     DECIMAL(10,2) NOT NULL DEFAULT 0,
    preco_venda     DECIMAL(10,2) NOT NULL DEFAULT 0,
    quantidade      DECIMAL(10,3) NOT NULL DEFAULT 0,
    estoque_minimo  DECIMAL(10,3) NOT NULL DEFAULT 0,
    unidade         VARCHAR(10)  NOT NULL DEFAULT 'un',
    data_criacao    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (id_loja) REFERENCES lojas(id_loja) ON DELETE CASCADE,
    UNIQUE KEY uq_produtos_loja_codigo (id_loja, codigo_externo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_produtos_quantidade ON produtos (id_loja, quantidade);


CREATE TABLE IF NOT EXISTS lotes (
    id_lote         INT AUTO_INCREMENT PRIMARY KEY,
    id_produto      INT NOT NULL,
    codigo_lote     VARCHAR(40) NULL,
    validade        DATE NOT NULL,
    quantidade      DECIMAL(10,3) NOT NULL DEFAULT 0,
    data_criacao    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (id_produto) REFERENCES produtos(id_produto) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_lotes_validade ON lotes (validade);


CREATE TABLE IF NOT EXISTS vendas (
    id_venda        INT AUTO_INCREMENT PRIMARY KEY,
    id_loja         INT NOT NULL,
    codigo_externo  VARCHAR(60) NOT NULL,
    numero_pedido   INT NULL,
    id_cliente      INT NULL,                     -- RN16: cliente é opcional
    forma_pagamento VARCHAR(20) NULL,
    total           DECIMAL(10,2) NOT NULL DEFAULT 0,
    data_venda      DATETIME NOT NULL,

    FOREIGN KEY (id_loja) REFERENCES lojas(id_loja) ON DELETE CASCADE,
    FOREIGN KEY (id_cliente) REFERENCES clientes(id_cliente) ON DELETE SET NULL,
    UNIQUE KEY uq_vendas_loja_codigo (id_loja, codigo_externo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_vendas_data ON vendas (id_loja, data_venda);


CREATE TABLE IF NOT EXISTS itens_venda (
    id_item         INT AUTO_INCREMENT PRIMARY KEY,
    id_venda        INT NOT NULL,
    id_produto      INT NULL,                     -- NULL se o produto foi excluído depois
    nome_produto    VARCHAR(150) NOT NULL,        -- cópia do nome: preserva o histórico
    quantidade      DECIMAL(10,3) NOT NULL,
    preco_unitario  DECIMAL(10,2) NOT NULL,

    FOREIGN KEY (id_venda) REFERENCES vendas(id_venda) ON DELETE CASCADE,
    FOREIGN KEY (id_produto) REFERENCES produtos(id_produto) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS movimentacoes_estoque (
    id_movimentacao INT AUTO_INCREMENT PRIMARY KEY,
    id_loja         INT NOT NULL,
    codigo_externo  VARCHAR(60) NOT NULL,
    id_produto      INT NULL,
    nome_produto    VARCHAR(150) NOT NULL,
    tipo            ENUM('entrada', 'saida') NOT NULL,
    quantidade      DECIMAL(10,3) NOT NULL,
    origem          VARCHAR(20) NULL,             -- cadastro | estoque | venda
    data_movimento  DATETIME NOT NULL,

    FOREIGN KEY (id_loja) REFERENCES lojas(id_loja) ON DELETE CASCADE,
    FOREIGN KEY (id_produto) REFERENCES produtos(id_produto) ON DELETE SET NULL,
    UNIQUE KEY uq_mov_loja_codigo (id_loja, codigo_externo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
