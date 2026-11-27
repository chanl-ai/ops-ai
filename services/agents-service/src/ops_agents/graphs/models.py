"""Model calls the workflow graphs make, behind one Protocol so tests run them without a provider."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from ops_agent_kernel import structured
from ops_agent_kernel.contract import ModelEndpoint
from ops_metering import Usage
from ops_service_kit.http import Json

from .usage import report_usage


class Facts(BaseModel):
    summary: str
    amount: str | None = None
    date: str | None = None
    merchant: str | None = None


class Grade(BaseModel):
    score: float = Field(ge=0, le=1)
    feedback: str


class PersonRecord(BaseModel):
    """One person named by a levy or garnishment notice. Fields the notice does not state are empty."""

    name: str
    address: str = ""
    ssn_last4: str = ""
    amount: str = ""
    court: str = ""
    case_no: str = ""


class PersonRecords(BaseModel):
    records: list[PersonRecord]


# Record schemas `extract_records` knows by name; a graph definition names one, never a Python type.
RECORD_SCHEMAS: dict[str, type[BaseModel]] = {"persons": PersonRecords}


class GraphModels(Protocol):
    async def classify(self, text: str, labels: list[str]) -> str: ...
    async def extract(self, category: str, name: str, text: str) -> Facts: ...
    async def draft(self, email: str, evidence: str, feedback: str | None) -> str: ...
    async def grade(self, email: str, draft: str) -> Grade: ...
    async def extract_records(self, schema: str, text: str) -> list[Json]: ...


class GatewayModels:
    """The workflow model calls, each one structured call through the model gateway (ops_agent_kernel.structured),
    its answer validated against the output type."""

    def __init__(self, model: ModelEndpoint) -> None:
        self._model = model

    async def classify(self, text: str, labels: list[str]) -> str:
        system = f"Classify the message into exactly one of these labels; reply with the label only: {labels}."
        out = (await self._text(system, text)).strip().lower()
        return next((label for label in labels if label in out), labels[-1])

    async def extract(self, category: str, name: str, text: str) -> Facts:
        system = (
            f"Extract the facts a {category} case needs from one attachment."
            " Leave a field empty when the attachment does not state it."
        )
        return await self._typed(Facts, system, f"Attachment {name}:\n{text}")

    async def draft(self, email: str, evidence: str, feedback: str | None) -> str:
        system = (
            "You draft replies for Harbor & Pine Bank's Card Services team. Write a short, plain reply to the"
            " customer that acknowledges the dispute, states what the evidence shows and the next step."
            " Do not promise an outcome."
        )
        prompt = f"Customer email:\n{email}\n\nEvidence from the attachments:\n{evidence}"
        if feedback:
            prompt += f"\n\nA reviewer graded the previous draft and said: {feedback}\nWrite an improved draft."
        return await self._text(system, prompt)

    async def grade(self, email: str, draft: str) -> Grade:
        system = (
            "You grade a bank's draft reply. Score 0 to 1: does it answer the customer's email, state the evidence"
            " correctly, give the next step and avoid promising an outcome? Give one sentence of feedback."
        )
        return await self._typed(Grade, system, f"Email:\n{email}\n\nDraft:\n{draft}")

    async def extract_records(self, schema: str, text: str) -> list[Json]:
        """Every record of `schema` (RECORD_SCHEMAS) the text states, one dict per record, in the text's order."""
        output = RECORD_SCHEMAS.get(schema)
        if output is None:
            raise ValueError(f"Unknown record schema {schema}; one of {sorted(RECORD_SCHEMAS)}.")
        system = (
            f"Extract every {schema} record the text states, one record per entry, in the order they appear."
            " Copy values as written. Leave a field empty when the text does not state it. Never invent a record."
        )
        found = await self._typed(output, system, text)
        records: list[Any] = list(found.model_dump(mode="json")["records"])
        return [dict(r) for r in records]

    async def _text(self, system: str, prompt: str) -> str:
        said = await structured.ask(self._model, system=system, prompt=prompt, purpose="turn")
        _report(said)
        return said.text

    async def _typed[T: BaseModel](self, output: type[T], system: str, prompt: str) -> T:
        said = await structured.ask(
            self._model, system=system, prompt=prompt, purpose="turn", schema=output.model_json_schema()
        )
        _report(said)
        try:
            return output.model_validate(said.value)
        except ValidationError as e:
            raise ModelAnswerInvalid(f"The model's answer did not match {output.__name__}: {e}") from e


class ModelAnswerInvalid(Exception):
    """A workflow call answered outside its output type."""


def _report(said: structured.Answered) -> None:
    """Reports one workflow call's usage to the metering wrapper around it (`metering.py`)."""
    u = said.usage
    report_usage(Usage(u.input_tokens, u.output_tokens, max(u.requests, 1)))
