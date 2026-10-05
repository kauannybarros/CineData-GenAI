"""Agente Text-to-SQL com orçamento por pergunta e resultados auditáveis."""

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openrouter import ChatOpenRouter
from langgraph.errors import GraphRecursionError
from openrouter import OpenRouter

from cinedata.config import Settings
from cinedata.prompts import build_system_prompt
from cinedata.tools import create_sql_tool


class CallCounter(BaseCallbackHandler):
    """Conta tentativas de chamada sem registrar prompts, resultados ou credenciais."""

    def __init__(self):
        self.calls = 0

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.calls += 1


def build_model(settings: Settings) -> ChatOpenRouter:
    # max_retries=0 sozinho deixa o SDK usar retries padrão em erros 5xx.
    # retry_config=None desabilita explicitamente esses retries no SDK.
    client = OpenRouter(api_key=settings.api_key, retry_config=None, timeout_ms=45_000)
    return ChatOpenRouter(
        model=settings.model,
        api_key=settings.api_key,
        client=client,
        max_retries=0,
        timeout=45_000,
        temperature=0,
        max_tokens=4096,
        openrouter_provider={"require_parameters": True},
    )


def _provider_error(exc: Exception) -> tuple[str, str]:
    status = getattr(exc, "status_code", None)
    if status == 401:
        return "authentication_error", "OpenRouter recusou a chave. Confira OPENROUTER_API_KEY."
    if status == 402:
        return "billing_error", "OpenRouter recusou a chamada por saldo/créditos da conta."
    if status == 429:
        return "rate_limit", "OpenRouter atingiu limite ou capacidade. Confira o painel de uso."
    if status == 404:
        return "model_unavailable", "Modelo indisponível. Confira OPENROUTER_MODEL."
    if isinstance(exc, httpx.TimeoutException) or status in {408, 524}:
        return (
            "model_timeout",
            "O modelo excedeu o tempo de resposta. Nenhuma retentativa foi feita.",
        )
    if isinstance(exc, httpx.TransportError):
        return "connection_error", "Não foi possível conectar ao OpenRouter. Confira a rede."
    return "model_error", "Falha na resposta do OpenRouter ou no uso de ferramentas pelo modelo."


def ask_question(
    settings: Settings,
    question: str,
    *,
    reference_date: date | None = None,
    model: BaseChatModel | None = None,
) -> dict[str, Any]:
    """Executa uma pergunta independente; model permite testes locais sem API."""
    reference_date = reference_date or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    counter = CallCounter()
    trace: list[dict[str, Any]] = []

    def failure(code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {"code": code, "message": message},
            "queries": trace,
            "model_calls": counter.calls,
        }

    if not isinstance(question, str) or not question.strip() or len(question) > 4_000:
        return failure("invalid_question", "Informe uma pergunta de até 4.000 caracteres.")
    if model is None and not settings.api_key:
        return failure("missing_key", "Preencha OPENROUTER_API_KEY no .env.")
    if not settings.db_path.is_file():
        return failure("database_unavailable", "Banco SQLite não encontrado.")
    if not 2 <= settings.max_model_calls <= 5:
        return failure("invalid_config", "O orçamento deve ser de 2 a 5 chamadas ao modelo.")
    try:
        prompt = build_system_prompt(settings.db_path, reference_date)
    except (ValueError, OSError) as exc:
        return failure("invalid_database", str(exc))
    except Exception:
        return failure("invalid_database", "Não foi possível ler o esquema do banco SQLite.")
    try:
        graph = create_agent(
            model=model if model is not None else build_model(settings),
            tools=[create_sql_tool(settings.db_path)],
            system_prompt=prompt,
            middleware=[
                ModelCallLimitMiddleware(run_limit=settings.max_model_calls, exit_behavior="error"),
                ToolCallLimitMiddleware(run_limit=3, exit_behavior="error"),
            ],
        )
        # Streaming de estado captura consultas mesmo se uma chamada posterior falhar.
        seen_calls: set[str] = set()
        results: dict[str, dict] = {}
        final_messages = []
        for state in graph.stream(
            {"messages": [{"role": "user", "content": question.strip()}]},
            config={"callbacks": [counter], "recursion_limit": 30},
            stream_mode="values",
        ):
            final_messages = state["messages"]
            for message in final_messages:
                if isinstance(message, AIMessage):
                    for call in message.tool_calls:
                        if call["id"] not in seen_calls:
                            seen_calls.add(call["id"])
                            trace.append({"id": call["id"], "sql": call["args"].get("sql")})
                elif isinstance(message, ToolMessage) and message.tool_call_id not in results:
                    try:
                        data = json.loads(message.content)
                    except (TypeError, ValueError):
                        data = {"ok": False, "error": {"code": "tool_error"}}
                    results[message.tool_call_id] = (
                        data if isinstance(data, dict) else {"ok": False}
                    )
            for entry in trace:
                if entry["id"] in results:
                    entry["result"] = results[entry["id"]]
        if not any(entry.get("result", {}).get("ok") for entry in trace):
            return failure("no_query_result", "O modelo não obteve uma consulta válida no banco.")
        if not final_messages or not isinstance(final_messages[-1], AIMessage):
            return failure("empty_answer", "O modelo não apresentou uma resposta final.")
        answer = final_messages[-1].text.strip()
        if not answer or final_messages[-1].tool_calls:
            return failure("empty_answer", "O modelo não apresentou uma resposta final.")
        actual_models = sorted(
            {
                m.response_metadata["model_name"]
                for m in final_messages
                if isinstance(m, AIMessage) and m.response_metadata.get("model_name")
            }
        )
        return {
            "ok": True,
            "answer": answer,
            "queries": trace,
            "model_calls": counter.calls,
            "model": settings.model,
            "actual_models": actual_models,
            "reference_date": reference_date.isoformat(),
        }
    except (ModelCallLimitExceededError, ToolCallLimitExceededError, GraphRecursionError):
        return failure(
            "agent_limit", "O agente atingiu o limite de chamadas sem concluir a resposta."
        )
    except Exception as exc:
        code, message = _provider_error(exc)
        return failure(code, message)
