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
| consultar_regras   | leitura         | -          | índice BM25 das RN/RF (src/rag.py) | Parte 2: RAG
| lembrar_fato       | ESCRITA         | sim        | SQLite (memoria_semantica)         | Parte 2: memória
"""
from __future__ import annotations

import difflib
import re
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
    memoria: bool = False                 # Parte 2: lê/grava memória de longo prazo (MEMORIA=on no .env)
    id_execucao: str | None = None        # Parte 2: chave do checkpoint
    chave_idempotencia: str | None = None # Parte 2: preenchida pelo grafo antes de cada escrita
    aprovado_por: str | None = None       # Parte 2: quem confirmou a escrita em curso


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
    via_apelido = None
    if produto and ctx.memoria:
        from .memoria import apelidos  # memória semântica: "o queijo" -> nome exato confirmado pelo Administrador
        alvo = apelidos(ctx.conn, ctx.id_loja).get(str(produto).strip().casefold())
        if alvo:
            via_apelido, produto = str(produto).strip(), alvo
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
    if via_apelido:
        resultado["via_apelido"] = f"'{via_apelido}' é apelido guardado na memória para '{produto}'"
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

def _resolver_produto(ctx: Contexto, nome, usar_apelidos: bool = True):
    """Casa o nome informado com um produto DESTA loja (ignora maiúsculas). Sem casar, tenta os apelidos
    confirmados na memória (Parte 2) e, por fim, sugere parecidos — sem nunca escolher sozinho."""
    produtos = _consultar(
        ctx, "SELECT id_produto, nome, quantidade, estoque_minimo FROM produtos WHERE id_loja = ?",
        (ctx.id_loja,))
    alvo = str(nome or "").strip().casefold()
    for produto in produtos:
        if produto["nome"].casefold() == alvo:
            return produto, None
    if usar_apelidos and ctx.memoria:
        from .memoria import apelidos
        nome_real = apelidos(ctx.conn, ctx.id_loja).get(alvo)
        for produto in produtos:
            if nome_real and produto["nome"] == nome_real:
                return produto, None
    por_nome = {p["nome"].casefold(): p["nome"] for p in produtos}
    sugestoes = [por_nome[n] for n in difflib.get_close_matches(alvo, list(por_nome), n=3, cutoff=0.5)]
    return None, erro(
        "produto_nao_encontrado", f"Não existe produto chamado {nome!r} nesta loja.",
        "Não escolha outro produto por conta própria: avise o Administrador e ofereça as sugestões. "
        "Para buscar por parte do nome use consultar_estoque(produto=...).",
        sugestoes=sugestoes)


# --- Controle 1 de segurança (ASI02 / ASI01): regex na mensagem ----------------
# Barra URLs, telefones celulares, CPFs e chaves PIX no campo livre 'mensagem'.
# Instrução no prompt de sistema não é controle: o texto injetado chega pelo mesmo canal.
# Teste: tests/test_seguranca.py::TestValidarMensagem

_RE_DADO_SUSPEITO = re.compile(
    r"https?://"                              # URL com esquema
    r"|www\.[a-z0-9-]{2,}"                   # URL sem esquema
    r"|\b\d{2}\s?9?\s?\d{4}[-\s]?\d{4}\b"   # telefone celular (DDD + número)
    r"|\d{3}\.\d{3}\.\d{3}-\d{2}"           # CPF
    r"|\bpix\b.*?\d{5,}"                      # menção a PIX seguida de número longo
    r"|\b[a-f0-9]{32,}\b",                   # hash longo (chave aleatória PIX)
    re.IGNORECASE,
)


def _validar_mensagem(mensagem: str) -> dict | None:
    """Controle 1 (ASI02/ASI01): barra URLs, telefones, CPFs e chaves PIX no campo livre 'mensagem'.
    Devolve None se a mensagem for segura, ou um dict de erro se não for.
    fail-closed: se esta função levantar exceção inesperada, _preparar_alerta captura e devolve erro."""
    if _RE_DADO_SUSPEITO.search(mensagem):
        return erro(
            "mensagem_invalida",
            "O campo 'mensagem' não pode conter URLs, telefones, CPFs nem chaves PIX.",
            "Remova o dado suspeito do campo 'mensagem' e use apenas uma descrição curta do alerta.",
        )
    return None


def _preparar_alerta(ctx: Contexto, produto, tipo, mensagem, codigo_lote=None):
    """Regras de negócio da escrita (decide: CÓDIGO). Devolve (dados, None) ou (None, erro)."""
    if tipo not in TIPOS_ALERTA:
        return None, erro("argumento_invalido", f"tipo={tipo!r}.", f"Use um de: {', '.join(TIPOS_ALERTA)}.")
    mensagem = str(mensagem or "").strip()
    if not mensagem or len(mensagem) > 200:
        return None, erro("argumento_invalido", "mensagem vazia ou com mais de 200 caracteres.",
                          "Escreva uma frase curta (até 200 caracteres).")
    # Controle 1: regex na mensagem (ASI02 / ASI01)
    e_msg = _validar_mensagem(mensagem)
    if e_msg:
        return None, e_msg
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
    if ctx.chave_idempotencia:  # Parte 2: a retomada de um checkpoint não reaplica uma escrita já feita
        feito = ctx.conn.execute("SELECT id_alerta, tipo FROM alertas_agente WHERE chave_idempotencia = ?",
                                 (ctx.chave_idempotencia,)).fetchone()
        if feito:
            return {"ok": True, "id_alerta": feito["id_alerta"], "status": "aberto", "idempotente": True,
                    "tipo": feito["tipo"], "nota": "esta escrita já tinha sido feita; nada foi duplicado"}
    dados, e = _preparar_alerta(ctx, produto, tipo, mensagem, codigo_lote)  # valida de novo na hora de escrever
    if e:
        return e
    cur = ctx.conn.execute(
        """INSERT INTO alertas_agente (id_loja, id_produto, id_lote, tipo, mensagem, status, criado_em,
                                       chave_idempotencia)
           VALUES (?, ?, ?, ?, ?, 'aberto', datetime('now', 'localtime'), ?)""",
        (ctx.id_loja, dados["id_produto"], dados["id_lote"], dados["tipo"], dados["mensagem"],
         ctx.chave_idempotencia))
    ctx.conn.commit()
    return {"ok": True, "id_alerta": cur.lastrowid, "status": "aberto",
            "produto": dados["nome"], "tipo": dados["tipo"]}


# --- Parte 2: RAG e memória --------------------------------------------------

def consultar_regras(ctx: Contexto, pergunta, tipo=None) -> dict:
    """RAG: trechos das regras de negócio (RN) e requisitos (RF) do Hydra que respondem à pergunta."""
    from .rag import buscar
    texto = str(pergunta or "").strip()
    if not texto:
        return erro("argumento_invalido", "pergunta vazia.", "Envie a pergunta do Administrador sobre a regra.")
    if tipo not in (None, "regra", "requisito"):
        return erro("argumento_invalido", f"tipo={tipo!r}.", "Use 'regra', 'requisito' ou omita.")
    trechos = buscar(texto[:300], tipo=tipo)
    resultado = {"consulta": texto[:300], "trechos": trechos}
    if not trechos:
        resultado["aviso"] = ("Nenhuma regra ou requisito da base responde a isso. Diga ao Administrador que a "
                              "documentação do Hydra não trata do assunto; não responda de memória.")
    return resultado


def validar_fato_ferramenta(ctx: Contexto, chave, valor):
    from .memoria import validar_fato
    return validar_fato(ctx, chave, valor)[1]


def descrever_fato(ctx: Contexto, chave, valor) -> str:
    from .memoria import validar_fato
    fato, _ = validar_fato(ctx, chave, valor)
    if not fato:
        return f"Guardar na memória: {chave} = {valor}"
    troca = f" (substitui o fato #{fato['substitui']})" if fato["substitui"] else ""
    return f"Guardar na memória da loja: {fato['chave']} = {fato['valor']}{troca}"


def lembrar_fato(ctx: Contexto, chave, valor) -> dict:
    """ESCRITA reversível na memória semântica. Só depois de validar (código) e confirmar (humano)."""
    from .memoria import gravar_fato, validar_fato
    fato, e = validar_fato(ctx, chave, valor)  # valida de novo na hora de escrever
    if e:
        return e
    id_fato = gravar_fato(ctx, fato["chave"], fato["valor"], ctx.aprovado_por or "desconhecido")
    return {"ok": True, "id_fato": id_fato, "chave": fato["chave"], "valor": fato["valor"],
            "substituiu": fato["substitui"]}


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
    Ferramenta("consultar_regras", consultar_regras, _fn(
        "consultar_regras",
        "Busca nas regras de negócio (RN01-RN29) e nos requisitos (RF01-RF24) do Hydra os trechos que respondem a "
        "uma pergunta sobre como o sistema funciona: permissões, prazos, formas de pagamento, o que o assistente "
        "pode fazer. Não serve para estoque, validade ou vendas (use as outras consultas).",
        {"pergunta": {"type": "string", "description": "a pergunta do Administrador, com os termos dele"},
         "tipo": {"type": "string", "enum": ["regra", "requisito"]}},
        ("pergunta",))),
    Ferramenta("lembrar_fato", lembrar_fato, _fn(
        "lembrar_fato",
        "ESCRITA reversível na memória da loja. Use SOMENTE quando o Administrador pedir para lembrar/guardar algo. "
        "Chaves aceitas: 'apelido:<como ele chama>' (valor = nome exato do produto), 'preferencia:janela_validade' "
        "(dias), 'fornecedor:<nome>:prazo_dias' (dias), 'produto:<nome>:descontinuado' (sim/nao). Não guarda "
        "saldo, validade nem vendas (vêm do banco) nem dado pessoal. Cada gravação exige confirmação.",
        {"chave": {"type": "string"}, "valor": {"type": "string"}},
        ("chave", "valor")),
        escrita=True, reversivel=True, valida=validar_fato_ferramenta, descreve=descrever_fato),
)}

SCHEMAS = [f.schema for f in FERRAMENTAS.values()]
