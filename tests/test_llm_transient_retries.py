import pytest

from tradingagents.llm_clients.base_client import (
    invoke_with_transient_retries,
    is_transient_llm_error,
)


class ProviderError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.unit
def test_capacity_error_is_transient():
    exc = ProviderError(
        "InternalServerError: Error code: 503 - "
        "{'error': {'metadata': {'raw': '{\"error\":{\"message\":\"No backends available\","
        "\"type\":\"capacity_error\"}}'}}}",
        status_code=503,
    )

    assert is_transient_llm_error(exc)


@pytest.mark.unit
def test_invoke_with_transient_retries_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("tradingagents.llm_clients.base_client.time.sleep", lambda _: None)
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ProviderError("No backends available", status_code=503)
        return "ok"

    assert invoke_with_transient_retries(operation, max_attempts=4) == "ok"
    assert attempts["count"] == 3


@pytest.mark.unit
def test_invoke_with_transient_retries_does_not_retry_non_transient():
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        raise ProviderError("invalid request", status_code=400)

    with pytest.raises(ProviderError):
        invoke_with_transient_retries(operation, max_attempts=4)

    assert attempts["count"] == 1
