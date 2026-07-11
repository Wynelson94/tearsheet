from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_bytes():  # type: ignore[no-untyped-def]
    def load(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()

    return load
