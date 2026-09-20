"""Ferramentas do agente.

O MODELO só pede a chamada; quem executa, valida e escreve é o CÓDIGO.
Toda ferramenta devolve um dict. Erro também é dado: {"erro", "detalhe", "dica"}, para o modelo
poder se corrigir em vez de a exceção derrubar o programa.

| ferramenta         | leitura/escrita | reversível | conversa com                       |
|--------------------|-----------------|------------|------------------------------------|
| consultar_vendas   | leitura         | -          | SQLite (vendas, itens_venda)       |
| consultar_estoque  | leitura         | -          | SQLite (produtos)                  |
| consultar_validade | leitura         | -          | SQLite (lotes, produtos)           |
| registrar_alerta   | ESCRITA         | sim        | SQLite (alertas_agente)            |
"""
from __future__ import annotations

import difflib
import sqlite3
from dataclasses import dataclass
from typing import Callable

TIPOS_ALERTA = ("validade", "estoque_baixo")
MAX_LINHAS = 50


@dataclass
class Contexto:
    """O que as ferramentas recebem do código (o modelo não vê nem controla isto)."""
    conn: sqlite3.Connection
    id_loja: int = 1
    limite_dias_validade: int = 30


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    funcao: Callable
    schema: dict
    escrita: bool = False
    reversivel: bool = True
    valida: Callable | None = None    # só escritas: checa as regras ANTES de pedir confirmação
    descreve: Callable | None = None  # só escritas: texto que o humano lê para confirmar


# --- utilitários -----------------------------------------------------------

def erro(codigo: str, detalhe: str, dica: str = "", **extra) -> dict:
    return {"erro": codigo, "detalhe": detalhe, "dica": dica, **extra}


def _consultar(ctx: Contexto, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(linha) for linha in ctx.conn.execute(sql, params).fetchall()]


def _inteiro(valor, nome: str, minimo: int, maximo: int):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None, erro("argumento_invalido", f"'{nome}'={valor!r} não é inteiro.",
                          f"Envie '{nome}' como inteiro entre {minimo} e {maximo}.")
    if not minimo <= numero <= maximo:
        return None, erro("argumento_invalido", f"'{nome}'={numero} fora do intervalo.",
                          f"Use '{nome}' entre {minimo} e {maximo}.")
    return numero, None


def _like(texto: str) -> str:
    """Escapa % e _ para o LIKE tratar o texto do modelo como texto literal."""
    return "%" + texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# --- leitura ---------------------------------------------------------------

def consultar_vendas(ctx: Contexto, ordem="desc", limite=5, dias=30) -> dict:
    """Produtos por quantidade vendida nos últimos N dias (desc = mais vendidos; asc = parados)."""
    ordem = "desc" if ordem is None else ordem  # null vindo do modelo = usar o padrao
    limite = 5 if limite is None else limite
    dias = 30 if dias is None else dias
    if ordem not in ("asc", "desc"):
        return erro("argumento_invalido", f"ordem={ordem!r}.",
                    "Use 'desc' (mais vendidos) ou 'asc' (menos vendidos / parados).")
    limite, e = _inteiro(limite, "limite", 1, MAX_LINHAS)
    if e:
        return e
    dias, e = _inteiro(dias, "dias", 1, 365)
    if e:
        return e
    direcao = "ASC" if ordem == "asc" else "DESC"  # vem do enum validado acima, nunca do texto do modelo
    # O CASE é necessário: a condição de data no ON do LEFT JOIN não remove os itens_venda de vendas
    # fora do período, só zera a venda. Sem o CASE, a soma ignoraria a janela de dias.
    sql = f"""
        SELECT p.nome, p.unidade,
               COALESCE(SUM(CASE WHEN v.id_venda IS NOT NULL THEN iv.quantidade END), 0) AS total_vendido
          FROM produtos p
          LEFT JOIN itens_venda iv ON iv.id_produto = p.id_produto
          LEFT JOIN vendas v ON v.id_venda = iv.id_venda
               AND v.data_venda >= datetime('now', 'localtime', ?)
         WHERE p.id_loja = ?
         GROUP BY p.id_produto, p.nome, p.unidade
         ORDER BY total_vendido {direcao}, p.nome
         LIMIT ?"""
    linhas = _consultar(ctx, sql, (f"-{dias} days", ctx.id_loja, limite))
    return {"periodo_dias": dias, "ordem": ordem, "linhas": linhas}


