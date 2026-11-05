import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from iomt_gateway.config import load  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    c = load(ROOT / "config.example.toml")
    c.db_path = str(tmp_path / "gw.db")
    c.cloud.enabled = False
    return c
