"""Verifica fidelidade das tabelas e separação da explicação na CLI, sem API."""

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cinedata.cli import main
from cinedata.presentation import render_query_tables


def query(columns, rows, **extra):
    return {"result": {"ok": True, "columns": columns, "rows": rows, **extra}}


class PresentationTests(unittest.TestCase):
    def test_duplicate_columns_null_zero_and_numbers_keep_their_values_and_order(self):
        queries = [query(["valor", "valor", "nota"], [[None, 0, 0.0], [2**63 - 1, -3.25, 1e-9]])]
        table = render_query_tables(queries)
        self.assertIn("| valor | valor | nota |", table)
        self.assertIn("| Não informado | 0 | 0.0 |", table)
        self.assertIn("| 9223372036854775807 | -3.25 | 1e-09 |", table)
        self.assertEqual(queries[0]["result"]["rows"][0], [None, 0, 0.0])

    def test_text_cannot_create_extra_columns_rows_or_links(self):
        table = render_query_tables([query(["título|nome"], [["A|B\n[link](url)\t<em>\x1b"]])])
        self.assertIn(r"título\|nome", table)
        self.assertIn(r"A\|B\n\[link\](url)\t\<em\>\x1b", table)
        self.assertNotIn("\x1b", table)
        self.assertEqual(len([line for line in table.splitlines() if line.startswith("| ")]), 3)

    def test_all_successful_queries_are_shown_without_selecting_a_main_query(self):
        queries = [
            {"result": {"ok": False, "error": {"code": "sqlite_error"}}},
            query(["filmes"], [[2]]),
            query(["titulo"], [["B"], ["A"]]),
        ]
        table = render_query_tables(queries)
        self.assertNotIn("Consulta 1", table)
        self.assertIn("Consulta 2", table)
        self.assertIn("Consulta 3", table)
        self.assertLess(table.index("| B |"), table.index("| A |"))

    def test_empty_truncated_and_shortened_results_are_explicit(self):
        table = render_query_tables(
            [
                query(["titulo"], []),
                query(["titulo"], [["Texto"]], truncated=True, shortened_cells=1),
            ]
        )
        self.assertIn("A consulta não retornou linhas.", table)
        self.assertIn("Linhas exibidas: 0.", table)
        self.assertIn("Resultado parcial", table)
        self.assertIn("Textos abreviados pelo executor em 1 célula(s).", table)

    def test_cli_keeps_sql_data_separate_from_unverified_model_numbers(self):
        tables = render_query_tables([query(["filmes"], [[2]])])
        result = {
            "ok": True,
            "answer": "Há 999 filmes.",
            "data_tables": tables,
            "queries": [],
            "model_calls": 2,
            "token_usage": {"total_tokens": None},
        }
        with (
            patch("sys.argv", ["cinedata", "ask", "Quantos filmes?"]),
            patch("cinedata.cli.load_settings"),
            patch("cinedata.agent.ask_question", return_value=result),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(main(), 0)
        data, explanation = output.getvalue().split("Explicação do modelo:")
        self.assertIn("| 2 |", data)
        self.assertNotIn("999", data)
        self.assertIn("999", explanation)

    def test_cli_json_preserves_raw_data_and_table_even_after_agent_failure(self):
        queries = [query(["filmes"], [[2]])]
        result = {
            "ok": False,
            "error": {"code": "connection_error", "message": "Falha de rede."},
            "queries": queries,
            "data_tables": render_query_tables(queries),
            "model_calls": 2,
            "token_usage": {"total_tokens": None},
        }
        with (
            patch("sys.argv", ["cinedata", "ask", "Quantos filmes?", "--json"]),
            patch("cinedata.cli.load_settings"),
            patch("cinedata.agent.ask_question", return_value=result),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(main(), 1)
        returned = json.loads(output.getvalue())
        self.assertEqual(returned["queries"][0]["result"]["rows"], [[2]])
        self.assertIn("| 2 |", returned["data_tables"])


if __name__ == "__main__":
    unittest.main()
