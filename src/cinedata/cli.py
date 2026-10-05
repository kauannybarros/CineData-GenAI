"""Verificação do ambiente de preparação, sem consumir cota do OpenRouter."""

import argparse
import sqlite3
from contextlib import closing

from cinedata.config import load_settings

EXPECTED_TABLES = {
    "dim_movies",
    "fact_movies_performance",
    "dim_genres",
    "dim_people",
    "dim_companies",
    "dim_reviews",
    "movie_reviews",
    "bridge_movie_genre",
    "bridge_movie_person",
    "bridge_movie_company",
}


def check_environment(require_key: bool = False) -> int:
    try:
        settings = load_settings()
        if not settings.db_path.is_file():
            raise ValueError(f"Banco não encontrado: {settings.db_path}")
        with closing(sqlite3.connect(f"{settings.db_path.as_uri()}?mode=ro", uri=True)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        missing = EXPECTED_TABLES - tables
        if missing:
            raise ValueError(f"Tabelas da atividade ausentes: {', '.join(sorted(missing))}.")
        print(f"Banco acessível em modo somente leitura: {settings.db_path}")
        print(f"Tabelas da atividade: {len(EXPECTED_TABLES)}; total no banco: {len(tables)}")
        print(f"Modelo configurado: {settings.model}")
        if settings.api_key:
            print("Chave OpenRouter preenchida (autenticação ainda não validada).")
        elif require_key:
            raise ValueError("Preencha OPENROUTER_API_KEY no .env.")
        else:
            print("Chave OpenRouter pendente: preencha OPENROUTER_API_KEY no .env.")
        print("Verificação local concluída; nenhuma chamada ao modelo foi realizada.")
        return 0
    except (ValueError, sqlite3.Error) as exc:
        print(f"Falha na preparação: {exc}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="CineData Analytics — preparação do projeto")
    subcommands = parser.add_subparsers(dest="command", required=True)
    check = subcommands.add_parser("check", help="Verifica configuração e acesso local ao banco")
    check.add_argument("--require-key", action="store_true", help="Exige chave preenchida no .env")
    args = parser.parse_args()
    return check_environment(require_key=args.require_key)


if __name__ == "__main__":
    raise SystemExit(main())
