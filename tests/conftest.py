"""Conftest para pytest.

IMPORTANTE: setea MOCK_LLM=1 ANTES de cualquier import de `app.*`.
Si en algun test puntual queres backend real, hace
`monkeypatch.delenv("MOCK_LLM")` DENTRO de ese test (antes del import).
"""

import os
import sys
from pathlib import Path

# Project root en sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# MOCK pin ANTES de cualquier import de app
os.environ.setdefault("MOCK_LLM", "1")

import pytest  # noqa: E402


@pytest.fixture
def project_root() -> Path:
    return _ROOT


@pytest.fixture
def sample_prompts_path(project_root: Path) -> Path:
    return project_root / "benchmarks" / "prompts_es.json"


@pytest.fixture
def example_model_config_path(project_root: Path) -> Path:
    return project_root / "configs" / "models.example.json"