import pytest

from app.config import Settings
from app.memory import Memory


@pytest.fixture
def settings(tmp_path):
    return Settings("test-openai", "test-tavily", database=str(tmp_path / "memory.sqlite3"))


@pytest.fixture
def memory(settings):
    return Memory(settings.database)
