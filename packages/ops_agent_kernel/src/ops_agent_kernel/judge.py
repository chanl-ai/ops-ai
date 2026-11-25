"""A model judge: one structured call that says whether evidence meets a check written in words, with a one-line
reason. Eval checks of type `judge` use it, and so do skill step checks written as a sentence (`steps.to_judge`).
Through models-service the call runs on its own alias, `judge`, so an operator can give judging a different model from
the answering one; while that alias is not bound it runs on the turn's model. The judge is given the check and the
evidence only, never the agent's instructions, so what the agent was told cannot argue for its own reply. A call that
fails, or an answer outside the schema, is a verdict of None: the judge did not answer, and a caller scores that as a
fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.output import StructuredDict

from ops_service_kit.http import Json

from .aliases import preferred
from .ports import BudgetReachedError, ModelSource
from .types import TokenUsage

JUDGE_ALIAS = "judge"
# The scripted models answer a judge call by this opening line (tests/conftest.py, the fake OpenAI's script.json).
PROMPT_HEAD = "Judge this check:"
INSTRUCTIONS = (
    "You judge whether the evidence meets one check. Read the check as a person would and judge the meaning, not "
    "single words. Answer passed true only when the evidence clearly meets the check, and give the reason in one "
    "short sentence."
)
SCHEMA: Json = {
    "type": "object",
    "properties": {"passed": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["passed", "reason"],
}


@dataclass(frozen=True)
class Verdict:
    """`passed` is None when the judge did not answer; `usage` is what the call spent, zero when it raised.
    `confidence` is not asked for yet and stays None."""

    passed: bool | None
    reason: str
    usage: TokenUsage
    confidence: float | None = None


def model_for(source: ModelSource | None, turn_model: Model) -> Model:
    """`judge` through models-service, or the turn's model while that alias does not exist."""
    return preferred(source, JUDGE_ALIAS, turn_model)


def prompt(check: str, evidence: str) -> str:
    return f"{PROMPT_HEAD}\n{check}\n\nEvidence:\n{evidence}"


async def verdict(model: Model, check: str, evidence: str) -> Verdict:
    agent = Agent[None, Any](
        model,
        deps_type=type(None),
        output_type=StructuredDict(SCHEMA, name="final_result"),
        instructions=INSTRUCTIONS,
        retries=0,
    )
    try:
        result = await agent.run(prompt(check, evidence))
    except BudgetReachedError:
        raise  # the run's budget is spent, which is not a judge that failed
    except Exception as e:  # any failure of the call is a judge that did not answer
        return Verdict(None, f"The judge did not answer: {type(e).__name__}: {e}", TokenUsage())
    u = result.usage
    spent = TokenUsage(u.input_tokens, u.output_tokens, u.requests)
    found: list[Any] = list(Draft202012Validator(SCHEMA).iter_errors(result.output))  # pyright: ignore[reportUnknownMemberType]
    if found:
        return Verdict(None, f"The judge did not answer within its schema: {found[0].message}", spent)
    return Verdict(bool(result.output["passed"]), str(result.output["reason"]), spent)
