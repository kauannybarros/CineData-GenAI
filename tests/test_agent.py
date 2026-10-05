"""Exercita o ciclo completo do agente com modelo simulado e SQLite temporário."""

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from cinedata.agent import ask_question, build_model
from cinedata.config import Settings, load_settings
from cinedata.prompts import build_system_prompt
from cinedata.schema import ANALYTICAL_TABLES


class ScriptedModel(BaseChatModel):
    responses: list[AIMessage]
    calls: int = 0
    fail_on_call: int | None = None
    received_tool_results: list[str] = []
    bound_choices: list = []

    @property
    def _llm_type(self):
        return "scripted-test"

    def bind_tools(self, tools, **kwargs):
        self.bound_choices.append(kwargs.get("tool_choice"))
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.received_tool_results.extend(m.content for m in messages if isinstance(m, ToolMessage))
        if self.fail_on_call == self.calls:
            raise httpx.ConnectError("Detalhe privado que não deve aparecer na resposta")
        message = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        return ChatResult(generations=[ChatGeneration(message=message)])


def sql_call(sql: str, call_id: str = "q1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "query_database", "args": {"sql": sql}, "id": call_id, "type": "tool_call"}
        ],
    )


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "catalog.db"
        conn = sqlite3.connect(self.db)
        for table in ANALYTICAL_TABLES:
            conn.execute(f'CREATE TABLE "{table}"(sk_movie_id TEXT, titulo TEXT)')
        conn.executemany("INSERT INTO dim_movies VALUES (?, ?)", [("a", "A"), ("b", "B")])
        conn.commit()
        conn.close()
        self.settings = Settings(self.db, "openrouter/free", "test-key")

    def test_sql_result_is_given_to_model_before_answer(self):
        model = ScriptedModel(
            responses=[
                sql_call("SELECT COUNT(*) AS filmes FROM dim_movies"),
                AIMessage(content="O catálogo contém 2 filmes."),
            ]
        )
        result = ask_question(
            self.settings, "Quantos filmes existem?", model=model, reference_date=date(2026, 10, 4)
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model_calls"], 2)
        self.assertEqual(result["queries"][0]["result"]["rows"], [[2]])
        self.assertIn("| filmes |", result["data_tables"])
        self.assertIn("| 2 |", result["data_tables"])
        self.assertIn('"rows": [[2]]', model.received_tool_results[-1])
        self.assertEqual(result["reference_date"], "2026-10-04")
        self.assertEqual(model.bound_choices[0], "required")
        self.assertIsNone(model.bound_choices[-1])

    def test_model_can_correct_sql_within_budget(self):
        model = ScriptedModel(
            responses=[
                sql_call("SELECT inexistente FROM dim_movies"),
                sql_call("SELECT COUNT(*) FROM dim_movies", "q2"),
                AIMessage(content="São 2 filmes."),
            ]
        )
        result = ask_question(self.settings, "Quantos filmes?", model=model)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model_calls"], 3)
        self.assertFalse(result["queries"][0]["result"]["ok"])
        self.assertTrue(result["queries"][1]["result"]["ok"])

    def test_unverified_answer_is_rejected(self):
        result = ask_question(
            self.settings,
            "Quantos filmes?",
            model=ScriptedModel(responses=[AIMessage(content="999 filmes.")]),
        )
        self.assertEqual(result["error"]["code"], "no_query_result")
        self.assertNotIn("answer", result)
        self.assertEqual(result["data_tables"], "")

    def test_tokens_include_sql_and_answer_without_recounting_graph_states(self):
        query = sql_call("SELECT COUNT(*) AS filmes FROM dim_movies")
        query.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        answer = AIMessage(
            content="O catálogo contém 2 filmes.",
            usage_metadata={"input_tokens": 150, "output_tokens": 10, "total_tokens": 160},
        )
        result = ask_question(
            self.settings, "Quantos filmes?", model=ScriptedModel(responses=[query, answer])
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["token_usage"],
            {
                "input_tokens": 250,
                "output_tokens": 30,
                "total_tokens": 280,
                "calls_with_usage": 2,
                "complete": True,
            },
        )

    def test_tokens_survive_provider_failure_and_are_marked_partial(self):
        query = sql_call("SELECT COUNT(*) FROM dim_movies")
        query.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        result = ask_question(
            self.settings,
            "Quantos filmes?",
            model=ScriptedModel(responses=[query], fail_on_call=2),
        )
        self.assertEqual(result["error"]["code"], "connection_error")
        self.assertEqual(result["token_usage"]["total_tokens"], 120)
        self.assertEqual(result["token_usage"]["calls_with_usage"], 1)
        self.assertFalse(result["token_usage"]["complete"])

    def test_missing_usage_is_unknown_not_zero(self):
        result = ask_question(
            self.settings,
            "Quantos filmes?",
            model=ScriptedModel(responses=[AIMessage(content="2 filmes")]),
        )
        self.assertIsNone(result["token_usage"]["total_tokens"])
        self.assertFalse(result["token_usage"]["complete"])

    def test_write_attempt_cannot_ground_answer(self):
        before = self.db.read_bytes()
        model = ScriptedModel(
            responses=[sql_call("DELETE FROM dim_movies"), AIMessage(content="Filmes removidos.")]
        )
        result = ask_question(self.settings, "Remova todos os filmes", model=model)
        self.assertFalse(result["ok"])
        self.assertEqual(result["queries"][0]["result"]["error"]["code"], "forbidden_sql")
        self.assertEqual(before, self.db.read_bytes())

    def test_model_call_limit_stops_loop(self):
        model = ScriptedModel(
            responses=[
                sql_call("SELECT 1", "q1"),
                sql_call("SELECT 1", "q2"),
                sql_call("SELECT 1", "q3"),
                sql_call("SELECT 1", "q4"),
            ]
        )
        result = ask_question(self.settings, "Consulte", model=model)
        self.assertEqual(result["error"]["code"], "agent_limit")
        self.assertEqual(model.calls, 3)
        self.assertEqual(result["model_calls"], 3)

    def test_tool_limit_stops_many_calls_in_one_response(self):
        calls = [sql_call("SELECT 1", f"q{i}").tool_calls[0] for i in range(4)]
        result = ask_question(
            self.settings,
            "Consulte",
            model=ScriptedModel(responses=[AIMessage(content="", tool_calls=calls)]),
        )
        self.assertEqual(result["error"]["code"], "agent_limit")
        self.assertEqual(result["model_calls"], 1)

    def test_failed_provider_preserves_query_and_hides_exception(self):
        model = ScriptedModel(
            responses=[sql_call("SELECT COUNT(*) FROM dim_movies")], fail_on_call=2
        )
        result = ask_question(self.settings, "Quantos filmes?", model=model)
        self.assertEqual(result["error"]["code"], "connection_error")
        self.assertEqual(result["queries"][0]["result"]["rows"], [[2]])
        self.assertIn("| 2 |", result["data_tables"])
        self.assertNotIn("Detalhe privado", str(result))

    def test_input_validation_does_not_call_model(self):
        model = ScriptedModel(responses=[AIMessage(content="inútil")])
        for question in ("", "x" * 4001):
            self.assertFalse(ask_question(self.settings, question, model=model)["ok"])
        self.assertEqual(model.calls, 0)
        settings = Settings(self.db, "openrouter/free", "")
        self.assertEqual(ask_question(settings, "Quantos filmes?")["error"]["code"], "missing_key")

    def test_prompt_uses_actual_schema_and_leap_year_window(self):
        prompt = build_system_prompt(self.db, date(2024, 2, 29))
        self.assertIn("2019-02-28 a 2024-02-29", prompt)
        self.assertIn("dim_movies(sk_movie_id TEXT, titulo TEXT)", prompt)
        self.assertNotIn("alembic_version", prompt)
        self.assertNotIn("test-key", prompt)

    def test_sdk_retries_are_disabled_and_timeout_is_milliseconds(self):
        model = build_model(self.settings)
        self.assertIsNone(model.client.sdk_configuration.retry_config)
        self.assertEqual(model.client.sdk_configuration.timeout_ms, 45000)
        self.assertEqual(model.max_retries, 0)
        self.assertEqual(model.max_tokens, 8192)

    def test_invalid_env_budget(self):
        with patch.dict("os.environ", {"CINEDATA_MAX_MODEL_CALLS": "100"}):
            with self.assertRaises(ValueError):
                load_settings()


if __name__ == "__main__":
    unittest.main()