def consultar_estoque(ctx: Contexto, limite_minimo=None, produto=None) -> dict:
    """Saldo de estoque. Com 'produto': busca por parte do nome (qualquer saldo).
    Com 'limite_minimo': produtos com saldo <= limite. Sem nada: saldo <= estoque_minimo de cada produto."""
    base = "SELECT nome, quantidade, estoque_minimo, unidade FROM produtos WHERE id_loja = ?"
    if produto:
        texto = str(produto).strip()
        sql = base + " AND nome LIKE ? ESCAPE '\\' ORDER BY nome LIMIT ?"
        params = (ctx.id_loja, _like(texto), MAX_LINHAS)
        filtro = f"nome contém '{texto}'"
    elif limite_minimo is not None:
        try:
            teto = float(limite_minimo)
        except (TypeError, ValueError):
            return erro("argumento_invalido", f"limite_minimo={limite_minimo!r} não é número.",
                        "Envie um número, ou omita para usar o mínimo de cada produto.")
        sql = base + " AND quantidade <= ? ORDER BY quantidade ASC LIMIT ?"
        params = (ctx.id_loja, teto, MAX_LINHAS)
        filtro = f"quantidade <= {teto:g}"
    else:
        sql = base + " AND quantidade <= estoque_minimo ORDER BY quantidade ASC LIMIT ?"
        params = (ctx.id_loja, MAX_LINHAS)
        filtro = "quantidade <= estoque_minimo de cada produto"
    linhas = _consultar(ctx, sql, params)
    for linha in linhas:
        linha["abaixo_do_minimo"] = linha["quantidade"] <= linha["estoque_minimo"]
    resultado = {"filtro": filtro, "linhas": linhas}
    if not linhas:
        resultado["aviso"] = "Nenhum produto encontrado com esse filtro."
    return resultado


def consultar_validade(ctx: Contexto, dias=7) -> dict:
    """Lotes com saldo que vencem em até N dias (inclui os já vencidos: dias_para_vencer negativo)."""
    dias, e = _inteiro(7 if dias is None else dias, "dias", 0, 365)
    if e:
        return e
    sql = """
        SELECT p.nome AS produto, l.codigo_lote, l.validade, l.quantidade, p.unidade,
               CAST(julianday(l.validade) - julianday(date('now', 'localtime')) AS INTEGER) AS dias_para_vencer
          FROM lotes l JOIN produtos p ON p.id_produto = l.id_produto
         WHERE p.id_loja = ? AND l.quantidade > 0
           AND l.validade <= date('now', 'localtime', ?)
         ORDER BY l.validade ASC, p.nome"""
    linhas = _consultar(ctx, sql, (ctx.id_loja, f"+{dias} days"))
    for linha in linhas:
        linha["vencido"] = linha["dias_para_vencer"] < 0
    resultado = {"janela_dias": dias, "linhas": linhas}
    if not linhas:
        resultado["aviso"] = "Nenhum lote com saldo vence nessa janela."
    return resultado


# --- escrita ---------------------------------------------------------------

def _resolver_produto(ctx: Contexto, nome):
    """Casa o nome informado com um produto DESTA loja (ignora maiúsculas). Sem casar, sugere parecidos."""
    produtos = _consultar(
        ctx, "SELECT id_produto, nome, quantidade, estoque_minimo FROM produtos WHERE id_loja = ?",
        (ctx.id_loja,))
    alvo = str(nome or "").strip().casefold()
    for produto in produtos:
        if produto["nome"].casefold() == alvo:
            return produto, None
    por_nome = {p["nome"].casefold(): p["nome"] for p in produtos}
    sugestoes = [por_nome[n] for n in difflib.get_close_matches(alvo, list(por_nome), n=3, cutoff=0.5)]
    return None, erro(
        "produto_nao_encontrado", f"Não existe produto chamado {nome!r} nesta loja.",
        "Não escolha outro produto por conta própria: avise o Administrador e ofereça as sugestões. "
        "Para buscar por parte do nome use consultar_estoque(produto=...).",
        sugestoes=sugestoes)


