"""Model calls the workflow graphs make, behind one Protocol so tests run them without a provider."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from ops_metering import Usage

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
    """One person named by a levy or garnishment notice (c-057). Fields the notice does not state are empty."""

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
    async def extract_records(self, schema: str, text: str) -> list[dict[str, Any]]: ...


class PydanticAiModels:
    """The workflow model calls on Pydantic AI, each a one-shot agent with a typed output."""

    def __init__(self, model: Model) -> None:
        self._model = model

    async def classify(self, text: str, labels: list[str]) -> str:
        agent = Agent[None, str](
            self._model,
            deps_type=type(None),
            output_type=str,
            instructions=f"Classify the message into exactly one of these labels; reply with the label only: {labels}.",
        )
        out = (await _run(agent, text)).strip().lower()
        return next((label for label in labels if label in out), labels[-1])

    async def extract(self, category: str, name: str, text: str) -> Facts:
        agent = Agent[None, Facts](
            self._model,
            deps_type=type(None),
            output_type=Facts,
            instructions=(
                f"Extract the facts a {category} case needs from one attachment."
                " Leave a field empty when the attachment does not state it."
            ),
        )
        return await _run(agent, f"Attachment {name}:\n{text}")

    async def draft(self, email: str, evidence: str, feedback: str | None) -> str:
        agent = Agent[None, str](
            self._model,
            deps_type=type(None),
            output_type=str,
            instructions=(
                "You draft replies for Northfield Bank's Card Services team. Write a short, plain reply to the"
                " customer that acknowledges the dispute, states what the evidence shows and the next step."
                " Do not promise an outcome."
            ),
        )
        prompt = f"Customer email:\n{email}\n\nEvidence from the attachments:\n{evidence}"
        if feedback:
            prompt += f"\n\nA reviewer graded the previous draft and said: {feedback}\nWrite an improved draft."
        return await _run(agent, prompt)

    async def grade(self, email: str, draft: str) -> Grade:
        agent = Agent[None, Grade](
            self._model,
            deps_type=type(None),
            output_type=Grade,
            instructions=(
                "You grade a bank's draft reply. Score 0 to 1: does it answer the customer's email, state the evidence"
                " correctly, give the next step and avoid promising an outcome? Give one sentence of feedback."
            ),
        )
        return await _run(agent, f"Email:\n{email}\n\nDraft:\n{draft}")

    async def extract_records(self, schema: str, text: str) -> list[dict[str, Any]]:
        """Every record of `schema` (RECORD_SCHEMAS) the text states, one dict per record, in the text's order."""
        output = RECORD_SCHEMAS.get(schema)
        if output is None:
            raise ValueError(f"Unknown record schema {schema}; one of {sorted(RECORD_SCHEMAS)}.")
        agent = Agent[None, BaseModel](
            self._model,
            deps_type=type(None),
            output_type=output,
            instructions=(
                f"Extract every {schema} record the text states, one record per entry, in the order they appear."
                " Copy values as written. Leave a field empty when the text does not state it. Never invent a record."
            ),
        )
        found = await _run(agent, text)
        records: list[Any] = list(found.model_dump(mode="json")["records"])
        return [dict(r) for r in records]


async def _run[T](agent: Agent[None, T], prompt: str) -> T:
    """Runs one workflow call and reports its usage to the metering wrapper around it (`metering.py`)."""
    result = await agent.run(prompt)
    u = result.usage
    report_usage(Usage(u.input_tokens, u.output_tokens, max(u.requests, 1)))
    return result.output
