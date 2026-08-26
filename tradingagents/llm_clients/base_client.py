from abc import ABC, abstractmethod
from typing import Any, Optional
import logging
import time
import warnings

logger = logging.getLogger(__name__)

_TRANSIENT_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
_TRANSIENT_ERROR_MARKERS = (
    "capacity_error",
    "no backends available",
    "internalservererror",
    "internal server error",
    "service unavailable",
    "temporarily unavailable",
    "rate limit",
    "too many requests",
    "timeout",
    # A genuinely dropped local connection (the caller's own network, not the
    # provider) surfaces as openai.APIConnectionError / anthropic.
    # APIConnectionError -- verified live against both SDKs: no status_code
    # attribute at all, message is exactly "Connection error." Neither the
    # status-code check above nor the markers before this line could ever
    # match that, so a Wi-Fi blip during an LLM call used to fail the whole
    # run outright instead of retrying like every other transient failure.
    "connection error",
    "connection refused",
    "connection reset",
    "network is unreachable",
    "failed to establish a new connection",
    "remote end closed connection",
    "name or service not known",  # Linux/macOS DNS failure
    "getaddrinfo failed",  # Windows DNS failure
)


def normalize_content(response):
    """Normalize LLM response content to a plain string.

    Multiple providers (OpenAI Responses API, Google Gemini 3) return content
    as a list of typed blocks, e.g. [{'type': 'reasoning', ...}, {'type': 'text', 'text': '...'}].
    Downstream agents expect response.content to be a string. This extracts
    and joins the text blocks, discarding reasoning/metadata blocks.
    """
    content = response.content
    if isinstance(content, list):
        texts = [
            item.get("text", "") if isinstance(item, dict) and item.get("type") == "text"
            else item if isinstance(item, str) else ""
            for item in content
        ]
        response.content = "\n".join(t for t in texts if t)
    return response


def invoke_with_transient_retries(
    operation,
    *,
    label: str = "LLM invocation",
    max_attempts: int = 4,
    base_delay: float = 2.0,
):
    """Run an LLM operation with retries for provider-side transient errors."""
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if attempt >= max_attempts or not is_transient_llm_error(exc):
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "%s failed with transient provider error; retrying in %.1fs "
                "(attempt %s/%s): %s",
                label,
                delay,
                attempt + 1,
                max_attempts,
                exc,
            )
            time.sleep(delay)


def is_transient_llm_error(exc: Exception) -> bool:
    """Return True for LLM provider errors that are usually safe to retry."""
    status_code = getattr(exc, "status_code", None)
    if status_code in _TRANSIENT_STATUS_CODES:
        return True

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if response_status in _TRANSIENT_STATUS_CODES:
        return True

    text = str(exc).lower()
    return any(marker in text for marker in _TRANSIENT_ERROR_MARKERS)


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        self.model = model
        self.base_url = base_url
        self.kwargs = kwargs

    def get_provider_name(self) -> str:
        """Return the provider name used in warning messages."""
        provider = getattr(self, "provider", None)
        if provider:
            return str(provider)
        return self.__class__.__name__.removesuffix("Client").lower()

    def warn_if_unknown_model(self) -> None:
        """Warn when the model is outside the known list for the provider."""
        if self.validate_model():
            return

        warnings.warn(
            (
                f"Model '{self.model}' is not in the known model list for "
                f"provider '{self.get_provider_name()}'. Continuing anyway."
            ),
            RuntimeWarning,
            stacklevel=2,
        )

    @abstractmethod
    def get_llm(self) -> Any:
        """Return the configured LLM instance."""
        pass

    @abstractmethod
    def validate_model(self) -> bool:
        """Validate that the model is supported by this client."""
        pass
