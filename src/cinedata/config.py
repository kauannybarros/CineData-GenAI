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


def load_settings() -> Settings:
    """Carrega o .env sem sobrescrever variáveis já presentes no ambiente."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    db_path = Path(os.getenv("CINEDATA_DB_PATH", "cinerocket-db/cinerocket (1).db"))
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    model = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip()
    if not model:
        raise ValueError("Preencha OPENROUTER_MODEL no .env.")
    return Settings(
        db_path=db_path.resolve(),
        model=model,
        api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
    )
