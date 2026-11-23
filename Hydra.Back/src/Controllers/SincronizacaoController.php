<?php

namespace Hydra\Controllers;

use Hydra\Support\Auth;
use Hydra\Support\Request;
use Hydra\Support\Response;

/**
 * Ponte entre o front (HydroStore, que ainda guarda tudo no localStorage)
 * e o MySQL. O front envia o estado completo de produtos, vendas e
 * movimentações; aqui é feito upsert idempotente por (id_loja, codigo_externo),
 * de modo que o Agente de IA consulte dados reais no banco.
 */
final class SincronizacaoController
{
    /** PUT /api/sincronizar */
    public function sincronizar(): void
    {
        $user = Auth::requireLogin();
        $idLoja = $user['id_loja'];
        $dados = Request::json();

        $produtos = is_array($dados['products'] ?? null) ? $dados['products'] : [];
        $vendas = is_array($dados['sales'] ?? null) ? $dados['sales'] : [];
        $movimentos = is_array($dados['movements'] ?? null) ? $dados['movements'] : [];

        $pdo = db();
        $pdo->beginTransaction();
        try {
            $mapa = $this->sincronizarProdutos($pdo, $idLoja, $produtos);
            $this->sincronizarVendas($pdo, $idLoja, $vendas, $mapa);
            $this->sincronizarMovimentos($pdo, $idLoja, $movimentos, $mapa);
            $pdo->commit();
        } catch (\Throwable $e) {
            $pdo->rollBack();
            throw $e;
        }

        Response::json([
            'produtos' => count($produtos),
            'vendas' => count($vendas),
            'movimentacoes' => count($movimentos),
        ]);
    }

    /** @return array<string,int> codigo_externo => id_produto */
    private function sincronizarProdutos(\PDO $pdo, int $idLoja, array $produtos): array
    {
        $upsert = $pdo->prepare(
            'INSERT INTO produtos
                (id_loja, codigo_externo, nome, descricao, sku, plu, categoria,
                 preco_custo, preco_venda, quantidade, estoque_minimo, unidade)
             VALUES
                (:id_loja, :codigo, :nome, :descricao, :sku, :plu, :categoria,
                 :custo, :venda, :quantidade, :minimo, :unidade)
             ON DUPLICATE KEY UPDATE
                nome = VALUES(nome), descricao = VALUES(descricao), sku = VALUES(sku),
                plu = VALUES(plu), categoria = VALUES(categoria),
                preco_custo = VALUES(preco_custo), preco_venda = VALUES(preco_venda),
                quantidade = VALUES(quantidade), estoque_minimo = VALUES(estoque_minimo),
                unidade = VALUES(unidade)'
        );

        $codigos = [];
        foreach ($produtos as $p) {
            $codigo = trim((string) ($p['id'] ?? ''));
            $nome = trim((string) ($p['name'] ?? ''));
            if ($codigo === '' || $nome === '') {
                continue;
            }
            $codigos[] = $codigo;
            $upsert->execute([
                'id_loja' => $idLoja,
                'codigo' => $codigo,
                'nome' => $nome,
                'descricao' => $this->textoOuNulo($p['desc'] ?? null),
                'sku' => $this->textoOuNulo($p['sku'] ?? null),
                'plu' => $this->textoOuNulo($p['plu'] ?? null),
                'categoria' => $this->textoOuNulo($p['category'] ?? null),
                'custo' => (float) ($p['costPrice'] ?? 0),
                'venda' => (float) ($p['price'] ?? 0),
                'quantidade' => (float) ($p['quantity'] ?? 0),
                'minimo' => (float) ($p['minStock'] ?? 0),
                'unidade' => $this->textoOuNulo($p['unit'] ?? null) ?? 'un',
            ]);
        }

        // Produtos excluídos no front somem do banco (o histórico de vendas
        // e movimentações fica, pois as FKs são ON DELETE SET NULL).
        if ($codigos === []) {
            $pdo->prepare('DELETE FROM produtos WHERE id_loja = ?')->execute([$idLoja]);
        } else {
            $marcadores = implode(',', array_fill(0, count($codigos), '?'));
            $pdo->prepare("DELETE FROM produtos WHERE id_loja = ? AND codigo_externo NOT IN ($marcadores)")
                ->execute(array_merge([$idLoja], $codigos));
        }

        $stmt = $pdo->prepare('SELECT codigo_externo, id_produto FROM produtos WHERE id_loja = ?');
        $stmt->execute([$idLoja]);
        $mapa = [];
        foreach ($stmt->fetchAll() as $row) {
            $mapa[$row['codigo_externo']] = (int) $row['id_produto'];
        }

        $this->sincronizarValidades($pdo, $produtos, $mapa);
        return $mapa;
    }

