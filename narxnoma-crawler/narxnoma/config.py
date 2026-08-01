"""Environment-driven settings. Import this, never os.environ directly."""
import os
from dataclasses import dataclass

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Settings:
    dsn: str
    user_agent: str = USER_AGENT
    min_delay: float = 0.3
    max_delay: float = 0.6
    connect_timeout: int = 15
    read_timeout: int = 90


def load_settings() -> Settings:
    return Settings(
        dsn=os.environ.get("NARXNOMA_DSN", "postgresql://narxnoma:narxnoma@localhost:5432/narxnoma"),
        min_delay=float(os.environ.get("NARXNOMA_MIN_DELAY", "0.3")),
        max_delay=float(os.environ.get("NARXNOMA_MAX_DELAY", "0.6")),
    )