def _preparar_alerta(ctx: Contexto, produto, tipo, mensagem, codigo_lote=None):
    """Regras de negócio da escrita (decide: CÓDIGO). Devolve (dados, None) ou (None, erro)."""
    if tipo not in TIPOS_ALERTA:
        return None, erro("argumento_invalido", f"tipo={tipo!r}.", f"Use um de: {', '.join(TIPOS_ALERTA)}.")
    mensagem = str(mensagem or "").strip()
    if not mensagem or len(mensagem) > 200:
        return None, erro("argumento_invalido", "mensagem vazia ou com mais de 200 caracteres.",
                          "Escreva uma frase curta (até 200 caracteres).")
    prod, e = _resolver_produto(ctx, produto)
    if e:
        return None, e

    id_lote = None
    if tipo == "validade":
        if not codigo_lote:
            return None, erro("argumento_invalido", "codigo_lote é obrigatório para tipo='validade'.",
                              "Use consultar_validade e copie o codigo_lote retornado.")
        lotes = _consultar(ctx, """
            SELECT id_lote, codigo_lote, quantidade,
                   CAST(julianday(validade) - julianday(date('now', 'localtime')) AS INTEGER) AS dias
              FROM lotes WHERE id_produto = ?""", (prod["id_produto"],))
        lote = next((l for l in lotes
                     if str(l["codigo_lote"]).casefold() == str(codigo_lote).strip().casefold()), None)
        if lote is None:
            return None, erro("lote_nao_encontrado",
                              f"O produto '{prod['nome']}' não tem o lote {codigo_lote!r}.",
                              "Use um dos lotes listados em lotes_do_produto.",
                              lotes_do_produto=[l["codigo_lote"] for l in lotes])
        if lote["quantidade"] <= 0:
            return None, erro("fora_da_regra", f"O lote {lote['codigo_lote']} não tem saldo.",
                              "Não registre; informe o Administrador.")
        if lote["dias"] > ctx.limite_dias_validade:
            return None, erro(
                "fora_da_regra",
                f"O lote {lote['codigo_lote']} vence em {lote['dias']} dias; alerta de validade só vale "
                f"para lotes que vencem em até {ctx.limite_dias_validade} dias (ou já vencidos).",
                "Não registre; explique ao Administrador.",
                dias_para_vencer=lote["dias"], limite_dias=ctx.limite_dias_validade)
        id_lote = lote["id_lote"]
    elif prod["quantidade"] > prod["estoque_minimo"]:
        return None, erro(
            "fora_da_regra",
            f"'{prod['nome']}' tem {prod['quantidade']:g} em estoque, acima do mínimo {prod['estoque_minimo']:g}.",
            "Não registre; explique ao Administrador.",
            quantidade=prod["quantidade"], estoque_minimo=prod["estoque_minimo"])

    aberto = ctx.conn.execute(
        """SELECT id_alerta FROM alertas_agente
            WHERE id_loja = ? AND id_produto = ? AND tipo = ? AND COALESCE(id_lote, 0) = COALESCE(?, 0)
              AND status = 'aberto'""", (ctx.id_loja, prod["id_produto"], tipo, id_lote)).fetchone()
    if aberto:
        return None, erro("alerta_duplicado", f"Já existe o alerta aberto #{aberto['id_alerta']}.",
                          "Não registre de novo; informe o número existente.", id_alerta=aberto["id_alerta"])
    return {"id_produto": prod["id_produto"], "nome": prod["nome"], "id_lote": id_lote,
            "tipo": tipo, "mensagem": mensagem}, None


def validar_alerta(ctx: Contexto, produto, tipo, mensagem, codigo_lote=None):
    return _preparar_alerta(ctx, produto, tipo, mensagem, codigo_lote)[1]


def descrever_alerta(ctx: Contexto, produto, tipo, mensagem, codigo_lote=None) -> str:
    dados, _ = _preparar_alerta(ctx, produto, tipo, mensagem, codigo_lote)
    nome = dados["nome"] if dados else produto
    lote = f" (lote {codigo_lote})" if codigo_lote else ""
    return f"Registrar alerta de {tipo} para '{nome}'{lote}: \"{str(mensagem).strip()}\""


