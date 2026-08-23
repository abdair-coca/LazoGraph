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
            "answer_mode",
            "entities",
            "relationship_hops",
            "relationship_path",
            "observed_period",
            "wiki_relationship_mentions",
            "active_plans",
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
        "Return strict JSON with keys text, citation_ids, confidence, abstained, suggestions, "
        "missing_information. suggestions and missing_information must be arrays of strings. "
        "Every factual claim must cite one or more message_id values. "
        "Every suggestion justified by evidence must include its citation marker. "
        "Label facts, inferences, suggestions, and missing information separately in text. "
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
        raw_suggestions = payload.get("suggestions", [])
        raw_missing_information = payload.get("missing_information", [])
        if not isinstance(raw_suggestions, list) or not isinstance(raw_missing_information, list):
            raise TypeError("suggestions and missing_information must be arrays")
        suggestions = tuple(str(item).strip() for item in raw_suggestions if str(item).strip())
        missing_information = tuple(
            str(item).strip()
            for item in raw_missing_information
            if str(item).strip()
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ProviderError("Provider returned invalid grounded-answer JSON.") from exc
    if not text:
        raise ProviderError("Provider returned an empty answer.")
    return ProviderOutput(
        text=text,
        citation_ids=citation_ids,
        confidence=max(0.0, min(1.0, confidence)),
        abstained=abstained,
        suggestions=suggestions,
        missing_information=missing_information,
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
        del question
        if not evidence:
            text = (
                f"No encontré evidencia suficiente sobre {participant}."
                if language == "es"
                else f"I found insufficient evidence about {participant}."
            )
            return ProviderOutput(text, (), 0.0, abstained=True)

        if context.get("answer_mode") == "suggestions":
            return self._suggestion_output(participant, evidence, context, language)

        if context.get("answer_mode") == "relationship":
            graph_items = [
                item for item in evidence
                if item.record_kind == "effective_relationship"
            ]
            if not graph_items:
                text = (
                    "No encontré una ruta relacional efectiva respaldada."
                    if language == "es"
                    else "I found no supported effective relationship path."
                )
                return ProviderOutput(text, (), 0.0, abstained=True)
            path = context.get("relationship_path", [])
            direct = context.get("relationship_hops") == 1
            relation_types = ", ".join(
                dict.fromkeys(
                    str(item.get("label") or item.get("type", "")).replace("_", " ")
                    for item in path
                )
            )
            markers = " ".join(f"[{item.message_id}]" for item in graph_items)
            if language == "es":
                text = (
                    f"El grafo efectivo respalda una conexión {'directa' if direct else 'indirecta'} "
                    f"mediante {relation_types}; no infiero una relación adicional fuera de esos "
                    f"hechos observados. {markers}"
                )
            else:
                text = (
                    f"The effective graph supports a {'direct' if direct else 'indirect'} connection "
                    f"through {relation_types}; I do not infer any additional relationship beyond "
                    f"those observed facts. {markers}"
                )
            return ProviderOutput(
                text=text,
                citation_ids=tuple(item.message_id for item in graph_items),
                confidence=min(item.score for item in graph_items),
            )

        selected = tuple(evidence[:3])
        has_manual_context = any(
            item.source_type in {"user_context", "user_correction"}
            for item in selected
        )
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

    @staticmethod
    def _suggestion_output(
        participant: str,
        evidence: Sequence[Evidence],
        context: dict[str, Any],
        language: str,
    ) -> ProviderOutput:
        """Produce deterministic, evidence-only suggestion wording without persistence."""
        markers = " ".join(f"[{item.message_id}]" for item in evidence)
        preference_items = [
            item for item in evidence
            if item.source_type in {"user_context", "user_correction"}
            or re.search(
                r"\b(?:like|likes|love|loves|prefer|prefers|favorite|enjoy|enjoys|gusta|encanta|prefiere|favorit[oa])\b",
                item.excerpt,
                re.IGNORECASE,
            )
        ]
        if not preference_items:
            text = (
                f"No encontré contexto suficiente para sugerir un regalo para {participant}."
                if language == "es"
                else f"I found insufficient context to suggest a gift for {participant}."
            )
            return ProviderOutput(text, (), 0.0, abstained=True)

        joined = " ".join(item.excerpt.casefold() for item in preference_items)
        gift = (
            "un regalo relacionado con el interés expresado"
            if language == "es"
            else "a gift connected to the stated interest"
        )
        if any(word in joined for word in ("book", "books", "reading", "libro", "libros", "leer")):
            gift = "un libro o regalo relacionado con la lectura" if language == "es" else "a book or reading-related gift"
        elif any(word in joined for word in ("coffee", "café", "cafe")):
            gift = "café de calidad o un regalo relacionado con café" if language == "es" else "quality coffee or a café-related gift"
        elif any(word in joined for word in ("music", "música", "guitar", "instrument")):
            gift = "un regalo relacionado con la música" if language == "es" else "a music-related gift"
        elif any(word in joined for word in ("paint", "painting", "art", "pintar", "arte")):
            gift = "materiales de arte o un regalo relacionado con el arte" if language == "es" else "art supplies or an art-related gift"
        elif any(word in joined for word in ("travel", "viaj", "trip", "viaje")):
            gift = "un regalo práctico relacionado con viajes" if language == "es" else "a practical travel-related gift"

        plan_items = [item for item in evidence if item.record_kind == "plan_transition"]
        correction_items = [item for item in evidence if item.source_type == "user_correction"]
        if language == "es":
            facts = "Hechos conocidos:\n" + "\n".join(
                f"- {item.excerpt} [{item.message_id}]" for item in preference_items
            )
            inference = (
                f"Inferencia:\n- Un regalo relacionado con esos intereses puede ser pertinente. {markers}"
            )
            suggestion = f"Sugerencia:\n- Considera {gift}. {markers}"
            if plan_items:
                suggestion += f" El plan activo también puede orientar el momento o contexto: {plan_items[0].excerpt} [{plan_items[0].message_id}]"
            if correction_items:
                suggestion += f" Se respeta la corrección activa y no se usa como preferencia lo retractado. {markers}"
            missing = (
                "Información faltante:\n- Presupuesto, ocasión y restricciones personales."
            )
        else:
            facts = "Known facts:\n" + "\n".join(
                f"- {item.excerpt} [{item.message_id}]" for item in preference_items
            )
            inference = (
                f"Inference:\n- A gift related to those stated interests may be relevant. {markers}"
            )
            suggestion = f"Suggestion:\n- Consider {gift}. {markers}"
            if plan_items:
                suggestion += f" The active plan may also guide timing or context: {plan_items[0].excerpt} [{plan_items[0].message_id}]"
            if correction_items:
                suggestion += f" The active correction is respected; retracted knowledge is not used as a preference. {markers}"
            missing = "Missing information:\n- Budget, occasion, and personal constraints."
        text = "\n".join((facts, inference, suggestion, missing))
        return ProviderOutput(
            text=text,
            citation_ids=tuple(item.message_id for item in evidence),
            confidence=min(item.score for item in evidence),
            suggestions=(suggestion, ),
            missing_information=(
                "presupuesto, ocasión y restricciones personales"
                if language == "es" else "budget, occasion, and personal constraints",
            ),
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
