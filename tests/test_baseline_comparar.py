"""Testes do cronômetro (src/baseline.py) e do comparador de modelos (src/comparar.py). Sem chamar API."""
import itertools
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from src import baseline, comparar
from src.agente import carregar_prompt
from src.config import RAIZ, Config
from tests.test_agente import ALERTA_IOGURTE, ALERTA_PAO, ALERTA_PRESUNTO, ClienteFalso, resposta

HOJE = date(2026, 9, 20)


class TestBaseline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_resumo_e_ganho(self):
        r = baseline.resumir([10, 20, 30, 40, 50])
        self.assertEqual((r["n"], r["mediana"], r["media"], r["minimo"], r["maximo"]), (5, 30, 30, 10, 50))
        self.assertAlmostEqual(baseline.ganho_percentual(120, 30), 75.0)
        self.assertLess(baseline.ganho_percentual(30, 60), 0)

    def test_csv_ida_e_volta(self):
        caminho = self.tmp / "b.csv"
        baseline.gravar_csv(caminho, {"hydra": [90.5, 80], "agente": [20]}, 12)
        tempos, volume = baseline.ler_csv(caminho)
        self.assertEqual(tempos, {"hydra": [90.5, 80.0], "agente": [20.0]})
        self.assertEqual(volume, 12)
        self.assertEqual(baseline.ler_csv(self.tmp / "nao_existe.csv"), ({"hydra": [], "agente": []}, None))

    def test_bloco_com_conta_e_denominador(self):
        bloco = baseline.gerar_bloco("tarefa X", {"hydra": [100, 120, 110], "agente": [20, 30, 25]}, 10, HOJE)
        self.assertIn("de 110 s para 25 s por consulta = 77% de ganho", bloco)
        self.assertIn("| **Mediana** | **110** | **25** |", bloco)
        self.assertIn("20/09/2026", bloco)
        self.assertIn("10 consultas por semana", bloco)
        self.assertIn("+0.24 h por semana", bloco)  # (110-25) s x 10 / 3600
        self.assertIn("Ressalva", bloco)

    def test_bloco_avisa_quando_o_agente_e_mais_lento(self):
        bloco = baseline.gerar_bloco("t", {"hydra": [10, 10], "agente": [30, 30]}, None, HOJE)
        self.assertIn("MAIS LENTO", bloco)
        self.assertIn("pendente", bloco)  # sem volume

    def test_bloco_pendente_sem_medicao(self):
        self.assertIn("Pendente", baseline.gerar_bloco("t", {"hydra": [], "agente": []}, None))

    def test_atualizar_case_troca_so_o_miolo(self):
        arq = self.tmp / "case.md"
        arq.write_text(f"antes\n{baseline.INICIO}\nvelho\n{baseline.FIM}\ndepois\n", encoding="utf-8")
        baseline.atualizar_case(arq, "NOVO")
        self.assertEqual(arq.read_text(encoding="utf-8"),
                         f"antes\n{baseline.INICIO}\nNOVO\n{baseline.FIM}\ndepois\n")

    def test_case_md_do_repositorio_tem_os_marcadores(self):
        texto = (RAIZ / "docs" / "case.md").read_text(encoding="utf-8")
        self.assertEqual(texto.count(baseline.INICIO), 1)
        self.assertEqual(texto.count(baseline.FIM), 1)

    def test_fluxo_interativo_descarta_e_grava(self):
        entradas = iter(["", "", "", "x"] + [""] * 6 + ["3"])  # 2 rodadas por caminho (1 descartada e refeita) + volume 3
        relogio = itertools.count(0, 5)  # cada leitura do relógio avança 5 s
        with mock.patch.object(baseline, "ARQUIVO_CSV", self.tmp / "b.csv"), \
                mock.patch.object(baseline, "ARQUIVO_CASE", self.tmp / "case.md"), \
                mock.patch("builtins.input", lambda *_: next(entradas)), \
                mock.patch("time.perf_counter", lambda: next(relogio)), \
                mock.patch("builtins.print"):
            (self.tmp / "case.md").write_text(f"{baseline.INICIO}\n{baseline.FIM}\n", encoding="utf-8")
            codigo = baseline.main(["--rodadas", "2"])
            tempos, volume = baseline.ler_csv(self.tmp / "b.csv")
        self.assertEqual(codigo, 0)
        self.assertEqual(len(tempos["hydra"]), 2)
        self.assertEqual(len(tempos["agente"]), 2)
        self.assertEqual(volume, 3)
        self.assertIn("A conta", (self.tmp / "case.md").read_text(encoding="utf-8"))


ROTEIRO_5_DE_5 = [
    resposta(chamadas=[("consultar_validade", {"dias": 3})]),
    resposta(chamadas=[ALERTA_IOGURTE, ALERTA_PAO, ALERTA_PRESUNTO]),
    resposta("Registrei 3 alertas.", entrada=1000, saida=200),
    resposta(chamadas=[("consultar_estoque", {"produto": "Leite Integral", "limite_minimo": None})]),
    resposta("Não. O Leite Integral 1L tem 6 un., abaixo do mínimo de 20.", entrada=1000, saida=100),
    resposta(chamadas=[("consultar_estoque", {"produto": "Queijo Prato Fatiado"})]),
    resposta("Não encontrei o Queijo Prato Fatiado.", entrada=1000, saida=100),
    resposta(chamadas=[("registrar_alerta", {"produto": "Arroz Tipo 1 5kg", "tipo": "validade", "mensagem": "x",
                                             "codigo_lote": "L-ARR-01"})]),
    resposta("Não registrei: o lote vence em 200 dias.", entrada=1000, saida=100),
    resposta("Não posso alterar estoque; faça pela tela de estoque.", entrada=1000, saida=100),
]


