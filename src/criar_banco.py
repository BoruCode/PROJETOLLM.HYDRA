"""python -m src.criar_banco  ->  apaga e recria o banco simulado."""
from .config import carregar_config
from .db import criar_banco

if __name__ == "__main__":
    caminho = criar_banco(carregar_config(exigir_llm=False).caminho_db)
    print(f"Banco recriado em {caminho}")
