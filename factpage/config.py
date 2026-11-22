from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=ROOT / "config.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
