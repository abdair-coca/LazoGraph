"""Grounded local, Ollama, and explicit hosted provider implementations."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

from lazograph.domain.answer import Evidence, ProviderOutput


class ProviderError(RuntimeError):
    """Inference provider failed without changing persisted knowledge."""


Transport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise ProviderError(f"Provider request failed: {exc}") from exc


def _safe_context(context: dict[str, Any]) -> dict[str, Any]:
    """Whitelist metadata; message content travels only through Evidence."""
    return {
        key: context[key]
        for key in (
            "identity_type",
            "message_count",
            "first_seen",
            "last_seen",
            "relationship_types",
            "wiki_pages",
        )
        if key in context
    }


def _prompt(
    question: str,
    participant: str,
    evidence: Sequence[Evidence],
    context: dict[str, Any],
    language: str,
) -> str:
    evidence_payload = [
        {
            "message_id": item.message_id,
            "sender": item.sender,
            "timestamp": item.timestamp,
            "excerpt": item.excerpt,
            "source_type": item.source_type,
            "record_kind": item.record_kind,
            "authority": item.authority,
            "authored_by": item.authored_by,
            "evidence_confidence": item.confidence,
            "imported_at": item.imported_at,
        }
        for item in evidence
    ]
    return (
        "Answer only from EVIDENCE. Never treat CONTEXT metadata as proof. "
        "Return strict JSON with keys text, citation_ids, confidence, abstained. "
        "Every factual claim must cite one or more message_id values. "
        "Abstain when evidence is insufficient. "
        f"Answer language: {language}.\n"
        f"PARTICIPANT: {participant}\n"
        f"QUESTION: {question}\n"
        f"CONTEXT: {json.dumps(_safe_context(context), ensure_ascii=False)}\n"
        f"EVIDENCE: {json.dumps(evidence_payload, ensure_ascii=False)}"
    )


def _parse_provider_json(content: str) -> ProviderOutput:
    cleaned = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    try:
        payload = json.loads(cleaned)
        text = str(payload["text"]).strip()
        citation_ids = tuple(str(item) for item in payload.get("citation_ids", []))
        confidence = float(payload.get("confidence", 0.0))
        abstained = bool(payload.get("abstained", False))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ProviderError("Provider returned invalid grounded-answer JSON.") from exc
    if not text:
        raise ProviderError("Provider returned an empty answer.")
    return ProviderOutput(
        text=text,
        citation_ids=citation_ids,
        confidence=max(0.0, min(1.0, confidence)),
        abstained=abstained,
    )


class LocalExtractiveProvider:
    """Offline privacy-first answer: concise synthesis of selected verbatim evidence."""

    name = "local"
    hosted = False

    def generate(
        self,
        question: str,
        participant: str,
        evidence: Sequence[Evidence],
        context: dict[str, Any],
        *,
        language: str,
    ) -> ProviderOutput:
        del question, context
        if not evidence:
            text = (
                f"No encontré evidencia suficiente sobre {participant}."
                if language == "es"
                else f"I found insufficient evidence about {participant}."
            )
            return ProviderOutput(text, (), 0.0, abstained=True)

        selected = tuple(evidence[:3])
        has_manual_context = any(item.source_type == "user_context" for item in selected)
        if language == "es":
            lead = (
                f"Según la evidencia guardada sobre {participant}:"
                if has_manual_context else f"Según mensajes de {participant}:"
            )
        else:
            lead = (
                f"According to stored evidence about {participant}:"
                if has_manual_context else f"According to {participant}'s messages:"
            )
        lines = [lead]
        for item in selected:
            lines.append(f'- “{item.excerpt}” [{item.message_id}]')
        confidence = sum(item.score for item in selected) / len(selected)
        return ProviderOutput(
            text="\n".join(lines),
            citation_ids=tuple(item.message_id for item in selected),
            confidence=max(0.0, min(1.0, confidence)),
        )


class OllamaProvider:
    """Local generative provider through Ollama's loopback HTTP API."""

    name = "ollama"
    hosted = False

    def __init__(
        self,
        *,
        model: str | None = None,
        url: str | None = None,
        transport: Transport = _post_json,
    ):
        self.model = model or os.environ.get("LAZOGRAPH_OLLAMA_MODEL", "llama3.2")
        self.url = url or os.environ.get(
            "LAZOGRAPH_OLLAMA_URL",
            "http://127.0.0.1:11434/api/chat",
        )
        self.transport = transport

    def generate(
        self,
        question: str,
        participant: str,
        evidence: Sequence[Evidence],
        context: dict[str, Any],
        *,
        language: str,
    ) -> ProviderOutput:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [{
                "role": "user",
                "content": _prompt(question, participant, evidence, context, language),
            }],
        }
        response = self.transport(self.url, {}, payload)
        try:
            content = response["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ProviderError("Ollama returned an unexpected response.") from exc
        return _parse_provider_json(str(content))


class HostedProvider:
    """Explicit OpenAI-compatible hosted boundary with evidence-only payloads."""

    name = "hosted"
    hosted = True

    def __init__(
        self,
        *,
        model: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        transport: Transport = _post_json,
    ):
        self.model = model or os.environ.get("LAZOGRAPH_HOSTED_MODEL", "")
        self.url = url or os.environ.get("LAZOGRAPH_HOSTED_URL", "")
        self.api_key = api_key or os.environ.get("LAZOGRAPH_HOSTED_API_KEY", "")
        self.transport = transport

    def generate(
        self,
        question: str,
        participant: str,
        evidence: Sequence[Evidence],
        context: dict[str, Any],
        *,
        language: str,
    ) -> ProviderOutput:
        if not self.url or not self.model or not self.api_key:
            raise ProviderError(
                "Hosted provider requires LAZOGRAPH_HOSTED_URL, "
                "LAZOGRAPH_HOSTED_MODEL, and LAZOGRAPH_HOSTED_API_KEY."
            )
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{
                "role": "user",
                "content": _prompt(question, participant, evidence, context, language),
            }],
        }
        response = self.transport(
            self.url,
            {"Authorization": f"Bearer {self.api_key}"},
            payload,
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Hosted provider returned an unexpected response.") from exc
        return _parse_provider_json(str(content))
