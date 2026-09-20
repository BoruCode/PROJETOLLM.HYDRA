-- ============================================================
-- Dados SIMULADOS (nenhum dado real de loja, cliente ou CPF).
-- Datas são relativas ao dia da execução (validade "+3 dias" é sempre daqui a 3 dias),
-- então os casos difíceis continuam difíceis em qualquer data.
-- Os casos difíceis estão nomeados em dados/LEIAME.md.
-- ============================================================
INSERT INTO lojas (id_loja, nome_loja) VALUES (1, 'Mercado Modelo'), (2, 'Mercado Vizinho');

INSERT INTO produtos (id_produto, id_loja, codigo_externo, nome, categoria, preco_custo, preco_venda, quantidade, estoque_minimo, unidade) VALUES
 (1,  1, 'p1',  'Arroz Tipo 1 5kg',         'Mercearia', 22.00, 29.90, 40,   10, 'un'),
 (2,  1, 'p2',  'Feijão Carioca 1kg',       'Mercearia',  6.50,  8.99,  8,   15, 'un'),
 (3,  1, 'p3',  'Leite Integral 1L',        'Laticínios', 4.20,  5.99,  6,   20, 'un'),
 (4,  1, 'p4',  'Iogurte Natural 170g',     'Laticínios', 1.60,  2.99, 12,   10, 'un'),
 (5,  1, 'p5',  'Pão de Forma 500g',        'Padaria',    5.10,  7.49,  9,    8, 'un'),
 (6,  1, 'p6',  'Queijo Mussarela Fatiado', 'Frios',     32.00, 44.90,  3.5,  2, 'kg'),
 (7,  1, 'p7',  'Presunto Fatiado',         'Frios',     24.00, 34.90,  2.2,  2, 'kg'),
 (8,  1, 'p8',  'Macarrão Espaguete 500g',  'Mercearia',  2.80,  4.49, 60,   20, 'un'),
 (9,  1, 'p9',  'Óleo de Soja 900ml',       'Mercearia',  5.90,  7.99, 30,   12, 'un'),
 (10, 1, 'p10', 'Açúcar Refinado 1kg',      'Mercearia',  3.50,  4.99, 25,   10, 'un'),
 (11, 1, 'p11', 'Café Torrado 500g',        'Mercearia', 11.00, 15.90, 14,   10, 'un'),
 (12, 1, 'p12', 'Sabão em Pó 1kg',          'Limpeza',    9.00, 13.90, 20,    8, 'un'),
 (13, 1, 'p13', 'Refrigerante Cola 2L',     'Bebidas',    6.20,  9.49, 48,   24, 'un'),
 (14, 1, 'p14', 'Banana Prata',             'Hortifruti', 3.20,  5.99, 12.5,  5, 'kg'),
 (15, 1, 'p15', 'Tomate',                   'Hortifruti', 4.50,  8.99,  7.8,  6, 'kg'),
 -- Loja 2: mesmo nome de produto com saldo bem diferente. O agente da loja 1 nunca pode ver isto.
 (16, 2, 'p3',  'Leite Integral 1L',        'Laticínios', 4.10,  5.79, 500,  20, 'un');

-- Lotes (dias = dias até vencer; negativo = já vencido). Soma dos lotes = quantidade do produto.
CREATE TEMP TABLE _lotes (cod TEXT, lote TEXT, dias INTEGER, qtd NUMERIC);
INSERT INTO _lotes VALUES
 ('p1',  'L-ARR-01', 200, 40),
 ('p2',  'L-FEI-01', 150,  8),
 ('p3',  'L-LEI-01',  25,  6),
 ('p4',  'L-IOG-01',   3, 12),
 ('p5',  'L-PAO-01',   2,  5),
 ('p5',  'L-PAO-02',  20,  4),
 ('p6',  'L-QUE-01',   6,  3.5),
 ('p7',  'L-PRE-01',  -1,  1.0),   -- já vencido e ainda com saldo
 ('p7',  'L-PRE-02',  12,  1.2),
 ('p8',  'L-MAC-01', 240, 60),
 ('p9',  'L-OLE-01', 300, 30),
 ('p10', 'L-ACU-01', 360, 25),
 ('p11', 'L-CAF-01', 150, 14),
 ('p13', 'L-REF-01',  90, 48),
 ('p14', 'L-BAN-01',   4, 12.5),
 ('p15', 'L-TOM-01',   5,  7.8);
