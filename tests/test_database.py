"""Verifica consultas analíticas e tentativas de escapar dos limites em banco temporário."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cinedata.database import QueryLimits, execute_query
from cinedata.tools import create_sql_tool


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "catalog #1.db"
        conn = sqlite3.connect(self.db)
        conn.executescript(
            "CREATE TABLE dim_movies(sk_movie_id TEXT PRIMARY KEY, titulo TEXT);"
            "INSERT INTO dim_movies VALUES ('a', 'A'), ('b', 'B'), ('c', 'C');"
            "CREATE TABLE fact_movies_performance(sk_movie_id TEXT, receita_brl NUMERIC);"
            "INSERT INTO fact_movies_performance VALUES ('a', 10), ('b', 20), ('c', NULL);"
            "CREATE TABLE alembic_version(version_num TEXT);"
            "INSERT INTO alembic_version VALUES ('v1');"
        )
        conn.close()

    def query(self, sql, **kwargs):
        return execute_query(self.db, sql, **kwargs)

    def test_join_and_aggregate_use_full_dataset(self):
        result = self.query(
            "SELECT COUNT(*) AS filmes, SUM(f.receita_brl) AS receita "
            "FROM dim_movies m JOIN fact_movies_performance f USING(sk_movie_id)",
            limits=QueryLimits(max_rows=1),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["columns"], ["filmes", "receita"])
        self.assertEqual(result["rows"], [[3, 30]])
        self.assertFalse(result["truncated"])

    def test_comments_cte_and_window(self):
        result = self.query(
            "/* entrada */ -- comentário\n WITH filmes AS (SELECT titulo FROM dim_movies) "
            "SELECT titulo, ROW_NUMBER() OVER (ORDER BY titulo) FROM filmes ORDER BY titulo;"
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["rows"], [["A", 1], ["B", 2], ["C", 3]])

    def test_limit_reports_partial_rows(self):
        result = self.query("SELECT titulo FROM dim_movies ORDER BY titulo", limits=QueryLimits(2))
        self.assertEqual(result["rows"], [["A"], ["B"]])
        self.assertEqual(result["row_count"], 2)
        self.assertTrue(result["truncated"])
        exact = self.query("SELECT titulo FROM dim_movies LIMIT 2", limits=QueryLimits(2))
        self.assertFalse(exact["truncated"])

    def test_empty_result_and_duplicate_column_names(self):
        empty = self.query("SELECT titulo FROM dim_movies WHERE 0")
        self.assertEqual(empty["rows"], [])
        duplicate = self.query("SELECT 1 AS valor, 2 AS valor")
        self.assertEqual(duplicate["columns"], ["valor", "valor"])
        self.assertEqual(duplicate["rows"], [[1, 2]])

    def test_writes_admin_commands_and_hidden_tables_are_blocked(self):
        before = self.db.read_bytes()
        queries = [
            "DELETE FROM dim_movies",
            "UPDATE dim_movies SET titulo='X'",
            "INSERT INTO dim_movies VALUES ('x','X')",
            "DROP TABLE dim_movies",
            "CREATE TABLE x(id)",
            "WITH x AS (SELECT 1) DELETE FROM dim_movies",
            "PRAGMA table_info(dim_movies)",
            "ATTACH DATABASE ':memory:' AS other",
            "BEGIN",
            "VACUUM",
            "SELECT * FROM sqlite_master",
            "SELECT COUNT(*) FROM sqlite_master",
            "SELECT * FROM alembic_version",
            "SELECT COUNT(*) FROM alembic_version",
            "WITH x AS (SELECT * FROM alembic_version) SELECT * FROM x",
            "SELECT * FROM pragma_table_info('dim_movies')",
            "SELECT load_extension('anything')",
            "SELECT randomblob(10000000)",
        ]
        for sql in queries:
            with self.subTest(sql=sql):
                result = self.query(sql)
                self.assertFalse(result["ok"], result)
        self.assertEqual(before, self.db.read_bytes())

    def test_multiple_statements_rejected_without_side_effects(self):
        before = self.db.read_bytes()
        result = self.query("SELECT 1; DELETE FROM dim_movies;")
        self.assertFalse(result["ok"])
        self.assertEqual(before, self.db.read_bytes())
        # Um ponto e vírgula dentro de string não é uma segunda instrução.
        self.assertEqual(
            self.query("SELECT '; DELETE FROM dim_movies'")["rows"], [["; DELETE FROM dim_movies"]]
        )

    def test_invalid_and_missing_inputs(self):
        for sql in ("", "   ", "-- comentário", "/* comentário */", None):
            with self.subTest(sql=sql):
                self.assertFalse(self.query(sql)["ok"])
        self.assertEqual(
            self.query("SELECT desconhecida FROM dim_movies")["error"]["code"], "sqlite_error"
        )
        missing = Path(self.temp.name) / "missing.db"
        self.assertEqual(
            execute_query(missing, "SELECT 1")["error"]["code"], "database_unavailable"
        )
        self.assertFalse(missing.exists())
        self.assertEqual(
            self.query("SELECT 123", limits=QueryLimits(max_sql_chars=5))["error"]["code"],
            "invalid_sql",
        )

    def test_recursive_work_limit(self):
        result = self.query(
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) SELECT SUM(x) FROM n",
            limits=QueryLimits(max_vm_steps=100),
        )
        self.assertEqual(result["error"]["code"], "query_limit")
        self.assertTrue(self.query("SELECT COUNT(*) FROM dim_movies")["ok"])

    def test_timeout_is_reported(self):
        with patch("cinedata.database.time.monotonic", side_effect=[0.0, 10.0, 10.0]):
            result = self.query("SELECT 1", limits=QueryLimits(timeout_seconds=1))
        self.assertEqual(result["error"]["code"], "query_limit")

    def test_text_and_binary_limits(self):
        result = self.query("SELECT 'abcdef' AS texto", limits=QueryLimits(max_cell_chars=3))
        self.assertEqual(result["rows"], [["abc"]])
        self.assertEqual(result["shortened_cells"], 1)
        self.assertEqual(self.query("SELECT X'ABCD'")["error"]["code"], "unsupported_result")
        oversized = self.query(
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<200) "
            "SELECT GROUP_CONCAT('" + "x" * 1000 + "') FROM n"
        )
        self.assertFalse(oversized["ok"])
        self.assertEqual(self.query("SELECT 1e999")["error"]["code"], "unsupported_result")

    def test_column_limit(self):
        result = self.query("SELECT 1, 2, 3", limits=QueryLimits(max_columns=2))
        self.assertFalse(result["ok"])

    def test_invalid_limits(self):
        for kwargs in (
            {"max_rows": 0},
            {"max_rows": 1001},
            {"max_rows": True},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": 0},
            {"max_columns": 33},
            {"max_vm_steps": -1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                QueryLimits(**kwargs)

    def test_langchain_tool_invocation(self):
        tool = create_sql_tool(self.db, limits=QueryLimits(max_rows=1))
        result = tool.invoke({"sql": "SELECT titulo FROM dim_movies ORDER BY titulo"})
        self.assertEqual(result["rows"], [["A"]])
        self.assertTrue(result["truncated"])
        self.assertEqual(set(tool.args), {"sql"})


if __name__ == "__main__":
    unittest.main()
