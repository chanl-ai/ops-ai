"""Personal data masked in what people see: SSNs and their last four, card and account
numbers, emails and phone numbers. The model still sees the real values, so a turn can chain calls on an account id;
only what a turn shows and returns is masked: its streamed text, its answer, its structured output, the tool calls
it records and the passages it cites. Names are not masked: no pattern finds them without a model call.

A pattern is masked whole, never a part of it: streamed text is held back by HOLD characters and cut only at
whitespace, so a number arriving across two chunks is masked as one, and an email (no whitespace in it) is never cut.
"""

from __future__ import annotations

from dataclasses import replace

from ops_contracts.skill_run import RunningSkill, SkillProgram, SkillRunState, SubRun

# The patterns and whole-text masking live in ops_pii, which services that are not agents use too (documents' examples);
# they are re-exported here so every caller of ops_agent_kernel.pii is unchanged.
from ops_pii import HOLD, StreamMasker, holds_placeholder, mask, masked

from .types import CitationRef, ToolCallRecord, TurnResult

__all__ = [
    "HOLD",
    "StreamMasker",
    "mask",
    "masked",
    "masked_call",
    "masked_citations",
    "masked_result",
    "masked_run",
    "remarked",
]


def masked_call(rec: ToolCallRecord) -> ToolCallRecord:
    """A copy of the call as it is shown and stored; the kernel's own record, which the model's history holds, is not
    changed."""
    return replace(rec, input=masked(rec.input), output=masked(rec.output), view=masked(rec.view))


def masked_citations(cited: list[CitationRef]) -> list[CitationRef]:
    """The cited passages as people see them: a knowledge base can hold a customer's details as well as a tool."""
    return [replace(c, passage=replace(c.passage, text=mask(c.passage.text))) for c in cited]


def masked_result(result: TurnResult) -> TurnResult:
    """The turn's answer as people see it. The interrupt is left as it is: a resumed turn continues from its history."""
    return replace(
        result,
        text=mask(result.text),
        output=masked(result.output),
        tool_calls=[masked_call(c) for c in result.tool_calls],
        citations=masked_citations(result.citations),
        run=masked_run(result.run) if result.run is not None else None,
    )


def _masked_program(p: SkillProgram) -> SkillProgram:
    steps = [
        s.model_copy(
            update={
                "do": mask(s.do),
                "check": s.check.model_copy(update={"text": mask(s.check.text)}) if s.check is not None else None,
            }
        )
        for s in p.steps
    ]
    return p.model_copy(
        update={
            "not_when": mask(p.not_when),
            "steps": steps,
            "exit": {k: mask(v) for k, v in p.exit.items()},
            "returns": [r.model_copy(update={"description": mask(r.description)}) for r in p.returns],
            "success": [mask(line) for line in p.success],
        }
    )


def _masked_frame[F: (RunningSkill, SubRun)](f: F) -> F:
    inputs = {k: mask(v) for k, v in f.inputs.items()}
    # Named so a later reply's rule does not compare the placeholder. Names already marked stay: a placeholder masks
    # to itself, so it no longer shows as changed.
    hidden = sorted({*f.masked_inputs, *(k for k, v in f.inputs.items() if inputs[k] != v)})
    return f.model_copy(
        update={
            "step_text": mask(f.step_text),
            "inputs": inputs,
            "masked_inputs": hidden,
            "results": {k: r.model_copy(update={"value": masked(r.value)}) for k, r in f.results.items()},
            "program": _masked_program(f.program),
            "rules": mask(f.rules),
        }
    )


def remarked(run: SkillRunState) -> SkillRunState:
    """A record carried from an earlier reply of an agent that masks personal data, with every input that holds a
    placeholder named as masked whatever the record says: a record stored without the names (an older one, or one
    changed on the way) would have its rules compare the placeholder."""
    running = run.running
    if running is None:
        return run
    frames = [running, *([running.sub] if running.sub is not None else [])]
    marked = [
        f.model_copy(
            update={
                "masked_inputs": sorted({*f.masked_inputs, *(k for k, v in f.inputs.items() if holds_placeholder(v))})
            }
        )
        for f in frames
    ]
    top = marked[0].model_copy(update={"sub": marked[1]}) if len(marked) == 2 else marked[0]
    return run.model_copy(update={"running": top})


def masked_run(run: SkillRunState) -> SkillRunState:
    """The running-skill record as it is shown, journalled and carried to the next reply: every text a person or a
    system wrote in it is masked (inputs, step results, the step texts and rules). Ids, names and exits are not."""
    running = run.running
    if running is not None:
        running = _masked_frame(running)
        if running.sub is not None:
            running = running.model_copy(update={"sub": _masked_frame(running.sub)})
    history = [h.model_copy(update={"returns": masked(h.returns)}) for h in run.history]
    return run.model_copy(update={"running": running, "history": history})