class TestComparar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cfg = Config(caminho_db=self.tmp / "c.db", pasta_logs=self.tmp / "logs")
        self.prompt = carregar_prompt(RAIZ / "prompts" / "sistema_v2.md")
        self.casos = json.loads((RAIZ / "dados" / "casos.json").read_text(encoding="utf-8"))
        self.candidatos = json.loads((RAIZ / "dados" / "candidatos.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def rodar(self, ambiente, roteiros, pausa=0):
        fila = iter(roteiros)
        esperas = []
        with mock.patch("builtins.print"):
            resultados = comparar.comparar(self.candidatos, self.casos, self.cfg, self.prompt, self.tmp / "logs",
                                           pausa=pausa, dormir=esperas.append, ambiente=ambiente,
                                           criar=lambda cfg: ClienteFalso(next(fila)))
        return resultados, esperas

    def test_tres_candidatos_um_perfeito_um_com_erro_de_provedor_um_sem_chave(self):
        ambiente = {"GROQ_API_KEY": "x"}  # sem MISTRAL_API_KEY
        erro_429 = [RuntimeError("429 rate limit")] * 5
        resultados, _ = self.rodar(ambiente, [ROTEIRO_5_DE_5, erro_429])
        self.assertEqual([r["medido"] for r in resultados], [True, True, False])
        perfeito, com_erro, sem_chave = resultados
        s1, s2 = comparar.resumir_candidato(perfeito), comparar.resumir_candidato(com_erro)
        self.assertEqual((s1["passaram"], s1["total"], s1["erros_llm"]), (5, 5, 0))
        self.assertEqual((s2["passaram"], s2["erros_llm"], s2["medias"]), (0, 5, None))
        self.assertIn("MISTRAL_API_KEY", sem_chave["motivo"])

    def test_custo_e_medias(self):
        resultados, _ = self.rodar({"GROQ_API_KEY": "x"}, [ROTEIRO_5_DE_5, ROTEIRO_5_DE_5])
        s = comparar.resumir_candidato(resultados[0])
        m = s["medias"]
        # 12 chamadas de 100+20 tokens e 5 respostas finais (1000/200 ou 1000/100), somadas por caso e divididas por 5
        esperado = comparar.custo_usd(m["tokens_entrada"], m["tokens_saida"], 0.15, 0.60)
        self.assertAlmostEqual(m["custo"], esperado)
        self.assertAlmostEqual(m["custo_100"], m["custo"] * 100)
        self.assertAlmostEqual(m["custo_semestre"], m["custo"] * comparar.EXECUCOES_SEMESTRE)
        # o gpt-oss-20b custa metade do 120b nos mesmos tokens
        s20 = comparar.resumir_candidato(resultados[1])["medias"]
        self.assertAlmostEqual(s20["custo"], m["custo"] / 2)

    def test_pausa_entre_todos_os_casos_menos_o_primeiro(self):
        _, esperas = self.rodar({"GROQ_API_KEY": "x"}, [ROTEIRO_5_DE_5, ROTEIRO_5_DE_5], pausa=7)
        self.assertEqual(esperas, [7] * 9)  # 2 candidatos x 5 casos - 1

    def test_markdown_e_atualizacao_do_modelos_md(self):
        resultados, _ = self.rodar({"GROQ_API_KEY": "x"}, [ROTEIRO_5_DE_5, [RuntimeError("429")] * 5])
        bloco = comparar.gerar_markdown(resultados, self.casos, self.prompt, HOJE)
        self.assertIn("**5 de 5**", bloco)
        self.assertIn("**0 de 5** (5 com erro do provedor)", bloco)
        self.assertIn("**não medido** (sem MISTRAL_API_KEY no .env)", bloco)
        self.assertIn("Custo por 100 execuções", bloco)
        self.assertIn("sem resposta do provedor", bloco)
        arq = self.tmp / "modelos.md"
        arq.write_text(f"a\n{comparar.INICIO}\nvelho\n{comparar.FIM}\nb\n", encoding="utf-8")
        comparar.atualizar_modelos(arq, bloco)
        texto = arq.read_text(encoding="utf-8")
        self.assertTrue(texto.startswith("a\n") and texto.endswith("\nb\n"))
        self.assertNotIn("velho", texto)

    def test_modelos_md_do_repositorio_tem_os_marcadores(self):
        texto = (RAIZ / "docs" / "modelos.md").read_text(encoding="utf-8")
        self.assertEqual(texto.count(comparar.INICIO), 1)
        self.assertEqual(texto.count(comparar.FIM), 1)

    def test_candidatos_json_bem_formado(self):
        for cand in self.candidatos:
            for chave in ("id", "nome", "base_url", "modelo", "chave_env", "preco_entrada_por_milhao",
                          "preco_saida_por_milhao"):
                self.assertIn(chave, cand)
        self.assertEqual(len({c["id"] for c in self.candidatos}), len(self.candidatos))


if __name__ == "__main__":
    unittest.main()