INSERT INTO lotes (id_produto, codigo_lote, validade, quantidade)
SELECT p.id_produto, l.lote, date('now', 'localtime', printf('%+d days', l.dias)), l.qtd
  FROM _lotes l JOIN produtos p ON p.codigo_externo = l.cod AND p.id_loja = 1
 ORDER BY l.dias;
DROP TABLE _lotes;

-- Vendas (dias = quantos dias atrás). As vendas 13 e 14 estão FORA da janela de 30 dias.
INSERT INTO vendas (id_venda, id_loja, codigo_externo, forma_pagamento, data_venda)
SELECT v.id, 1, 'sale_' || v.id, v.pgto, datetime('now', 'localtime', printf('-%d days', v.dias))
  FROM (SELECT 1 AS id, 1 AS dias, 'pix' AS pgto UNION ALL SELECT 2, 2, 'dinheiro' UNION ALL SELECT 3, 4, 'debito'
        UNION ALL SELECT 4, 6, 'pix' UNION ALL SELECT 5, 9, 'credito' UNION ALL SELECT 6, 12, 'pix'
        UNION ALL SELECT 7, 15, 'dinheiro' UNION ALL SELECT 8, 18, 'debito' UNION ALL SELECT 9, 21, 'pix'
        UNION ALL SELECT 10, 24, 'credito' UNION ALL SELECT 11, 27, 'dinheiro' UNION ALL SELECT 12, 29, 'pix'
        UNION ALL SELECT 13, 45, 'pix' UNION ALL SELECT 14, 60, 'debito') v;

CREATE TEMP TABLE _itens (venda INTEGER, cod TEXT, qtd NUMERIC);
INSERT INTO _itens VALUES
 (1,'p3',12),(1,'p5',6),(1,'p1',2),
 (2,'p3',10),(2,'p13',4),(2,'p11',2),(2,'p2',3),
 (3,'p3',8),(3,'p4',3),(3,'p5',5),(3,'p14',2.5),
 (4,'p3',9),(4,'p1',4),(4,'p8',2),(4,'p15',1.8),
 (5,'p5',7),(5,'p13',5),(5,'p10',3),(5,'p9',2),
 (6,'p3',7),(6,'p2',6),(6,'p6',1.5),(6,'p7',0.8),
 (7,'p1',6),(7,'p11',3),(7,'p4',4),(7,'p14',3.5),
 (8,'p5',6),(8,'p13',4),(8,'p8',2),(8,'p15',2.4),
 (9,'p3',6),(9,'p2',5),(9,'p9',3),(9,'p10',3),
 (10,'p1',5),(10,'p4',3),(10,'p6',1.5),(10,'p7',1.0),
 (11,'p5',4),(11,'p13',5),(11,'p11',3),(11,'p14',3.5),
 (12,'p3',8),(12,'p1',8),(12,'p2',8),(12,'p10',3),(12,'p9',3),(12,'p8',2),(12,'p11',4),(12,'p15',3.0),(12,'p6',1.5),
 (13,'p12',5),(13,'p3',20),(13,'p1',10),
 (14,'p3',30),(14,'p5',20);
INSERT INTO itens_venda (id_venda, id_produto, nome_produto, quantidade, preco_unitario)
SELECT i.venda, p.id_produto, p.nome, i.qtd, p.preco_venda
  FROM _itens i JOIN produtos p ON p.codigo_externo = i.cod AND p.id_loja = 1;
DROP TABLE _itens;

UPDATE vendas SET total = COALESCE((SELECT ROUND(SUM(quantidade * preco_unitario), 2)
                                      FROM itens_venda WHERE itens_venda.id_venda = vendas.id_venda), 0);
