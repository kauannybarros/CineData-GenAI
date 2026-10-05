"""Valida regras financeiras, cobertura, notas e empates com respostas conhecidas."""

import contextlib
import io
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from cinedata.config import Settings
from cinedata.evaluation import compare_agent_queries, compare_results, run_evaluation


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "fixture.db"
        with contextlib.closing(sqlite3.connect(self.db)) as c:
            c.executescript("""
                CREATE TABLE dim_movies(sk_movie_id TEXT PRIMARY KEY, titulo TEXT,
                    ano_lancamento INTEGER, data_lancamento TEXT, status_filme TEXT);
                CREATE TABLE fact_movies_performance(sk_movie_id TEXT PRIMARY KEY,
                    receita_brl NUMERIC, orcamento_brl NUMERIC, lucro_brl NUMERIC,
                    nota_tmdb REAL, qtd_tmdb INTEGER, nota_imdb REAL, qtd_imdb INTEGER,
                    popularidade REAL);
                CREATE TABLE dim_genres(sk_genre_id TEXT, nome_genero TEXT);
                CREATE TABLE bridge_movie_genre(sk_movie_id TEXT, sk_genre_id TEXT);
                CREATE TABLE dim_people(sk_person_id TEXT, nome_pessoa TEXT, tipo_pessoa TEXT);
                CREATE TABLE bridge_movie_person(sk_movie_id TEXT, sk_person_id TEXT);
                CREATE TABLE dim_companies(sk_company_id TEXT, nome_produtora TEXT);
                CREATE TABLE bridge_movie_company(sk_movie_id TEXT, sk_company_id TEXT);
                CREATE TABLE dim_reviews(sk_movie_id TEXT, nota_media_usuarios REAL,
                    qtd_avaliacoes_usuarios INTEGER);
                CREATE TABLE movie_reviews(sk_movie_id TEXT);
            """)
            movies = [
                ("a", "Alpha", 2022),
                ("b", "Beta", 2023),
                ("c", "Gamma", 2024),
                ("d", "Delta", 2025),
                ("e", "Epsilon", 2026),
                ("f", "Future", 2027),
                ("g", "Old", 2020),
                ("h", "Zero", 2026),
            ]
            c.executemany(
                "INSERT INTO dim_movies VALUES (?,?,?,?,?)",
                [
                    (key, title, year, f"{year}-01-01", "Planejado" if key == "f" else "Lançado")
                    for key, title, year in movies
                ],
            )
            c.executemany(
                "INSERT INTO fact_movies_performance VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    ("a", 100, 50, 50, 8, 10, 6, 10, 10),
                    ("b", 200, 100, 100, 9, 10, 9, 10, 20),
                    ("c", 300, None, 300, 0, 0, 8, 10, None),
                    ("d", None, 10, -10, 0, 5, None, 100, 0),
                    ("e", 100, 100, 0, 7, 10, 7, 10, 5),
                    ("f", 500, 200, 300, 10, 10, 10, 50, 2),
                    ("g", 100, 0, 100, 1, 1, 5, 1, 6),
                    ("h", 0, 0, 0, 0, 1, 0, 1, 1),
                ],
            )
            c.executemany(
                "INSERT INTO dim_genres VALUES (?,?)",
                [("action", "Action"), ("drama", "Drama"), ("empty", "Empty")],
            )
            for genre, keys in [("action", "abch"), ("drama", "aeg")]:
                c.executemany(
                    "INSERT INTO bridge_movie_genre VALUES (?,?)", [(k, genre) for k in keys]
                )
            c.executemany(
                "INSERT INTO dim_people VALUES (?,?,?)",
                [
                    ("alex", "Alex", "Ator"),
                    ("sam", "Sam", "Ator"),
                    ("five", "DirFive", "Diretor"),
                    ("no", "DirNoScore", "Diretor"),
                ],
            )
            for person, keys in [
                ("alex", "abcef"),
                ("sam", "bcde"),
                ("five", "abceg"),
                ("no", "abcde"),
            ]:
                c.executemany(
                    "INSERT INTO bridge_movie_person VALUES (?,?)", [(k, person) for k in keys]
                )
            for company, keys in [("One", "abcg"), ("Two", "abg")]:
                c.execute("INSERT INTO dim_companies VALUES (?,?)", (company, company))
                c.executemany(
                    "INSERT INTO bridge_movie_company VALUES (?,?)", [(k, company) for k in keys]
                )
            c.executemany(
                "INSERT INTO dim_reviews VALUES (?,?,?)",
                [("a", 10, 2), ("b", 7, 3), ("c", 4, 1), ("e", 9, 4)],
            )
            c.commit()
        self.settings = Settings(self.db, "openrouter/free", "test-key")

    def run_report(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_evaluation(self.settings, date(2026, 10, 4), **kwargs)

    def test_reference_queries_against_known_answers(self):
        before = self.db.read_bytes()
        report = self.run_report()
        self.assertEqual(report["summary"], {"reference_ok": 14})
        self.assertEqual(report["model_calls"], 0)
        rows = {c["id"]: c["expected"]["rows"] for c in report["cases"]}
        self.assertEqual(rows["lucro_genero"], [["Action", 112.5, 4, 1], ["Drama", 50.0, 3, 0]])
        self.assertEqual(rows["generos"], [["Action", 4], ["Drama", 3], ["Empty", 0]])
        self.assertEqual(rows["ator"], [["Alex", 4], ["Sam", 4]])
        self.assertEqual(rows["diretores"], [["DirFive", 7.0, 5]])
        self.assertEqual(
            rows["dupla"],
            [["Alex", "DirFive", 4], ["Alex", "DirNoScore", 4], ["Sam", "DirNoScore", 4]],
        )
        self.assertEqual(rows["produtora"], [["One", 250], ["Two", 250]])
        self.assertEqual(rows["margem_genero"], [["Action", 50.0, 2], ["Drama", 50.0, 3]])
        self.assertEqual(rows["margem"][0], ["Old", 100.0])
        self.assertEqual(rows["divergencia_notas"][0], ["Old", 1.0, 5.0, 4.0])
        self.assertIn([2026, 3.5, 2], rows["imdb_ano"])
        self.assertEqual(rows["avaliacoes"][0], ["Epsilon", 4])
        self.assertEqual(before, self.db.read_bytes())

    def test_comparison_detects_wrong_order_values_and_partial_data(self):
        expected = {"columns": ["titulo", "media"], "rows": [["A", 1 / 3], ["B", 2.0]]}
        actual = {"ok": True, "columns": ["titulo", "media"], "rows": [["A", 0.33], ["B", 2]]}
        self.assertTrue(compare_results(expected, actual)[0])
        actual["rows"].reverse()
        self.assertFalse(compare_results(expected, actual)[0])
        actual["rows"] = [["A", 0.5], ["B", 2]]
        self.assertFalse(compare_results(expected, actual)[0])
        actual["truncated"] = True
        self.assertFalse(compare_results(expected, actual)[0])

    def test_budget_never_starts_case_without_reserved_calls(self):
        with patch("cinedata.evaluation.ask_question") as ask:
            report = self.run_report(live=True, max_calls=2, case_ids=["receita"])
        ask.assert_not_called()
        self.assertEqual(report["summary"], {"skipped": 1})

    def test_auxiliary_query_does_not_override_main_evidence(self):
        expected = {"columns": ["filmes"], "rows": [[2]]}
        agent = {
            "queries": [
                {"id": "main", "result": {"ok": True, **expected}},
                {"id": "check", "result": {"ok": True, "columns": ["nome"], "rows": [["A"]]}},
            ]
        }
        passed, _, query_id = compare_agent_queries(expected, agent)
        self.assertTrue(passed)
        self.assertEqual(query_id, "main")

    def test_rate_limit_stops_remaining_model_requests(self):
        failed = {"ok": False, "model_calls": 1, "error": {"code": "rate_limit"}, "queries": []}
        with patch("cinedata.evaluation.ask_question", return_value=failed) as ask:
            report = self.run_report(live=True, max_calls=10, case_ids=["receita", "popularidade"])
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(report["model_calls"], 1)
        self.assertEqual(report["summary"], {"agent_error": 1, "skipped": 1})


if __name__ == "__main__":
    unittest.main()
