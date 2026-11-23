import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import pymysql
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, origins=[os.environ.get("CORS_ALLOWED_ORIGIN", "*")])

client = OpenAI(
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ["OPENAI_API_KEY"],
)


def get_db():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASS"],
        database=os.environ["DB_NAME"],
        port=int(os.environ.get("DB_PORT", 3306)),
        cursorclass=pymysql.cursors.DictCursor,
    )


# --- Ferramentas de leitura ---------------------------------------------
# Tabelas do schema.sql do Hydra.Back: produtos, lotes, vendas, itens_venda.
# Toda consulta é filtrada por ID_LOJA (uma instância do agente atende uma
# loja) e usa apenas parâmetros %s — nunca concatena valores no SQL.
ID_LOJA = int(os.environ.get("ID_LOJA", 1))


def consultar_vendas(ordem="desc", limite=5, dias=30):
    """Lista produtos por quantidade vendida num período.
    ordem='desc' -> mais vendidos; ordem='asc' -> parados/sem saída
    (produtos sem nenhuma venda no período aparecem com total 0)."""
    direcao = "ASC" if ordem == "asc" else "DESC"
    sql = f"""
        SELECT p.nome, COALESCE(SUM(iv.quantidade), 0) AS total_vendido
        FROM produtos p
        LEFT JOIN itens_venda iv ON iv.id_produto = p.id_produto
        LEFT JOIN vendas v ON v.id_venda = iv.id_venda
             AND v.data_venda >= NOW() - INTERVAL %s DAY
        WHERE p.id_loja = %s
        GROUP BY p.id_produto, p.nome
        ORDER BY total_vendido {direcao}, p.nome
        LIMIT %s
    """
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(sql, (dias, ID_LOJA, limite))
        return cur.fetchall()


def consultar_estoque(limite_minimo=None):
    """Lista produtos com estoque igual ou abaixo do limite informado.
    Sem limite, usa o estoque mínimo cadastrado em cada produto."""
    if limite_minimo is None:
        sql = """
            SELECT nome, quantidade, estoque_minimo, unidade
            FROM produtos
            WHERE id_loja = %s AND quantidade <= estoque_minimo
            ORDER BY quantidade ASC
        """
        params = (ID_LOJA,)
    else:
        sql = """
            SELECT nome, quantidade, estoque_minimo, unidade
            FROM produtos
            WHERE id_loja = %s AND quantidade <= %s
            ORDER BY quantidade ASC
        """
        params = (ID_LOJA, limite_minimo)
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def consultar_validade(dias=7):
    """Lista lotes que vencem dentro de N dias (inclui já vencidos)."""
    sql = """
        SELECT p.nome, l.codigo_lote, l.validade, l.quantidade,
               DATEDIFF(l.validade, CURDATE()) AS dias_para_vencer
        FROM lotes l
        JOIN produtos p ON p.id_produto = l.id_produto
        WHERE p.id_loja = %s
          AND l.quantidade > 0
          AND l.validade <= CURDATE() + INTERVAL %s DAY
        ORDER BY l.validade ASC
    """
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(sql, (ID_LOJA, dias))
        return cur.fetchall()


FERRAMENTAS = {
    "consultar_vendas": consultar_vendas,
    "consultar_estoque": consultar_estoque,
    "consultar_validade": consultar_validade,
}

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "consultar_vendas",
            "description": (
                "Retorna produtos ordenados por quantidade vendida num "
                "período. Use ordem='desc' para 'mais vendidos' e "
                "ordem='asc' para 'parados/sem saída'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ordem": {"type": "string", "enum": ["asc", "desc"]},
                    "limite": {"type": "integer", "description": "quantos produtos retornar"},
                    "dias": {"type": "integer", "description": "janela de dias a considerar"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_estoque",
            "description": (
                "Retorna produtos com estoque igual ou abaixo do limite informado. "
                "Sem limite_minimo, usa o estoque mínimo de cada produto."
            ),
            "parameters": {
                "type": "object",
                "properties": {"limite_minimo": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_validade",
            "description": "Retorna lotes que vencem (ou já venceram) dentro de N dias.",
            "parameters": {
                "type": "object",
                "properties": {"dias": {"type": "integer"}},
            },
        },
    },
]

SYSTEM_PROMPT = (
    "Você é o assistente de estoque da loja. Responda de forma curta e "
    "resumida, em português, com base apenas nos dados retornados pelas "
    "ferramentas. Nunca invente números. Se a pergunta pedir uma ação de "
    "escrita (descontar, pedir reposição), explique que ainda não pode "
    "executar isso — só informar."
)


@app.route("/chat", methods=["POST"])
def chat():
    body = request.get_json(force=True)
    mensagem = body.get("mensagem", "")
    historico = body.get("historico", [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += historico
    messages.append({"role": "user", "content": mensagem})

    resposta = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        messages=messages,
        tools=TOOLS_SCHEMA,
    )
    msg = resposta.choices[0].message

    # laço simples: enquanto o modelo pedir ferramenta, executa e devolve
    while msg.tool_calls:
        messages.append(msg)
        for call in msg.tool_calls:
            nome = call.function.name
            args = json.loads(call.function.arguments or "{}")
            try:
                resultado = FERRAMENTAS[nome](**args)
            except Exception as e:
                resultado = {"erro": str(e)}
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(resultado, default=str),
            })
        resposta = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            messages=messages,
            tools=TOOLS_SCHEMA,
        )
        msg = resposta.choices[0].message

    return jsonify({"resposta": msg.content})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8082))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
