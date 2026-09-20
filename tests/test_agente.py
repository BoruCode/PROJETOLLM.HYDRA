"""Testes SEM chamar API: um modelo falso devolve respostas roteirizadas.

Isto testa o código (ferramentas, laço, orçamento, confirmação, verificador), não a qualidade do modelo.
A qualidade do modelo é medida pela demonstração (python -m src.avaliar) e por docs/modelos.md.

Rodar:  python -m unittest -v
"""
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src import avaliar
from src.agente import Trajetoria, carregar_prompt, executar
from src.config import RAIZ, Config
from src.db import conectar, criar_banco
from src.ferramentas import (Contexto, consultar_estoque, consultar_validade, consultar_vendas,
                             registrar_alerta)


# --- modelo falso ---------------------------------------------------------

def resposta(texto=None, chamadas=(), entrada=100, saida=20):
    """chamadas: [(nome, argumentos_dict_ou_string_crua)]"""
    tool_calls = [SimpleNamespace(id=f"c{i}", type="function", function=SimpleNamespace(
        name=nome, arguments=args if isinstance(args, str) else json.dumps(args)))
        for i, (nome, args) in enumerate(chamadas)]
    msg = SimpleNamespace(content=texto, tool_calls=tool_calls or None)
    uso = None if entrada is None else SimpleNamespace(prompt_tokens=entrada, completion_tokens=saida)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=uso)


class ClienteFalso:
    def __init__(self, respostas):
        self._respostas = iter(respostas)
        self.pedidos = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._criar))

    def _criar(self, **kwargs):
        self.pedidos.append({**kwargs, "messages": list(kwargs["messages"])})
        item = next(self._respostas)
        if isinstance(item, Exception):
            raise item
        return item


ALERTA_IOGURTE = ("registrar_alerta", {"produto": "Iogurte Natural 170g", "tipo": "validade",
                                       "mensagem": "Vence em 3 dias", "codigo_lote": "L-IOG-01"})
ALERTA_PAO = ("registrar_alerta", {"produto": "Pão de Forma 500g", "tipo": "validade",
                                   "mensagem": "Vence em 2 dias", "codigo_lote": "L-PAO-01"})
ALERTA_PRESUNTO = ("registrar_alerta", {"produto": "Presunto Fatiado", "tipo": "validade",
                                        "mensagem": "Já vencido", "codigo_lote": "L-PRE-01"})