    /**
     * A tela de produtos guarda uma única validade por produto. Ela vira um
     * lote automático (codigo_lote = 'AUTO'), recriado a cada sincronização;
     * lotes cadastrados manualmente via /api/lotes não são tocados.
     */
    private function sincronizarValidades(\PDO $pdo, array $produtos, array $mapa): void
    {
        $remove = $pdo->prepare("DELETE FROM lotes WHERE id_produto = ? AND codigo_lote = 'AUTO'");
        $insere = $pdo->prepare(
            "INSERT INTO lotes (id_produto, codigo_lote, validade, quantidade) VALUES (?, 'AUTO', ?, ?)"
        );

        foreach ($produtos as $p) {
            $idProduto = $mapa[trim((string) ($p['id'] ?? ''))] ?? null;
            if ($idProduto === null) {
                continue;
            }
            $remove->execute([$idProduto]);

            $validade = \DateTime::createFromFormat('Y-m-d', (string) ($p['validade'] ?? ''));
            if ($validade !== false) {
                $insere->execute([$idProduto, $validade->format('Y-m-d'), (float) ($p['quantity'] ?? 0)]);
            }
        }
    }

    private function sincronizarVendas(\PDO $pdo, int $idLoja, array $vendas, array $mapa): void
    {
        $existe = $pdo->prepare('SELECT 1 FROM vendas WHERE id_loja = ? AND codigo_externo = ?');
        $insereVenda = $pdo->prepare(
            'INSERT INTO vendas (id_loja, codigo_externo, numero_pedido, forma_pagamento, total, data_venda)
             VALUES (:id_loja, :codigo, :pedido, :pagamento, :total, :data)'
        );
        $insereItem = $pdo->prepare(
            'INSERT INTO itens_venda (id_venda, id_produto, nome_produto, quantidade, preco_unitario)
             VALUES (:id_venda, :id_produto, :nome, :quantidade, :preco)'
        );

        foreach ($vendas as $v) {
            $codigo = trim((string) ($v['id'] ?? ''));
            if ($codigo === '') {
                continue;
            }
            $existe->execute([$idLoja, $codigo]);
            if ($existe->fetchColumn()) {
                continue; // vendas são imutáveis: já sincronizada
            }

            $insereVenda->execute([
                'id_loja' => $idLoja,
                'codigo' => $codigo,
                'pedido' => isset($v['orderId']) ? (int) $v['orderId'] : null,
                'pagamento' => $this->textoOuNulo($v['payment'] ?? null),
                'total' => (float) ($v['total'] ?? 0),
                'data' => $this->dataMysql($v['date'] ?? null),
            ]);
            $idVenda = (int) $pdo->lastInsertId();

            foreach ((is_array($v['items'] ?? null) ? $v['items'] : []) as $item) {
                $insereItem->execute([
                    'id_venda' => $idVenda,
                    'id_produto' => $mapa[(string) ($item['productId'] ?? '')] ?? null,
                    'nome' => (string) ($item['name'] ?? ''),
                    'quantidade' => (float) ($item['qty'] ?? 0),
                    'preco' => (float) ($item['price'] ?? 0),
                ]);
            }
        }
    }

    private function sincronizarMovimentos(\PDO $pdo, int $idLoja, array $movimentos, array $mapa): void
    {
        $insere = $pdo->prepare(
            'INSERT IGNORE INTO movimentacoes_estoque
                (id_loja, codigo_externo, id_produto, nome_produto, tipo, quantidade, origem, data_movimento)
             VALUES (:id_loja, :codigo, :id_produto, :nome, :tipo, :quantidade, :origem, :data)'
        );

        foreach ($movimentos as $m) {
            $codigo = trim((string) ($m['id'] ?? ''));
            $tipo = $m['type'] ?? '';
            if ($codigo === '' || !in_array($tipo, ['entrada', 'saida'], true)) {
                continue;
            }
            $insere->execute([
                'id_loja' => $idLoja,
                'codigo' => $codigo,
                'id_produto' => $mapa[(string) ($m['productId'] ?? '')] ?? null,
                'nome' => (string) ($m['productName'] ?? ''),
                'tipo' => $tipo,
                'quantidade' => (float) ($m['qty'] ?? 0),
                'origem' => $this->textoOuNulo($m['source'] ?? null),
                'data' => $this->dataMysql($m['date'] ?? null),
            ]);
        }
    }

    private function textoOuNulo(mixed $valor): ?string
    {
        $texto = trim((string) ($valor ?? ''));
        return $texto === '' ? null : $texto;
    }

    /** Converte o ISO 8601 do front (UTC) para DATETIME do MySQL. */
    private function dataMysql(mixed $iso): string
    {
        $ts = is_string($iso) ? strtotime($iso) : false;
        return date('Y-m-d H:i:s', $ts !== false ? $ts : time());
    }
}
