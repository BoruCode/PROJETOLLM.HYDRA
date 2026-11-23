"""Testes dos três controles de segurança implementados fora do prompt.

Controle 1 — Regex na mensagem (ASI02 / ASI01): src/ferramentas.py::_validar_mensagem
Controle 2 — SQLite somente leitura (ASI03):     src/db.py::conectar_leitura
Controle 3 — Lotes da resposta vieram de ferramenta (ASI09): src/verificar.py::verificar_lotes_na_resposta

Rodar: python -m unittest tests.test_seguranca -v
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.db import conectar_leitura, criar_banco
from src.ferramentas import _validar_mensagem
from src.verificar import verificar_lotes_na_resposta


# ===========================================================================
# Controle 1 — Regex na mensagem
# ===========================================================================

class TestValidarMensagem(unittest.TestCase):
    """Controle 1 (ASI02/ASI01): _validar_mensagem barra dados suspeitos no campo livre 'mensagem'."""

    # --- deve bloquear -------------------------------------------------------

    def test_pix_numero_longo(self):
        """Chave PIX com número longo → bloqueada."""
        resultado = _validar_mensagem("Pague no PIX: 11912345678")
        self.assertIsNotNone(resultado, "mensagem com número tipo PIX deve ser bloqueada")
        self.assertEqual(resultado["erro"], "mensagem_invalida")

    def test_url_https(self):
        """URL com https:// → bloqueada."""
        resultado = _validar_mensagem("Veja mais em https://fornecedor.com/boleto")
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["erro"], "mensagem_invalida")

    def test_url_www(self):
        """URL sem esquema mas com www. → bloqueada."""
        resultado = _validar_mensagem("Acesse www.boleto.com.br para pagar")
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["erro"], "mensagem_invalida")

    def test_cpf(self):
        """CPF no padrão 999.999.999-99 → bloqueado."""
        resultado = _validar_mensagem("Fornecedor CPF 123.456.789-09")
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["erro"], "mensagem_invalida")

    def test_telefone_celular(self):
        """Telefone celular com DDD → bloqueado."""
        resultado = _validar_mensagem("Ligar para 11 9 1234-5678")
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["erro"], "mensagem_invalida")

    # --- deve passar ---------------------------------------------------------

    def test_mensagem_normal(self):
        """Descrição simples de alerta → não bloqueada."""
        self.assertIsNone(_validar_mensagem("Lote vence em 2 dias"))

    def test_mensagem_com_numero_pequeno(self):
        """Número pequeno (quantidade) → não bloqueado."""
        self.assertIsNone(_validar_mensagem("Estoque abaixo do mínimo: 6 unidades"))

    def test_mensagem_vazia_nao_entra_aqui(self):
        """Mensagem vazia não chega ao regex (filtrada antes por _preparar_alerta)."""
        # _validar_mensagem recebe string já stripped; string vazia → nenhum padrão casa
        self.assertIsNone(_validar_mensagem(""))

    def test_mensagem_com_codigo_lote(self):
        """Código de lote (ex.: L-IOG-01) não é dado suspeito → passa."""
        self.assertIsNone(_validar_mensagem("Lote L-IOG-01 vence em 3 dias"))


# ===========================================================================
# Controle 2 — SQLite somente leitura
# ===========================================================================

