"""Configurações locais, sem chamadas à API."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    db_path: Path
    model: str
    api_key: str = field(repr=False)
    max_model_calls: int = 3


def load_settings() -> Settings:
    """Carrega o .env sem sobrescrever variáveis já presentes no ambiente."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    db_path = Path(os.getenv("CINEDATA_DB_PATH", "cinerocket-db/cinerocket (1).db"))
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    model = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip()
    if not model:
        raise ValueError("Preencha OPENROUTER_MODEL no .env.")
    try:
        max_model_calls = int(os.getenv("CINEDATA_MAX_MODEL_CALLS", "3"))
    except ValueError as exc:
        raise ValueError("CINEDATA_MAX_MODEL_CALLS deve ser um inteiro entre 2 e 5.") from exc
    if not 2 <= max_model_calls <= 5:
        raise ValueError("CINEDATA_MAX_MODEL_CALLS deve estar entre 2 e 5.")
    return Settings(
        db_path=db_path.resolve(),
        model=model,
        api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        max_model_calls=max_model_calls,
    )