class BaseComBanco(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.caminho_db = criar_banco(self.tmp / "teste.db")
        self.conn = conectar(self.caminho_db)
        self.ctx = Contexto(self.conn, id_loja=1, limite_dias_validade=30)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def total_alertas(self):
        return self.conn.execute("SELECT COUNT(*) FROM alertas_agente").fetchone()[0]


class TestFerramentas(BaseComBanco):
    def test_vendas_respeita_a_janela_de_dias(self):
        # Sem o CASE no SQL, o Leite somaria também as vendas de 45 e 60 dias atrás (110 em vez de 60).
        topo = consultar_vendas(self.ctx, "desc", 3, 30)["linhas"]
        self.assertEqual([(l["nome"], l["total_vendido"]) for l in topo],
                         [("Leite Integral 1L", 60), ("Pão de Forma 500g", 28), ("Arroz Tipo 1 5kg", 25)])

    def test_vendas_parados_no_periodo(self):
        parado = consultar_vendas(self.ctx, "asc", 1, 30)["linhas"][0]
        self.assertEqual((parado["nome"], parado["total_vendido"]), ("Sabão em Pó 1kg", 0))

    def test_vendas_argumento_invalido_vira_dado(self):
        self.assertEqual(consultar_vendas(self.ctx, "sideways")["erro"], "argumento_invalido")
        self.assertEqual(consultar_vendas(self.ctx, "desc", 5, 9999)["erro"], "argumento_invalido")

    def test_estoque_nao_vaza_dados_da_outra_loja(self):
        linhas = consultar_estoque(self.ctx, produto="Leite")["linhas"]
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["quantidade"], 6)  # a loja 2 tem 500
        self.assertTrue(linhas[0]["abaixo_do_minimo"])

    def test_estoque_padrao_lista_abaixo_do_minimo(self):
        nomes = {l["nome"] for l in consultar_estoque(self.ctx)["linhas"]}
        self.assertEqual(nomes, {"Feijão Carioca 1kg", "Leite Integral 1L"})

    def test_estoque_busca_sem_resultado_avisa(self):
        self.assertIn("aviso", consultar_estoque(self.ctx, produto="Queijo Prato"))

    def test_estoque_like_trata_percentual_como_texto(self):
        self.assertEqual(consultar_estoque(self.ctx, produto="%")["linhas"], [])

    def test_validade_em_3_dias_inclui_vencido(self):
        linhas = consultar_validade(self.ctx, 3)["linhas"]
        self.assertEqual([l["codigo_lote"] for l in linhas], ["L-PRE-01", "L-PAO-01", "L-IOG-01"])
        self.assertTrue(linhas[0]["vencido"])
        self.assertEqual([l["dias_para_vencer"] for l in linhas], [-1, 2, 3])

    def test_registrar_alerta_ok_e_duplicado(self):
        args = dict(produto="iogurte natural 170g", tipo="validade", mensagem="x", codigo_lote="l-iog-01")
        primeiro = registrar_alerta(self.ctx, **args)
        self.assertTrue(primeiro["ok"])
        self.assertEqual(registrar_alerta(self.ctx, **args)["erro"], "alerta_duplicado")
        self.assertEqual(self.total_alertas(), 1)

    def test_registrar_alerta_produto_inexistente_sugere(self):
        r = registrar_alerta(self.ctx, "Queijo Prato Fatiado", "validade", "x", "L-QUE-01")
        self.assertEqual(r["erro"], "produto_nao_encontrado")
        self.assertIn("Queijo Mussarela Fatiado", r["sugestoes"])
        self.assertEqual(self.total_alertas(), 0)

    def test_registrar_alerta_fora_da_janela_e_barrado_pelo_codigo(self):
        r = registrar_alerta(self.ctx, "Arroz Tipo 1 5kg", "validade", "x", "L-ARR-01")
        self.assertEqual(r["erro"], "fora_da_regra")
        self.assertEqual(r["dias_para_vencer"], 200)
        self.assertEqual(self.total_alertas(), 0)

    def test_registrar_alerta_lote_errado_lista_os_do_produto(self):
        r = registrar_alerta(self.ctx, "Pão de Forma 500g", "validade", "x", "L-XXX")
        self.assertEqual(r["erro"], "lote_nao_encontrado")
        self.assertEqual(set(r["lotes_do_produto"]), {"L-PAO-01", "L-PAO-02"})

    def test_registrar_alerta_estoque_baixo_so_se_abaixo_do_minimo(self):
        self.assertEqual(registrar_alerta(self.ctx, "Arroz Tipo 1 5kg", "estoque_baixo", "x")["erro"], "fora_da_regra")
        self.assertTrue(registrar_alerta(self.ctx, "Leite Integral 1L", "estoque_baixo", "x")["ok"])

    def test_registrar_alerta_nao_mexe_no_estoque(self):
        antes = self.conn.execute("SELECT SUM(quantidade) FROM produtos").fetchone()[0]
        registrar_alerta(self.ctx, "Leite Integral 1L", "estoque_baixo", "x")
        self.assertEqual(self.conn.execute("SELECT SUM(quantidade) FROM produtos").fetchone()[0], antes)


class TestPrompt(unittest.TestCase):
    def test_prompt_carimbado(self):
        prompt = carregar_prompt(RAIZ / "prompts" / "sistema_v1.md")
        self.assertEqual(prompt["versao"], "1")
        self.assertEqual(len(prompt["sha"]), 8)
        self.assertNotIn("---", prompt["texto"].splitlines()[0])
        self.assertIn("REGRAS", prompt["texto"])


