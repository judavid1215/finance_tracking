import pytest

from finanzas import morningstar


@pytest.fixture(autouse=True)
def _sin_morningstar(monkeypatch):
    """Ningún test toca la red: la descarga de Morningstar falla salvo que el test la sustituya."""

    def sin_red(*args, **kwargs):
        raise OSError("sin red en los tests")

    monkeypatch.setattr(morningstar.urllib.request, "urlopen", sin_red)