def registrar_alerta(ctx: Contexto, produto, tipo, mensagem, codigo_lote=None) -> dict:
    """ESCRITA reversível: cria um alerta na fila do Administrador (descartar = status 'descartado')."""
    dados, e = _preparar_alerta(ctx, produto, tipo, mensagem, codigo_lote)  # valida de novo na hora de escrever
    if e:
        return e
    cur = ctx.conn.execute(
        """INSERT INTO alertas_agente (id_loja, id_produto, id_lote, tipo, mensagem, status, criado_em)
           VALUES (?, ?, ?, ?, ?, 'aberto', datetime('now', 'localtime'))""",
        (ctx.id_loja, dados["id_produto"], dados["id_lote"], dados["tipo"], dados["mensagem"]))
    ctx.conn.commit()
    return {"ok": True, "id_alerta": cur.lastrowid, "status": "aberto",
            "produto": dados["nome"], "tipo": dados["tipo"]}


# --- registro e schemas enviados ao modelo ---------------------------------

def _fn(nome: str, descricao: str, propriedades: dict, obrigatorios: tuple = ()) -> dict:
    # gpt-oss e outros modelos mandam null nos parametros opcionais: o schema precisa aceitar (null = usar o padrao)
    for chave, prop in propriedades.items():
        if chave not in obrigatorios:
            prop["type"] = [prop["type"], "null"]
            if "enum" in prop:
                prop["enum"] = [*prop["enum"], None]
    return {"type": "function", "function": {
        "name": nome, "description": descricao,
        "parameters": {"type": "object", "properties": propriedades, "required": list(obrigatorios)}}}


FERRAMENTAS: dict[str, Ferramenta] = {f.nome: f for f in (
    Ferramenta("consultar_vendas", consultar_vendas, _fn(
        "consultar_vendas",
        "Produtos ordenados por quantidade vendida nos últimos N dias. ordem='desc' = mais vendidos; "
        "ordem='asc' = menos vendidos / parados (total 0 = sem venda no período).",
        {"ordem": {"type": "string", "enum": ["asc", "desc"]},
         "limite": {"type": "integer", "description": "quantos produtos retornar (1 a 50)"},
         "dias": {"type": "integer", "description": "janela em dias (1 a 365)"}})),
    Ferramenta("consultar_estoque", consultar_estoque, _fn(
        "consultar_estoque",
        "Saldo de estoque. Com 'produto' (parte do nome) devolve os produtos que casam, com qualquer saldo. "
        "Sem parâmetros devolve os que estão no mínimo ou abaixo dele.",
        {"produto": {"type": "string", "description": "parte do nome do produto"},
         "limite_minimo": {"type": "number", "description": "lista produtos com saldo menor ou igual a este valor"}})),
    Ferramenta("consultar_validade", consultar_validade, _fn(
        "consultar_validade",
        "Lotes com saldo que vencem em até N dias, incluindo os já vencidos (dias_para_vencer negativo). "
        "Devolve o codigo_lote de cada lote.",
        {"dias": {"type": "integer", "description": "janela em dias (0 a 365)"}})),
    Ferramenta("registrar_alerta", registrar_alerta, _fn(
        "registrar_alerta",
        "ESCRITA reversível: registra um alerta na fila do Administrador. Não altera estoque, produtos nem "
        "vendas. Cada registro exige confirmação do Administrador. Use SOMENTE quando ele pedir explicitamente. "
        "Um alerta por lote (validade) ou por produto (estoque_baixo).",
        {"produto": {"type": "string", "description": "nome exato do produto, como retornado pelas consultas"},
         "tipo": {"type": "string", "enum": list(TIPOS_ALERTA)},
         "mensagem": {"type": "string", "description": "frase curta (até 200 caracteres)"},
         "codigo_lote": {"type": "string", "description": "obrigatório quando tipo='validade'"}},
        ("produto", "tipo", "mensagem")),
        escrita=True, reversivel=True, valida=validar_alerta, descreve=descrever_alerta),
)}

SCHEMAS = [f.schema for f in FERRAMENTAS.values()]