class TestAgente(BaseComBanco):
    def cfg(self, **kw):
        return Config(base_url="http://falso", api_key="x", modelo="modelo-falso", caminho_db=self.caminho_db, **kw)

    def rodar(self, respostas, confirmar=None, cfg=None, log=None, historico=()):
        cliente = ClienteFalso(respostas)
        estado = executar("pergunta", cliente=cliente, cfg=cfg or self.cfg(), ctx=self.ctx,
                          prompt=carregar_prompt(RAIZ / "prompts" / "sistema_v1.md"),
                          confirmar=confirmar or (lambda d: (True, "teste")),
                          traj=Trajetoria(log, verboso=False), historico=historico)
        return estado, cliente

    def mensagens_de_ferramenta(self, cliente):
        return [json.loads(m["content"]) for m in cliente.pedidos[-1]["messages"] if m["role"] == "tool"]

    def test_fluxo_completo_com_tres_escritas(self):
        estado, cliente = self.rodar([
            resposta(chamadas=[("consultar_validade", {"dias": 3})]),
            resposta(chamadas=[ALERTA_IOGURTE, ALERTA_PAO, ALERTA_PRESUNTO]),
            resposta("Registrei 3 alertas."),
        ])
        self.assertEqual(estado.terminacao, "resposta_final")
        self.assertEqual(estado.passo, 3)
        self.assertEqual(len(estado.escritas), 3)
        self.assertEqual(self.total_alertas(), 3)
        self.assertEqual(estado.tokens, 3 * 120)
        # o resultado de cada ferramenta voltou para o modelo na chamada seguinte
        self.assertEqual(len(self.mensagens_de_ferramenta(cliente)), 4)

    def test_verificador_aprova_o_gabarito_do_caso_01(self):
        estado, _ = self.rodar([resposta(chamadas=[("consultar_validade", {"dias": 3})]),
                                resposta(chamadas=[ALERTA_IOGURTE, ALERTA_PAO, ALERTA_PRESUNTO]),
                                resposta("Registrei 3 alertas.")])
        casos = json.loads(avaliar.ARQUIVO_CASOS.read_text(encoding="utf-8"))
        regras = next(c for c in casos if c["id"] == "01_simples")["verificador"]
        self.assertTrue(all(ok for _, ok in avaliar.verificar(regras, estado, self.conn)))

    def test_verificador_reprova_quando_falta_um_alerta(self):
        estado, _ = self.rodar([resposta(chamadas=[("consultar_validade", {"dias": 3})]),
                                resposta(chamadas=[ALERTA_IOGURTE, ALERTA_PAO]),
                                resposta("Registrei 2 alertas.")])
        casos = json.loads(avaliar.ARQUIVO_CASOS.read_text(encoding="utf-8"))
        regras = next(c for c in casos if c["id"] == "01_simples")["verificador"]
        self.assertFalse(all(ok for _, ok in avaliar.verificar(regras, estado, self.conn)))

    def test_verificador_reprova_alerta_indevido_no_caso_de_divergencia(self):
        estado, _ = self.rodar([resposta(chamadas=[ALERTA_IOGURTE]), resposta("Feito, o leite tem 6.")])
        casos = json.loads(avaliar.ARQUIVO_CASOS.read_text(encoding="utf-8"))
        regras = next(c for c in casos if c["id"] == "02_divergencia")["verificador"]
        resultado = dict((d, ok) for d, ok in avaliar.verificar(regras, estado, self.conn))
        self.assertFalse(all(resultado.values()))

    def test_confirmacao_recusada_nao_escreve(self):
        estado, cliente = self.rodar([resposta(chamadas=[ALERTA_IOGURTE]), resposta("Nada foi registrado.")],
                                     confirmar=lambda d: (False, "teste"))
        self.assertEqual(self.total_alertas(), 0)
        self.assertEqual(estado.escritas, [])
        self.assertEqual(self.mensagens_de_ferramenta(cliente)[0]["erro"], "nao_confirmado")

    def test_regra_violada_nao_chega_a_pedir_confirmacao(self):
        pedidos = []
        estado, cliente = self.rodar(
            [resposta(chamadas=[("registrar_alerta", {"produto": "Arroz Tipo 1 5kg", "tipo": "validade",
                                                      "mensagem": "x", "codigo_lote": "L-ARR-01"})]),
             resposta("Não registrei: o lote vence em 200 dias.")],
            confirmar=lambda d: pedidos.append(d) or (True, "teste"))
        self.assertEqual(pedidos, [])
        self.assertEqual(self.mensagens_de_ferramenta(cliente)[0]["erro"], "fora_da_regra")
        self.assertEqual(self.total_alertas(), 0)

    def test_erro_de_ferramenta_vira_dado_e_o_laco_continua(self):
        estado, cliente = self.rodar([
            resposta(chamadas=[("registrar_alerta", {"produto": "Queijo Prato Fatiado", "tipo": "validade",
                                                     "mensagem": "x", "codigo_lote": "L-QUE-01"})]),
            resposta("Não encontrei esse produto. Você quis dizer Queijo Mussarela Fatiado?"),
        ])
        self.assertEqual(estado.terminacao, "resposta_final")
        self.assertEqual(estado.erros_de_ferramenta, ["produto_nao_encontrado"])
        self.assertIn("Queijo Mussarela Fatiado", self.mensagens_de_ferramenta(cliente)[0]["sugestoes"])

    def test_argumentos_que_nao_sao_json_viram_dado(self):
        estado, cliente = self.rodar([resposta(chamadas=[("consultar_estoque", "{isto nao e json")]),
                                      resposta("ok")])
        self.assertEqual(self.mensagens_de_ferramenta(cliente)[0]["erro"], "argumentos_invalidos")

    def test_argumento_faltando_ou_sobrando_vira_dado(self):
        estado, cliente = self.rodar([
            resposta(chamadas=[("registrar_alerta", {"produto": "Leite Integral 1L"}),
                               ("consultar_estoque", {"cor": "azul"})]),
            resposta("ok")])
        self.assertEqual([m["erro"] for m in self.mensagens_de_ferramenta(cliente)],
                         ["argumentos_invalidos", "argumentos_invalidos"])

    def test_ferramenta_inexistente_vira_dado(self):
        estado, cliente = self.rodar([resposta(chamadas=[("apagar_estoque", {})]), resposta("Não posso.")])
        self.assertEqual(self.mensagens_de_ferramenta(cliente)[0]["erro"], "ferramenta_desconhecida")

    def test_orcamento_de_passos(self):
        infinito = itertools.repeat(resposta(chamadas=[("consultar_estoque", {})]))
        estado, cliente = self.rodar(infinito, cfg=self.cfg(max_passos=3))
        self.assertEqual(estado.terminacao, "orcamento_passos")
        self.assertEqual((estado.passo, len(cliente.pedidos)), (3, 3))
        self.assertIsNone(estado.resposta)

    def test_orcamento_de_tokens(self):
        infinito = itertools.repeat(resposta(chamadas=[("consultar_estoque", {})], entrada=6000, saida=20))
        estado, _ = self.rodar(infinito, cfg=self.cfg(max_tokens=10_000))
        self.assertEqual((estado.terminacao, estado.passo), ("orcamento_tokens", 2))

    def test_orcamento_de_custo_so_vale_com_precos(self):
        cara = lambda: itertools.repeat(resposta(chamadas=[("consultar_estoque", {})], entrada=1_000_000, saida=0))
        com_preco, _ = self.rodar(cara(), cfg=self.cfg(preco_entrada_por_milhao=1.0, preco_saida_por_milhao=2.0,
                                                       max_custo_usd=0.5, max_passos=5, max_tokens=10**9))
        self.assertEqual(com_preco.terminacao, "orcamento_custo")
        self.assertAlmostEqual(com_preco.custo_usd, 1.0)
        sem_preco, _ = self.rodar(cara(), cfg=self.cfg(max_passos=2, max_tokens=10**9))
        self.assertEqual(sem_preco.terminacao, "orcamento_passos")
        self.assertIsNone(sem_preco.custo_usd)

    def test_erro_do_provedor_nao_derruba_o_programa(self):
        estado, _ = self.rodar([RuntimeError("401 chave inválida")])
        self.assertEqual(estado.terminacao, "erro_llm")
        self.assertIn("chave inválida", estado.erro_llm)

    def test_provedor_sem_usage_e_sinalizado(self):
        estado, _ = self.rodar([resposta("oi", entrada=None)])
        self.assertTrue(estado.usage_ausente)
        self.assertEqual(estado.terminacao, "resposta_final")

    def test_resposta_vazia_nao_conta_como_final(self):
        estado, _ = self.rodar([resposta("   ")])
        self.assertEqual(estado.terminacao, "resposta_vazia")

    def test_temperature_none_nao_e_enviada(self):
        _, cliente = self.rodar([resposta("oi")], cfg=self.cfg(temperature=None))
        self.assertNotIn("temperature", cliente.pedidos[0])
        _, cliente = self.rodar([resposta("oi")], cfg=self.cfg(temperature=0.0))
        self.assertEqual(cliente.pedidos[0]["temperature"], 0.0)

    def test_historico_entra_entre_o_prompt_e_a_pergunta(self):
        hist = [{"role": "user", "content": "antes"}, {"role": "assistant", "content": "resposta antes"}]
        _, cliente = self.rodar([resposta("oi")], historico=hist)
        papeis = [m["role"] for m in cliente.pedidos[0]["messages"]]
        self.assertEqual(papeis, ["system", "user", "assistant", "user"])

    def test_log_da_trajetoria(self):
        log = self.tmp / "logs" / "t.jsonl"
        self.rodar([resposta(chamadas=[ALERTA_IOGURTE]), resposta("ok")], log=log)
        eventos = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["evento"] for e in eventos], ["inicio", "passo", "ferramenta", "passo", "fim"])
        inicio, ferramenta, fim = eventos[0], eventos[2], eventos[-1]
        self.assertEqual(inicio["prompt"]["arquivo"], "sistema_v1.md")
        self.assertEqual((inicio["modelo"], inicio["temperature"]), ("modelo-falso", 0.0))
        self.assertTrue(ferramenta["escrita"] and ferramenta["reversivel"])
        self.assertEqual(ferramenta["confirmacao"], {"aprovado": True, "por": "teste"})
        self.assertEqual(ferramenta["argumentos"]["codigo_lote"], "L-IOG-01")
        self.assertEqual(fim["terminacao"], "resposta_final")
        self.assertEqual(fim["alertas_registrados"], [1])

    def test_executar_caso_de_ponta_a_ponta_com_banco_recriado(self):
        casos = json.loads(avaliar.ARQUIVO_CASOS.read_text(encoding="utf-8"))
        caso = next(c for c in casos if c["id"] == "02_divergencia")
        cliente = ClienteFalso([resposta(chamadas=[("consultar_estoque", {"produto": "Leite Integral"})]),
                                resposta("Não: o Leite Integral 1L tem 6 un., abaixo do mínimo de 20.")])
        r = avaliar.executar_caso(caso, cliente=cliente, cfg=self.cfg(),
                                  prompt=carregar_prompt(RAIZ / "prompts" / "sistema_v1.md"),
                                  pasta_logs=self.tmp / "logs")
        self.assertTrue(r["passou"], r["checagens"])
        self.assertTrue((self.tmp / "logs" / "02_divergencia.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
