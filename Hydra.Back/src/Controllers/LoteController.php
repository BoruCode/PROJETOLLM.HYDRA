<?php

namespace Hydra\Controllers;

use Hydra\Support\Auth;
use Hydra\Support\Request;
use Hydra\Support\Response;

/**
 * Lotes com data de validade por produto. Alimenta a ferramenta
 * consultar_validade do Agente de IA.
 */
final class LoteController
{
    /** GET /api/lotes */
    public function index(): void
    {
        $user = Auth::requireLogin();
        $stmt = db()->prepare(
            'SELECT l.id_lote, l.id_produto, p.nome AS produto, l.codigo_lote, l.validade, l.quantidade
             FROM lotes l
             JOIN produtos p ON p.id_produto = l.id_produto
             WHERE p.id_loja = :id_loja
             ORDER BY l.validade ASC'
        );
        $stmt->execute(['id_loja' => $user['id_loja']]);
        Response::json(['lotes' => $stmt->fetchAll()]);
    }

    /** POST /api/lotes  { codigo_produto, codigo_lote?, validade (AAAA-MM-DD), quantidade } */
    public function store(): void
    {
        $user = Auth::requireLogin();
        if ($user['perfil'] === 'operador_caixa') {
            Response::json(['erro' => 'Sem permissão para cadastrar lotes'], 403);
            return;
        }
        $dados = Request::json();

        $validade = \DateTime::createFromFormat('Y-m-d', (string) ($dados['validade'] ?? ''));
        $quantidade = (float) ($dados['quantidade'] ?? 0);
        if ($validade === false || $quantidade <= 0) {
            Response::json(['erro' => 'Informe validade (AAAA-MM-DD) e quantidade maior que zero'], 422);
            return;
        }

        $stmt = db()->prepare('SELECT id_produto FROM produtos WHERE id_loja = ? AND codigo_externo = ?');
        $stmt->execute([$user['id_loja'], (string) ($dados['codigo_produto'] ?? '')]);
        $idProduto = $stmt->fetchColumn();
        if ($idProduto === false) {
            Response::json(['erro' => 'Produto não encontrado (sincronize os produtos primeiro)'], 404);
            return;
        }

        $codigoLote = trim((string) ($dados['codigo_lote'] ?? ''));
        $ins = db()->prepare(
            'INSERT INTO lotes (id_produto, codigo_lote, validade, quantidade)
             VALUES (:id_produto, :codigo_lote, :validade, :quantidade)'
        );
        $ins->execute([
            'id_produto' => $idProduto,
            'codigo_lote' => $codigoLote !== '' ? $codigoLote : null,
            'validade' => $validade->format('Y-m-d'),
            'quantidade' => $quantidade,
        ]);

        Response::json(['id_lote' => (int) db()->lastInsertId()], 201);
    }
}
