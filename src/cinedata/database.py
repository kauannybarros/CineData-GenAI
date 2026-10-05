"""Execução restrita de SQL sobre as dez tabelas analíticas do SQLite."""

import math
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cinedata.schema import ANALYTICAL_TABLES

# Apenas funções internas de análise, sem extensões, escrita ou leitura de arquivos.
ALLOWED_FUNCTIONS = frozenset(
    "abs avg coalesce count date datetime dense_rank first_value glob group_concat "
    "ifnull instr julianday lag last_value lead length like lower ltrim max min nth_value "
    "ntile nullif rank replace round row_number rtrim strftime substr substring "
    "sum time total trim typeof unixepoch upper".split()
)
LEADING_COMMENTS = re.compile(r"\A(?:\s+|--[^\n]*(?:\n|\Z)|/\*[\s\S]*?\*/)*")
FIRST_KEYWORD = re.compile(r"[A-Za-z_]+")


@dataclass(frozen=True)
class QueryLimits:
    max_rows: int = 100
    timeout_seconds: float = 10.0
    max_vm_steps: int = 20_000_000
    max_sql_chars: int = 20_000
    max_columns: int = 32
    max_cell_chars: int = 2_000

    def __post_init__(self) -> None:
        for name in ("max_rows", "max_vm_steps", "max_sql_chars", "max_columns", "max_cell_chars"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} deve ser um inteiro positivo.")
        if self.max_rows > 1_000 or self.max_columns > 32 or self.max_cell_chars > 2_000:
            raise ValueError(
                "Limites máximos: 1000 linhas, 32 colunas e 2000 caracteres por célula."
            )
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 30:
            raise ValueError("timeout_seconds deve estar entre 0 (exclusivo) e 30 segundos.")


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def execute_query(db_path: Path, sql: str, *, limits: QueryLimits | None = None) -> dict[str, Any]:
    """Executa uma consulta, devolvendo linhas posicionais e erros estruturados.

    A validação definitiva usa o autorizador do SQLite, inclusive para CTEs e funções.
    A verificação do primeiro termo é apenas um filtro inicial, não um parser SQL.
    """
    limits = limits or QueryLimits()
    if not isinstance(sql, str) or not sql.strip():
        return _error("invalid_sql", "Informe uma consulta SQL não vazia.")
    if len(sql) > limits.max_sql_chars:
        return _error("invalid_sql", "Consulta excede o limite de tamanho do SQL.")
    start = LEADING_COMMENTS.match(sql).end()
    keyword = FIRST_KEYWORD.match(sql, start)
    if keyword is None or keyword.group().upper() not in {"SELECT", "WITH"}:
        return _error("forbidden_sql", "Somente SELECT ou WITH ... SELECT são permitidos.")
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        return _error("database_unavailable", "Banco SQLite não encontrado.")

    deadline = time.monotonic() + limits.timeout_seconds
    blocked = False
    interrupted = False
    steps = 0
    interval = min(1_000, limits.max_vm_steps)

    def authorize(action: int, arg1: str | None, arg2: str | None, db: str | None, _: str | None):
        nonlocal blocked
        allowed = action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}
        if action == sqlite3.SQLITE_READ:
            # COUNT(*) otimizado informa coluna vazia e omite o nome do banco.
            main_read = db == "main" or (db is None and arg2 == "")
            allowed = main_read and arg1 is not None and arg1.lower() in ANALYTICAL_TABLES
        elif action == sqlite3.SQLITE_FUNCTION:
            allowed = arg2 is not None and arg2.lower() in ALLOWED_FUNCTIONS
        if not allowed:
            blocked = True
        return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY

    def progress() -> int:
        nonlocal steps, interrupted
        steps += interval
        interrupted = steps >= limits.max_vm_steps or time.monotonic() >= deadline
        return int(interrupted)

    try:
        with closing(
            sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=limits.timeout_seconds)
        ) as conn:
            conn.execute("PRAGMA query_only = ON")
            # Limites do mecanismo também se aplicam a expressões geradas pelo SQL.
            conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, limits.max_sql_chars * 4)
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 100_000)
            conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, limits.max_columns)
            conn.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 100)
            conn.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 20)
            conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
            conn.set_authorizer(authorize)
            conn.set_progress_handler(progress, interval)
            cursor = conn.execute(sql)
            columns = [column[0] for column in cursor.description]
            fetched = cursor.fetchmany(limits.max_rows + 1)
            if time.monotonic() >= deadline:
                return _error("query_limit", "Consulta excedeu o limite de tempo de execução.")
            truncated = len(fetched) > limits.max_rows
            rows = []
            shortened = 0
            for row in fetched[: limits.max_rows]:
                values = []
                for value in row:
                    if isinstance(value, bytes):
                        return _error(
                            "unsupported_result", "Resultados binários não são permitidos."
                        )
                    if isinstance(value, float) and not math.isfinite(value):
                        return _error(
                            "unsupported_result", "Resultados numéricos devem ser finitos."
                        )
                    if isinstance(value, str) and len(value) > limits.max_cell_chars:
                        value = value[: limits.max_cell_chars]
                        shortened += 1
                    values.append(value)
                rows.append(values)
            return {
                "ok": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "max_rows": limits.max_rows,
                "truncated": truncated,
                "shortened_cells": shortened,
            }
    except sqlite3.Error as exc:
        if blocked:
            return _error(
                "forbidden_sql", "Consulta acessa uma operação, tabela ou função proibida."
            )
        if interrupted or time.monotonic() >= deadline:
            return _error(
                "query_limit", "Consulta excedeu o limite de tempo ou trabalho do SQLite."
            )
        # Mensagem do mecanismo ajuda o agente a corrigir coluna/sintaxe; não inclui credenciais.
        return _error("sqlite_error", str(exc))
