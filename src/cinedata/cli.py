"""Verificação do ambiente de preparação, sem consumir cota do OpenRouter."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import date

from cinedata.config import load_settings
from cinedata.database import QueryLimits, execute_query
from cinedata.schema import ANALYTICAL_TABLES


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
        missing = ANALYTICAL_TABLES - tables
        if missing:
            raise ValueError(f"Tabelas da atividade ausentes: {', '.join(sorted(missing))}.")
        print(f"Banco acessível em modo somente leitura: {settings.db_path}")
        print(f"Tabelas da atividade: {len(ANALYTICAL_TABLES)}; total no banco: {len(tables)}")
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
    parser = argparse.ArgumentParser(description="CineData Analytics — consultas e análises")
    subcommands = parser.add_subparsers(dest="command", required=True)
    check = subcommands.add_parser("check", help="Verifica configuração e acesso local ao banco")
    check.add_argument("--require-key", action="store_true", help="Exige chave preenchida no .env")
    query = subcommands.add_parser("query", help="Executa uma consulta SQL local somente leitura")
    query.add_argument("sql", help="Uma instrução SELECT ou WITH ... SELECT")
    query.add_argument("--max-rows", type=int, default=100, help="Limite de linhas (1 a 1000)")
    ask = subcommands.add_parser("ask", help="Pergunta em linguagem natural via OpenRouter")
    ask.add_argument("question", help="Pergunta sobre o catálogo de filmes")
    ask.add_argument(
        "--reference-date", type=date.fromisoformat, help="Data de referência YYYY-MM-DD"
    )
    ask.add_argument("--show-sql", action="store_true", help="Mostra o SQL usado na análise")
    ask.add_argument(
        "--json", action="store_true", help="Retorna resposta, SQL e resultados em JSON"
    )
    args = parser.parse_args()
    if args.command == "check":
        return check_environment(require_key=args.require_key)
    if args.command == "ask":
        from cinedata.agent import ask_question

        try:
            result = ask_question(
                load_settings(), args.question, reference_date=args.reference_date
            )
        except ValueError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["answer"] if result["ok"] else result["error"]["message"])
            if args.show_sql:
                for entry in result["queries"]:
                    print(f"\nSQL: {entry['sql']}")
            print(f"\nChamadas ao modelo: {result['model_calls']}")
        return 0 if result["ok"] else 1
    try:
        result = execute_query(
            load_settings().db_path, args.sql, limits=QueryLimits(max_rows=args.max_rows)
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
