"""OpenAI API-Client."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from src.models.schemas import Settings

logger = logging.getLogger(__name__)


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMClient:
    def __init__(self, settings: Settings, *, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY nicht gesetzt. "
                "Bitte Umgebungsvariable oder GitHub Secret hinterlegen."
            )
        self._client = OpenAI(api_key=key)
        self._settings = settings
        self.usage = LLMUsage()

    @property
    def _llm_config(self) -> dict[str, Any]:
        return self._settings.llm or {}

    def _max_retries(self) -> int:
        return int(self._llm_config.get("max_retries", 2))

    def _temperature(self) -> float:
        return float(self._llm_config.get("temperature", 0.3))

    def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        """LLM-Aufruf mit JSON-Antwort. Retry bei Parse-Fehlern."""
        last_error: Exception | None = None
        retries = self._max_retries()

        for attempt in range(retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=self._temperature(),
                )
                usage = response.usage
                if usage:
                    self.usage.prompt_tokens += usage.prompt_tokens or 0
                    self.usage.completion_tokens += usage.completion_tokens or 0
                    self.usage.total_tokens += usage.total_tokens or 0

                content = response.choices[0].message.content or "{}"
                return json.loads(content)
            except (json.JSONDecodeError, IndexError, AttributeError) as exc:
                last_error = exc
                logger.warning(
                    "JSON-Parse-Fehler (Versuch %d/%d): %s",
                    attempt + 1,
                    retries + 1,
                    exc,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM-Fehler (Versuch %d/%d): %s",
                    attempt + 1,
                    retries + 1,
                    exc,
                )

        raise RuntimeError(f"LLM-Aufruf fehlgeschlagen: {last_error}")
