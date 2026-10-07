from pathlib import Path
from shutil import copytree

import pytest

from market_intelligence.storage import Store


@pytest.fixture
def scenario(tmp_path):
    original = Path(__file__).resolve().parents[1] / "scenarios" / "functional-beverage"
    target = tmp_path / "scenarios" / "functional-beverage"
    copytree(original, target)
    return target


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "runs")
