from pathlib import Path
import yaml
from src.config.schema import AppConfig


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r") as f:
        data = yaml.safe_load(f)
    return AppConfig(**data)
