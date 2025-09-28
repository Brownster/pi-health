from __future__ import annotations

from typing import List, Tuple, Any, Dict

try:  # optional
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


class AIProvider:
    def is_available(self) -> bool:
        raise NotImplementedError

    def generate(self, messages: List[Dict[str, Any]], *, temperature: float) -> Tuple[str, str]:
        raise NotImplementedError


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self._client = None
        if OpenAI is not None:
            try:
                self._client = OpenAI(api_key=api_key)
            except Exception as exc:  # pragma: no cover
                print(f"Warning: could not initialise OpenAI client: {exc}")

    def is_available(self) -> bool:
        return self._client is not None

    def generate(self, messages: List[Dict[str, Any]], *, temperature: float) -> Tuple[str, str]:
        if not self._client:
            return "", self.model
        response = self._client.responses.create(
            model=self.model,
            input=messages,
            temperature=temperature,
        )
        return (response.output_text or "").strip(), self.model


class OfflineProvider(AIProvider):
    def is_available(self) -> bool:
        return True

    def generate(self, messages: List[Dict[str, Any]], *, temperature: float) -> Tuple[str, str]:
        # The agent will still apply its own offline fallback rendering.
        return "", "offline-fallback"
