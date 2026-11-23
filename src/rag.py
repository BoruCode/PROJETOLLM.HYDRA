"""RAG: busca nas regras de negócio (RN) e nos requisitos (RF) do Hydra.

Por que BM25 (busca lexical) e não embeddings, ao contrário do que o rascunho do Exercício 6 previa:
  - o provedor escolhido em docs/modelos.md (Groq) não tem endpoint de embeddings; usar embeddings
    exigiria um segundo provedor, uma segunda chave e mais um ponto de falha;
  - o corpus tem 53 trechos curtos, com identificadores e termos do domínio ("estoque mínimo",
    "código de recuperação", "Administrador"): a sobreposição de termos já separa bem os trechos;
  - BM25 é determinístico e roda sem rede: a avaliação do recall não depende de serviço externo.
O custo da escolha (docs/rag.md): sinônimo sem termo em comum ("senha esquecida" x "recuperação")
recupera pior. A normalização abaixo (acento, caixa, sufixos comuns) reduz, não elimina.

Corpus: dados/corpus/base_v1.jsonl, um trecho por linha: {id, tipo, titulo, texto, estado, fonte}.
Chunking: 1 regra = 1 trecho; 1 requisito = 1 trecho (estrutura natural do documento, Exercício 6 §4).
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .config import RAIZ

CORPUS_PADRAO = RAIZ / "dados" / "corpus" / "base_v1.jsonl"
K = 3                      # trechos devolvidos (Exercício 8 §1.2: 3 trechos cabem no teto de 1.500 tokens)
MAX_CARACTERES = 1500      # por trecho
SCORE_MINIMO = 3.6       # calibrado em dados/perguntas_rag.json: menor acerto 3,86; maior ruído 3,36 (docs/rag.md)

_STOP = set("""a o e é de da do das dos em no na nos nas um uma uns umas para por com sem que se ao aos à às
ou como qual quais quem quando onde pode podem posso deve devem ser ter tem mais menos muito pelo pela
isso este esta esse essa meu minha seu sua sistema hydra""".split())


def normalizar(texto: str) -> list[str]:
    """minúsculas, sem acento, sem pontuação, sem stopwords, com um radical grosseiro (corta sufixos comuns)."""
    texto = unicodedata.normalize("NFKD", str(texto).casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    termos = re.findall(r"[a-z0-9]+", texto)
    saida = []
    for t in termos:
        if t in _STOP or len(t) < 2:
            continue
        if not re.fullmatch(r"(rn|rf)\d+", t):
            for suf in ("acoes", "coes", "cao", "mente", "idade", "ados", "adas", "idos", "idas", "ado", "ada",
                        "ido", "ida", "ar", "er", "ir", "es", "s"):
                if len(t) > len(suf) + 3 and t.endswith(suf):
                    t = t[: -len(suf)]
                    break
            if len(t) > 4 and t[-1] in "aeo":  # venda/vendo/vende -> vend
                t = t[:-1]
        saida.append(t)
    return saida


@dataclass
class Indice:
    """BM25 clássico (k1=1,5; b=0,75). Serve ao RAG e à recuperação da memória episódica."""
    docs: list[dict]
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self):
        self._tokens = [normalizar(self._texto(d)) for d in self.docs]
        self._tf = [Counter(t) for t in self._tokens]
        n = len(self.docs) or 1
        self._media = sum(len(t) for t in self._tokens) / n if self.docs else 0.0
        df = Counter(term for t in self._tokens for term in set(t))
        self._idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    @staticmethod
    def _texto(doc: dict) -> str:
        return " ".join(str(doc.get(c, "")) for c in ("id", "titulo", "texto", "pergunta", "resumo"))

    def pontuar(self, consulta: str) -> list[tuple[float, dict]]:
        termos = normalizar(consulta)
        resultado = []
        for doc, tf, toks in zip(self.docs, self._tf, self._tokens):
            score = 0.0
            for term in termos:
                if term not in tf:
                    continue
                f = tf[term]
                score += self._idf.get(term, 0.0) * f * (self.k1 + 1) / (
                    f + self.k1 * (1 - self.b + self.b * len(toks) / (self._media or 1)))
            # citar o identificador ("RN26") é a pergunta mais precisa que existe
            if doc.get("id") and str(doc["id"]).casefold() in consulta.casefold().split():
                score += 10.0
            resultado.append((score, doc))
        resultado.sort(key=lambda par: (-par[0], str(par[1].get("id", ""))))
        return resultado


def carregar_corpus(caminho: str | Path = CORPUS_PADRAO) -> list[dict]:
    with Path(caminho).open(encoding="utf-8") as arq:
        return [json.loads(linha) for linha in arq if linha.strip()]


_CACHE: dict[str, Indice] = {}


def indice_padrao(caminho: str | Path = CORPUS_PADRAO) -> Indice:
    """Índice montado uma vez por processo (53 trechos: milissegundos)."""
    chave = str(caminho)
    if chave not in _CACHE:
        # metadado: só entra o que está ativo (uma regra removida nunca é citada)
        _CACHE[chave] = Indice([d for d in carregar_corpus(caminho) if d.get("estado", "ativo") == "ativo"])
    return _CACHE[chave]


def buscar(consulta: str, tipo: str | None = None, k: int = K, indice: Indice | None = None) -> list[dict]:
    indice = indice or indice_padrao()
    trechos = []
    for score, doc in indice.pontuar(consulta):
        if score < SCORE_MINIMO or len(trechos) >= k:
            break
        if tipo and doc.get("tipo") != tipo:
            continue
        trechos.append({"id": doc["id"], "tipo": doc["tipo"], "titulo": doc["titulo"],
                        "texto": doc["texto"][:MAX_CARACTERES], "fonte": doc.get("fonte", ""),
                        "score": round(score, 2)})
    return trechos