class TestConectarLeitura(unittest.TestCase):
    """Controle 2 (ASI03): conectar_leitura abre SQLite em mode=ro; escritas levantam OperationalError."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.caminho = Path(self._tmp.name) / "test.db"
        criar_banco(self.caminho)

    def tearDown(self):
        self._tmp.cleanup()

    def test_leitura_funciona(self):
        """SELECT em conexão leitura deve funcionar normalmente."""
        conn = conectar_leitura(self.caminho)
        try:
            linhas = conn.execute("SELECT nome FROM produtos LIMIT 3").fetchall()
            self.assertGreater(len(linhas), 0, "deve devolver linhas do banco")
        finally:
            conn.close()

    def test_insert_bloqueado(self):
        """INSERT em conexão leitura deve levantar OperationalError (modo mode=ro)."""
        conn = conectar_leitura(self.caminho)
        try:
            with self.assertRaises(sqlite3.OperationalError,
                                   msg="INSERT em conexão leitura deve ser bloqueado"):
                conn.execute(
                    "INSERT INTO produtos (id_loja, nome, quantidade, estoque_minimo) "
                    "VALUES (1, 'Produto Falso', 10, 5)"
                )
        finally:
            conn.close()

    def test_update_bloqueado(self):
        """UPDATE em conexão leitura deve levantar OperationalError."""
        conn = conectar_leitura(self.caminho)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE produtos SET quantidade = 999 WHERE id_loja = 1")
        finally:
            conn.close()

    def test_delete_bloqueado(self):
        """DELETE em conexão leitura deve levantar OperationalError."""
        conn = conectar_leitura(self.caminho)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM produtos WHERE id_loja = 1")
        finally:
            conn.close()


# ===========================================================================
# Controle 3 — Lotes da resposta vieram de ferramenta
# ===========================================================================

class TestVerificarResposta(unittest.TestCase):
    """Controle 3 (ASI09): verificar_lotes_na_resposta detecta lotes inventados na resposta final."""

    def _chamadas(self, *resumos):
        """Cria lista de chamadas com os resumos de resultado fornecidos."""
        return [{"nome": "consultar_validade", "args": {}, "resumo_resultado": r} for r in resumos]

    # --- deve passar (lote tem fonte) ----------------------------------------

    def test_lote_veio_de_ferramenta(self):
        """L-IOG-01 aparece no resumo de ferramenta → sem fonte faltando."""
        chamadas = self._chamadas("3 linha(s) [L-IOG-01, L-PAO-01, L-PRE-01]")
        resposta = "O lote L-IOG-01 vence em 3 dias."
        self.assertEqual(verificar_lotes_na_resposta(resposta, chamadas), [])

    def test_varios_lotes_com_fonte(self):
        """Vários lotes na resposta, todos com fonte nas ferramentas."""
        chamadas = self._chamadas("3 linha(s) [L-IOG-01, L-PAO-01, L-PRE-01]")
        resposta = "Lotes vencendo: L-IOG-01, L-PAO-01 e L-PRE-01."
        self.assertEqual(verificar_lotes_na_resposta(resposta, chamadas), [])

    def test_sem_lotes_na_resposta(self):
        """Resposta sem código de lote → sempre passa."""
        resposta = "Nenhum lote vence nos próximos 7 dias."
        self.assertEqual(verificar_lotes_na_resposta(resposta, []), [])

    def test_lote_no_argumento_da_chamada(self):
        """Lote que aparece nos args da chamada (não só no resumo) é aceito."""
        chamadas = [{"nome": "registrar_alerta",
                     "args": {"codigo_lote": "L-QUE-01"},
                     "resumo_resultado": "alerta #5"}]
        resposta = "Alerta registrado para o lote L-QUE-01."
        self.assertEqual(verificar_lotes_na_resposta(resposta, chamadas), [])

    # --- deve detectar (lote sem fonte) --------------------------------------

    def test_lote_inventado(self):
        """L-INV-99 nunca apareceu nas ferramentas → detectado como sem fonte."""
        chamadas = self._chamadas("3 linha(s) [L-IOG-01, L-PAO-01]")
        resposta = "O lote L-INV-99 está vencendo."
        sem_fonte = verificar_lotes_na_resposta(resposta, chamadas)
        self.assertIn("L-INV-99", sem_fonte)

    def test_lote_de_outra_execucao(self):
        """Lote que poderia existir no banco mas não foi consultado nesta execução → detectado."""
        chamadas = self._chamadas("1 linha(s) [L-LEI-01]")
        resposta = "Consulte o lote L-ARR-01 que vence logo."
        sem_fonte = verificar_lotes_na_resposta(resposta, chamadas)
        self.assertIn("L-ARR-01", sem_fonte)

    def test_hifen_unicode_normalizado(self):
        """Hífen não separável (U+2011) usado pelo gpt-oss-120b é normalizado antes de comparar."""
        hifen_ns = "\u2011"
        chamadas = self._chamadas(f"1 linha(s) [L{hifen_ns}IOG{hifen_ns}01]")
        resposta = f"Lote L{hifen_ns}IOG{hifen_ns}01 vence amanhã."
        # Após normalização ambos viram L-IOG-01, então não há lote sem fonte
        self.assertEqual(verificar_lotes_na_resposta(resposta, chamadas), [])

    def test_resposta_none(self):
        """Resposta None (terminação sem texto) → retorna lista vazia."""
        self.assertEqual(verificar_lotes_na_resposta(None, []), [])


if __name__ == "__main__":
    unittest.main()
