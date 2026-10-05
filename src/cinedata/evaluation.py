"""Avaliação reproduzível de consultas de referência e resultados do agente."""

import hashlib
import json
import math
import time
from datetime import date
from pathlib import Path
from typing import Any

from cinedata.agent import ask_question
from cinedata.config import Settings
from cinedata.database import execute_query
from cinedata.evaluation_cases import CASES


def compare_results(expected: dict, actual: dict) -> tuple[bool, str]:
    """Compara ordem, quantidade e valores; aceita arredondamento até 0,011."""
    if not actual.get("ok"):
        return False, "Consulta do agente falhou."
    if actual.get("truncated") or actual.get("shortened_cells"):
        return False, "Resultado incompleto ou abreviado."
    if len(expected["columns"]) != len(actual["columns"]):
        return False, "Quantidade de colunas diferente da referência."
    if len(expected["rows"]) != len(actual["rows"]):
        return False, "Quantidade de linhas diferente da referência."
    for i, (expected_row, actual_row) in enumerate(
        zip(expected["rows"], actual["rows"], strict=True)
    ):
        if len(expected_row) != len(actual_row):
            return False, f"Quantidade de células divergente na linha {i + 1}."
        for j, (a, b) in enumerate(zip(expected_row, actual_row, strict=True)):
            equal = a == b
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                equal = math.isclose(a, b, rel_tol=1e-12, abs_tol=0.011)
            if not equal:
                return False, f"Valor ou ordem divergente na linha {i + 1}, coluna {j + 1}."
    return True, "Linhas e valores coincidem com a referência."


def compare_agent_queries(expected: dict, agent: dict) -> tuple[bool, str, str | None]:
    """Consultas auxiliares não substituem evidências que coincidem com a referência."""
    candidates = [q for q in agent.get("queries", []) if q.get("result", {}).get("ok")]
    reason = "Nenhuma consulta bem-sucedida."
    for query in candidates:
        passed, reason = compare_results(expected, query["result"])
        if passed:
            return True, reason, query["id"]
    return False, reason, None


def rescore_report(path: Path) -> dict:
    """Reavalia dados registrados, sem enviar requisições ou mudar consultas."""
    report = json.loads(path.read_text(encoding="utf-8"))
    for case in report["cases"]:
        if case.get("agent", {}).get("ok") and case["expected"]["ok"]:
            passed, reason, query_id = compare_agent_queries(case["expected"], case["agent"])
            case["status"] = "passed" if passed else "mismatch"
            case["reason"] = reason
            case["matched_query_id"] = query_id
    report["comparison_version"] = 2
    report["summary"] = {
        status: sum(c["status"] == status for c in report["cases"])
        for status in sorted({c["status"] for c in report["cases"]})
    }
    write_report(report, path)
    return report


def run_evaluation(
    settings: Settings,
    reference_date: date,
    *,
    live: bool = False,
    max_calls: int = 10,
    case_ids: list[str] | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if max_calls < 0:
        raise ValueError("max_calls não pode ser negativo.")
    if case_ids and set(case_ids) - {case.id for case in CASES}:
        raise ValueError("Identificador de caso desconhecido.")
    selected = [c for c in CASES if not case_ids or c.id in case_ids]
    try:
        start = reference_date.replace(year=reference_date.year - 5)
    except ValueError:
        start = reference_date.replace(year=reference_date.year - 5, day=28)
    with settings.db_path.open("rb") as database:
        fingerprint = hashlib.file_digest(database, "sha256").hexdigest()
    report: dict[str, Any] = {
        "mode": "live" if live else "references",
        "reference_date": reference_date.isoformat(),
        "database_sha256": fingerprint,
        "model": settings.model if live else None,
        "max_model_calls_per_question": settings.max_model_calls,
        "comparison_version": 2,
        "call_budget": max_calls if live else 0,
        "model_calls": 0,
        "cases": [],
    }
    stop = False
    for case in selected:
        sql = case.sql.format(
            reference_date=reference_date.isoformat(), five_years_ago=start.isoformat()
        )
        before = time.monotonic()
        expected = execute_query(settings.db_path, sql)
        entry = {
            "id": case.id,
            "category": case.category,
            "question": case.question,
            "reference_sql": sql,
            "expected": expected,
            "reference_seconds": round(time.monotonic() - before, 3),
        }
        report["cases"].append(entry)
        if not expected["ok"] or expected["truncated"] or expected["shortened_cells"]:
            entry["status"] = "reference_error"
        elif not live:
            entry["status"] = "reference_ok"
        elif stop or max_calls - report["model_calls"] < settings.max_model_calls:
            entry["status"] = "skipped"
        else:
            # Contrato de saída, sem fornecer SQL ou respostas esperadas ao modelo.
            question = case.question + (
                "\nPara conferência, a consulta final deve retornar somente estas colunas, "
                "nesta ordem: " + ", ".join(expected["columns"]) + ". "
                "Use os nomes como aliases; mantenha a ordem de linhas solicitada."
            )
            before = time.monotonic()
            actual = ask_question(settings, question, reference_date=reference_date)
            report["model_calls"] += actual["model_calls"]
            entry["agent"] = actual
            entry["agent_seconds"] = round(time.monotonic() - before, 3)
            if not actual["ok"]:
                entry["status"] = "agent_error"
                entry["reason"] = actual["error"]["code"]
                stop = actual["error"]["code"] in {
                    "missing_key",
                    "rate_limit",
                    "authentication_error",
                    "billing_error",
                    "connection_error",
                }
            else:
                passed, reason, query_id = compare_agent_queries(expected, actual)
                entry["status"] = "passed" if passed else "mismatch"
                entry["reason"] = reason
                entry["matched_query_id"] = query_id
        if output_path:
            write_report(report, output_path)
        print(f"{case.id}: {entry['status']}", flush=True)
    report["summary"] = {
        status: sum(c["status"] == status for c in report["cases"])
        for status in sorted({c["status"] for c in report["cases"]})
    }
    if output_path:
        write_report(report, output_path)
    return report


def write_report(report: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
