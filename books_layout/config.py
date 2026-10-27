"""
Same database as the platform. Loads, in this order (first value wins):
  1. process env
  2. books-layout-detection/.env          (local overrides: POSTGRES_HOST=localhost, POSTGRES_PORT=5433)
  3. <backend>/shared/environment/.env.dev (or .env.prod when HOST=production) — DB name, user, password
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = PROJECT_DIR.parent


def _load() -> Path:
    load_dotenv(PROJECT_DIR / ".env", override=False)
    backend = Path(os.getenv("BACKEND_DIR", WORKSPACE_DIR / "CoachingQuiz-Ai-Plateform-v2"))
    if not backend.is_absolute():
        backend = (PROJECT_DIR / backend).resolve()
    name = ".env.prod" if os.getenv("HOST") == "production" else ".env.dev"
    env_file = backend / "shared" / "environment" / name
    if not env_file.exists():
        raise FileNotFoundError(f"Backend env file not found: {env_file}")
    load_dotenv(env_file, override=False)
    return backend


@dataclass(frozen=True)
class Settings:
    backend_dir: Path
    db_name: str
    db_user: str
    db_password: str
    db_host: str
    db_port: int

    @property
    def dsn(self) -> str:
        return (f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}")

    def safe_dsn(self) -> str:
        return f"postgresql://{self.db_user}:***@{self.db_host}:{self.db_port}/{self.db_name}"


def get_settings() -> Settings:
    backend = _load()
    return Settings(
        backend_dir=backend,
        db_name=os.environ["POSTGRES_DB"],
        db_user=os.environ["POSTGRES_USER"],
        db_password=os.environ["POSTGRES_PASSWORD"],
        db_host=os.environ["POSTGRES_HOST"],
        db_port=int(os.environ["POSTGRES_PORT"]),
    )
