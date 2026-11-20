"""A skill written as plain text, read into the steps the kernel runs. The one reader of a skill's text: a save, the
editor's read-as-you-type call and the publish check all call `read`, and a skill saved as a list of steps is shown
as text by `render`, so nothing is migrated by hand.

The text is a prompt with three things the kernel also enforces:

- a line that mentions a tool, an agent, a workflow or a skill (`@tool:find_customer`) is a step that may use it;
  plain lines before it are part of that step's instruction;
- `if <condition>:` with an indented block is a path, and `else:` at the same indent is the other one;
- `stop "reason"` (or `stop <exit> "reason"`) ends the skill with that reason.

Nothing here refuses a text. Free text is valid and saves; what the reader cannot use becomes a hint on its line.
The only error is a mention of something that no longer exists (`missing`), which blocks a publish, never a save.

A condition made of words the step's tool returns is turned into a rule the kernel checks on the result
("checked"); any other condition is a sentence the model decides from the conversation ("agent decides"), and it
reports which way it went to the kernel (`step_done` with `holds`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from pydantic import ValidationError

from ops_agent_kernel import expr, steps
from ops_contracts.skill_run import (
    BUILT_IN_EXITS,
    EXIT_NAME,
    MAX_STEPS,
    Branch,
    IfNot,
    Jump,
    Ref,
    RefKind,
    SkillProgram,
    SkillStep,
    StepCheck,
)
from ops_service_kit.http import Json

How = Literal["checked", "agent"]
LineKind = Literal["text", "step", "if", "else", "stop", "blank"]

DO_MAX = 600
TEST_MAX = 300
EXITS_MAX = 8
# Words that make a condition read as a comparison: one of them with no field the tool returns earns a hint.
_COMPARING = {"is", "are", "was", "equals", "more", "less", "over", "under", "above", "below", "=", ">", "<"}
_LEAD = {"the", "it", "they", "still", "its", "their"}
_ORDER: list[tuple[tuple[str, ...], str]] = [
    (("more", "than"), ">"),
    (("greater", "than"), ">"),
    (("over",), ">"),
    (("above",), ">"),
    (("less", "than"), "<"),
    (("fewer", "than"), "<"),
    (("under",), "<"),
    (("below",), "<"),
    (("at", "least"), ">="),
    (("at", "most"), "<="),
]
_FLIP = {">": "<=", "<": ">=", ">=": "<", "<=": ">"}
_IF = re.compile(r"^if\s+(.+?)\s*:\s*$", re.IGNORECASE)
_ELSE = re.compile(r"^else\s*:\s*$", re.IGNORECASE)
_STOP = re.compile(r"^stop\b\s*(?:([a-z][a-z0-9_]{0,31})\s*)?(.*)$", re.IGNORECASE)
_QUOTES = "\"'\u201c\u201d\u2018\u2019"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STEP_KINDS: frozenset[RefKind] = frozenset({"tool", "agent", "workflow", "skill"})


class Field(TypedDict, total=False):
    """One top-level field of what a tool returns, from its output schema."""

    type: str
    enum: list[str]


Fields = Mapping[str, Field]


class Note(TypedDict):
    """A hint or an error, on a line of the text (from 1)."""

    line: int
    message: str


class Missing(Note):
    id: str


class Mark(TypedDict):
    """What one line of the text is, for the editor: its kind, the step it belongs to, how its condition is decided
    and the tool of its step."""

    line: int
    kind: LineKind
    step: int | None
    how: How | None
    tool: str | None


class Uses(TypedDict):
    tools: int
    knowledge: int
    skills: int
    agents: int
    workflows: int


@dataclass(frozen=True)
class Reading:
    """What a text reads as: the program the kernel runs (None for a text with no steps), the hints and errors on
    its lines, what it uses, a mark for each line, the condition phrases each mentioned tool offers (for the
    editor's `if ` suggestions) and the line each step starts on."""

    program: SkillProgram | None
    hints: list[Note]
    errors: list[Missing]
    uses: Uses
    marks: list[Mark]
    phrases: dict[str, list[str]]
    step_lines: list[int]
    refs: list[Ref]

    def json(self) -> Json:
        return {
            "hints": list(self.hints),
            "errors": list(self.errors),
            "uses": dict(self.uses),
            "lines": list(self.marks),
            "phrases": {k: list(v) for k, v in self.phrases.items()},
            "steps": len(self.program.steps) if self.program is not None else 0,
            "stepLines": list(self.step_lines),
        }  # type: ignore[return-value]


# --- the text as a tree ---


@dataclass
class _Text:
    line: int
    text: str


@dataclass
class _Stop:
    line: int
    name: str
    meaning: str


@dataclass
class _If:
    line: int
    cond: str
    body: list[_Item]
    orelse: list[_Item]


_Item = _Text | _Stop | _If


def _indent(raw: str) -> int:
    lead = raw[: len(raw) - len(raw.lstrip(" \t"))]
    return len(lead.expandtabs(4))


def _unquote(text: str) -> str:
    t = text.strip()
    while t and t[0] in _QUOTES:
        t = t[1:]
    while t and t[-1] in _QUOTES:
        t = t[:-1]
    return t.strip()


def _slug(reason: str) -> str:
    words = re.findall(r"[a-z0-9]+", reason.lower())
    name = "_".join(words)
    if len(name) > 32:
        # Cut at a word, so an exit reads as words: `hand_over_to_the_customer_care` rather than `..._care_t`.
        name = name[:33].rsplit("_", 1)[0]
    name = name.strip("_")
    if not name or not name[0].isalpha():
        name = f"stop_{name}"[:32].strip("_")
    return name if re.fullmatch(EXIT_NAME, name) else "stopped"


class _Parser:
    def __init__(self, text: str, hints: list[Note]) -> None:
        self.rows = [(n, _indent(raw), raw.strip()) for n, raw in enumerate(text.split("\n"), start=1) if raw.strip()]
        self.hints = hints
        self.i = 0

    def block(self, level: int) -> list[_Item]:
        items: list[_Item] = []
        while self.i < len(self.rows):
            line, ind, txt = self.rows[self.i]
            if ind < level:
                break
            if ind > level:
                self.hints.append(
                    {
                        "line": line,
                        "message": (
                            "This line is indented, and no “if …:” above it opens a path; it is read as part of "
                            "the lines around it."
                        ),
                    }
                )
            self.i += 1
            if m := _IF.match(txt):
                body = self._inner(line, ind)
                orelse: list[_Item] = []
                if self.i < len(self.rows) and self.rows[self.i][1] == ind and _ELSE.match(self.rows[self.i][2]):
                    else_line = self.rows[self.i][0]
                    self.i += 1
                    orelse = self._inner(else_line, ind)
                items.append(_If(line, m.group(1).strip(), body, orelse))
            elif _ELSE.match(txt):
                self.hints.append(
                    {
                        "line": line,
                        "message": "This else: has no “if …:” above it at the same indent; it is read as text.",
                    }
                )
                items.extend(self._inner(line, ind))
            elif m := _STOP.match(txt):
                name, rest = m.group(1), _unquote(m.group(2))
                if name and not rest and name.lower() not in BUILT_IN_EXITS:
                    rest, name = name, None
                exit_name = name.lower() if name else _slug(rest) if rest else "failed"
                items.append(_Stop(line, exit_name, rest[:300]))
            else:
                items.append(_Text(line, txt))
        return items

    def _inner(self, line: int, ind: int) -> list[_Item]:
        if self.i < len(self.rows) and self.rows[self.i][1] > ind:
            return self.block(self.rows[self.i][1])
        self.hints.append({"line": line, "message": "Nothing is indented under this line, so this path does nothing."})
        return []


# --- conditions ---


def _words_of(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").replace("-", " ")
    return spaced.lower().split()


def _number(word: str) -> str | None:
    w = word.replace(",", "")
    return w if re.fullmatch(r"-?\d+(\.\d+)?", w) else None


def _rule_for(cond: str, fields: Fields) -> str | None:
    """The rule a condition is, when it is made of words the tool returns; None when the agent decides it."""
    original = cond.split()
    words = [re.sub(r"[^\w.<>=-]", "", w).lower() for w in original]
    i = 0
    while i < len(words) and words[i] in _LEAD:
        i += 1
    neg = False
    if i < len(words) and words[i] in ("not", "no"):
        neg, i = True, i + 1
    best: tuple[str, int] | None = None
    for name in fields:
        fw = _words_of(name)
        at = all(i + k < len(words) and words[i + k] == w for k, w in enumerate(fw))
        if fw and at and _IDENT.match(name) and (best is None or len(fw) > best[1]):
            best = (name, len(fw))
    if best is None:
        return None
    name, size = best
    spec = fields[name]
    kind = spec.get("type", "")
    rest, kept = words[i + size :], original[i + size :]
    path = f"result.{name}"
    if not rest:
        if kind in ("boolean", ""):
            return f"{path} == {'false' if neg else 'true'}"
        return f"{path} is null" if neg else f"exists({path})"
    if rest[0] in ("is", "are", "was", "equals", "=", "=="):
        rest, kept = rest[1:], kept[1:]
    if rest and rest[0] == "not":
        neg, rest, kept = not neg, rest[1:], kept[1:]
    for phrase, op in _ORDER:
        if tuple(rest[: len(phrase)]) == phrase and len(rest) == len(phrase) + 1:
            num = _number(rest[-1])
            if num is None or kind not in ("number", "integer", ""):
                return None
            return f"{path} {_FLIP[op] if neg else op} {num}"
    if not rest:
        return None
    if rest in (["true"], ["yes"], ["false"], ["no"]):
        value = rest in (["true"], ["yes"])
        return f"{path} == {'false' if value == neg else 'true'}"
    if rest == ["empty"]:
        return f"len({path}) {'>' if neg else '=='} 0"
    eq = "!=" if neg else "=="
    if kind in ("number", "integer") and len(rest) == 1 and (num := _number(rest[0])) is not None:
        return f"{path} {eq} {num}"
    if kind not in ("string", ""):
        return None
    value = " ".join(_unquote(w) for w in kept)
    if enum := spec.get("enum"):
        match = next((e for e in enum if e.lower() == value.lower()), None)
        if match is None:
            return None
        value = match
    if not value or '"' in value or "\\" in value:
        return None
    return f'{path} {eq} "{value}"'


def phrases_of(fields: Fields) -> list[str]:
    """What the editor offers after `if ` for a tool, from the fields it returns."""
    out: list[str] = []
    for name, spec in fields.items():
        if not _IDENT.match(name):
            continue
        w = " ".join(_words_of(name))
        kind = spec.get("type", "")
        if kind == "boolean":
            out += [w, f"not {w}"]
        elif enum := spec.get("enum"):
            out += [f"{w} is {e}" for e in enum[:3]]
        elif kind in ("number", "integer"):
            out.append(f"{w} is more than …")
        elif kind == "string":
            out.append(f"{w} is …")
    return out[:8]


# --- compiling the tree into the kernel's steps ---


@dataclass
class _Label:
    """A place in the program, known once the step it names is written: a step (its index), an exit, or another
    label that resolves later."""

    target: int | str | _Label | None = None

    def resolve(self) -> int | str:
        t = self.target
        while isinstance(t, _Label):
            t = t.target
        return "done" if t is None else t


@dataclass
class _Step:
    line: int
    do: list[str]
    use: Ref | None = None
    test: str | None = None
    otherwise: _Label | None = None
    next: _Label | None = None


@dataclass
class _Compiler:
    fields: Mapping[str, Fields]
    labels: Mapping[str, str]
    hints: list[Note]
    marks: dict[int, Mark]
    out: list[_Step] = field(default_factory=list[_Step])
    exits: dict[str, str] = field(default_factory=dict[str, str])

    def exit_for(self, stop: _Stop) -> str:
        if stop.name in BUILT_IN_EXITS:
            return stop.name
        if stop.name not in self.exits and len(self.exits) >= EXITS_MAX:
            self.hints.append(
                {"line": stop.line, "message": f"A skill ends {EXITS_MAX} ways at most; this stop ends it as failed."}
            )
            return "failed"
        self.exits.setdefault(stop.name, stop.meaning or stop.name.replace("_", " "))
        return stop.name

    def block(self, items: Sequence[_Item], follow: _Label) -> _Label:
        start = _Label()
        waiting: list[_Label] = [start]
        buffer: list[tuple[int, str]] = []
        last: int | None = None
        dead = False

        def emit(step: _Step) -> int:
            self.out.append(step)
            idx = len(self.out) - 1
            for w in waiting:
                w.target = idx
            waiting.clear()
            return idx

        def flush() -> int | None:
            nonlocal buffer
            if not buffer:
                return None
            idx = emit(_Step(buffer[0][0], [t for _, t in buffer]))
            for n, _ in buffer:
                self.marks[n]["step"] = idx + 1
            buffer = []
            return idx

        for item in items:
            if dead:
                self.hints.append(
                    {
                        "line": item.line,
                        "message": "The skill has already stopped above, so this line is never reached.",
                    }
                )
                continue
            if isinstance(item, _Text):
                runs = [r for r in Ref.found_in(item.text) if r.kind in _STEP_KINDS]
                if not runs:
                    if sum(len(t) for _, t in buffer) + len(item.text) > DO_MAX - 50 and buffer:
                        last = flush()
                    buffer.append((item.line, item.text))
                    continue
                if len(runs) > 1:
                    name = self.labels.get(runs[0].token, runs[0].id)
                    self.hints.append(
                        {
                            "line": item.line,
                            "message": (
                                f"This line names more than one tool; the step may use only {name}. Put the other on "
                                "its own line."
                            ),
                        }
                    )
                if sum(len(t) for _, t in buffer) + len(item.text) > DO_MAX:
                    last = flush()
                lines = [*buffer, (item.line, item.text)]
                idx = emit(_Step(lines[0][0], [t for _, t in lines], use=runs[0]))
                for n, _ in lines:
                    self.marks[n]["step"] = idx + 1
                self.marks[item.line]["kind"] = "step"
                self.marks[item.line]["tool"] = runs[0].token
                buffer, last = [], idx
            elif isinstance(item, _Stop):
                to = self.exit_for(item)
                if (idx := flush()) is not None:
                    self.out[idx].next = _Label(to)
                elif waiting:
                    for w in waiting:
                        w.target = to
                    waiting.clear()
                elif last is not None:
                    self.out[last].next = _Label(to)
                dead = True
            else:
                if (idx := flush()) is not None:
                    last = idx
                if last is not None and not waiting and self.out[last].test is None and self.out[last].next is None:
                    host = last
                else:
                    host = emit(_Step(item.line, [f"Decide whether {item.cond}."]))
                self.marks[item.line]["step"] = host + 1
                test, how, swap = self.condition(item, self.out[host])
                self.marks[item.line]["how"] = how
                self.out[host].test = test
                after = _Label()
                body = self.block(item.body, after)
                orelse = self.block(item.orelse, after) if item.orelse else after
                yes, no = (orelse, body) if swap else (body, orelse)
                self.out[host].next, self.out[host].otherwise = yes, no
                waiting, last = [after], None
        if not dead:
            if (idx := flush()) is not None:
                last = idx
            if waiting:
                for w in waiting:
                    w.target = follow
            elif last is not None and self.out[last].next is None:
                self.out[last].next = follow
        return start

    def condition(self, item: _If, host: _Step) -> tuple[str, How, bool]:
        """The test the condition is, how it is decided, and whether it was written as `not` and its paths swap."""
        cond = item.cond[:TEST_MAX]
        if len(item.cond) > TEST_MAX:
            self.hints.append(
                {
                    "line": item.line,
                    "message": f"A condition is read up to {TEST_MAX} characters; the rest is left out.",
                }
            )
        tool = host.use.token if host.use is not None and host.use.tool_name is not None else None
        none: Fields = {}
        fields: Fields = self.fields.get(tool, none) if tool else none
        name = self.labels.get(tool, host.use.id) if tool and host.use is not None else ""
        if Ref.found_in(cond):
            self.hints.append(
                {
                    "line": item.line,
                    "message": (
                        "A mention in a condition is read as words, so the agent decides it from the conversation."
                    ),
                }
            )
            return cond, "agent", False
        try:
            # `if not <rule>:` is the other path of the rule, never `not (rule)`: a rule with no answer (a value
            # that is not there) holds neither way, so it must take the path the author guards with.
            inner = re.sub(r"^\s*not\s+", "", cond, flags=re.IGNORECASE)
            if inner != cond and expr.kind_of(inner) == "rule" and (tool is not None or not expr.reads_result(inner)):
                return inner, "checked", True
            if expr.kind_of(cond) == "rule":
                if expr.reads_result(cond) and tool is None:
                    self.hints.append(
                        {
                            "line": item.line,
                            "message": (
                                "This rule reads a result, and the line above runs no tool; the agent decides it "
                                "instead."
                            ),
                        }
                    )
                    return f"this holds: {cond.replace('result.', 'the result ')}", "agent", False
                return cond, "checked", False
        except expr.CheckError as e:
            self.hints.append(
                {
                    "line": item.line,
                    "message": f"This reads like a rule but is not a valid one ({e}); the agent decides it instead.",
                }
            )
            return f"this holds: {cond.replace('result.', 'the result ')}", "agent", False
        rule = _rule_for(cond, fields) if fields else None
        if rule is not None:
            try:
                if expr.kind_of(rule) == "rule":
                    # A `not` written as a rule is the other path of the plain rule: when the value is not there,
                    # neither the rule nor its `not` holds, and the `not` path is the one an author guards with.
                    plain = _rule_for(re.sub(r"^\s*(not|no)\s+", "", cond, flags=re.IGNORECASE), fields)
                    negated = re.match(r"^\s*(not|no)\s+", cond, re.IGNORECASE) is not None
                    if negated and plain is not None:
                        return plain, "checked", True
                    return rule, "checked", False
            except expr.CheckError:
                pass
        words = set(re.findall(r"[\w=<>]+", cond.lower()))
        if tool is not None and words & _COMPARING:
            offer = phrases_of(fields)
            if offer:
                example = offer[0].replace(" …", "")
                self.hints.append(
                    {
                        "line": item.line,
                        "message": (
                            f"{name} does not return anything that matches “{cond}”, so the agent decides from the "
                            f"conversation. To check it exactly, use a word {name} returns, such as “{example}”."
                        ),
                    }
                )
            else:
                self.hints.append(
                    {
                        "line": item.line,
                        "message": (
                            f"What {name} returns is not known, so the agent decides this from the conversation."
                        ),
                    }
                )
        return cond, "agent", False


def _jump(label: _Label | None, at: int, total: int, *, default_next: bool) -> Jump | None:
    if label is None:
        return None
    to = label.resolve()
    if isinstance(to, int):
        return None if default_next and to == at + 1 else Jump(step=to + 1)
    if default_next and to == "done" and at == total - 1:
        return None
    return Jump(exit=to)


def read(
    text: str,
    *,
    fields: Mapping[str, Fields] | None = None,
    labels: Mapping[str, str] | None = None,
    missing: Mapping[str, str] | None = None,
    plain: str | None = None,
) -> Reading:
    """The text as the kernel will run it. `fields` is what each mentioned tool returns (by its `@kind:id` token),
    from its output schema; `labels` the names of what the text mentions; `missing` the mentions (token to label)
    that no longer exist. With `plain` (a reason), the text is read as plain instructions whatever it holds: a skill
    that is always on, or written in parts, cannot run step by step."""
    fields, labels, missing = fields or {}, labels or {}, missing or {}
    hints: list[Note] = []
    marks: dict[int, Mark] = {}
    for n, raw in enumerate(text.split("\n"), start=1):
        t = raw.strip()
        kind: LineKind = (
            "blank"
            if not t
            else "if"
            if _IF.match(t)
            else "else"
            if _ELSE.match(t)
            else "stop"
            if _STOP.match(t)
            else "text"
        )
        marks[n] = {"line": n, "kind": kind, "step": None, "how": None, "tool": None}
    tree = _Parser(text, hints).block(0) if text.strip() else []
    refs = Ref.found_in(text)
    errors: list[Missing] = []
    for n, raw in enumerate(text.split("\n"), start=1):
        for ref in Ref.found_in(raw):
            if ref.token in missing:
                name = missing[ref.token] or ref.id
                errors.append(
                    {
                        "line": n,
                        "id": f"{ref.kind}:{ref.id}",
                        "message": (
                            f"Line {n} mentions {name}, which no longer exists. Your draft is saved; pick another "
                            "or delete the mention to publish."
                        ),
                    }
                )
    counts = {k: len({r.id for r in refs if r.kind == k}) for k in ("tool", "knowledge", "skill", "agent", "workflow")}
    uses: Uses = {
        "tools": counts["tool"],
        "knowledge": counts["knowledge"],
        "skills": counts["skill"],
        "agents": counts["agent"],
        "workflows": counts["workflow"],
    }
    phrases = {tok: p for tok, f in fields.items() if (p := phrases_of(f))}
    structured = any(not isinstance(i, _Text) for i in tree) or any(r.kind in _STEP_KINDS for r in refs)
    if not structured:
        return Reading(None, hints, errors, uses, list(marks.values()), phrases, [], refs)
    if plain is not None:
        hints.insert(0, {"line": 1, "message": plain})
        return Reading(None, hints, errors, uses, list(marks.values()), phrases, [], refs)
    c = _Compiler(fields, labels, hints, marks)
    c.block(tree, _Label("done"))
    if len(c.out) > MAX_STEPS:
        hints.insert(
            0,
            {
                "line": 1,
                "message": (
                    f"The text makes more than {MAX_STEPS} steps, so it is read as plain instructions and "
                    "nothing in it is enforced."
                ),
            },
        )
        return Reading(None, hints, errors, uses, list(marks.values()), phrases, [], refs)
    total = len(c.out)
    built: list[SkillStep] = []
    for i, s in enumerate(c.out):
        do = "\n".join(s.do)
        if len(do) > DO_MAX:
            hints.append(
                {
                    "line": s.line,
                    "message": (
                        f"A step's instruction is read up to {DO_MAX} characters; the rest is in the skill's text only."
                    ),
                }
            )
            do = do[: DO_MAX - 1] + "…"
        branch = None
        if s.test is not None and s.otherwise is not None:
            otherwise = _jump(s.otherwise, i, total, default_next=False)
            assert otherwise is not None
            branch = Branch(test=StepCheck(text=s.test), otherwise=otherwise)
        built.append(SkillStep(do=do, use=s.use, branch=branch, next=_jump(s.next, i, total, default_next=True)))
    try:
        program = steps.judged(SkillProgram(steps=built, exit=c.exits))
    except (ValidationError, expr.CheckError) as e:
        hints.insert(
            0, {"line": 1, "message": f"The text could not be read into steps ({e}); it is read as plain instructions."}
        )
        return Reading(None, hints, errors, uses, list(marks.values()), phrases, [], refs)
    for p in steps.problems(program):
        if p.kind != "bad_use":
            line = c.out[p.step - 1].line if p.step else 1
            hints.append({"line": line, "message": p.message})
    return Reading(program, hints, errors, uses, list(marks.values()), phrases, [s.line for s in c.out], refs)


def render(instructions: str, program: SkillProgram | None) -> str:
    """A skill saved as a list of steps, written as text that `read` reads back to the same steps: each step's
    instruction with the tool it runs, then its check as `if not <check>:` with the ending it takes. Notes shared by
    every step come first. A retry, a jump back and a builder's lock have no words in the text, so a check that
    retried reads as `stop failed`; the stored steps are kept as they are until the text is saved."""
    lines = list(instructions.strip().split("\n")) if instructions.strip() else []
    if program is None:
        return "\n".join(lines)
    for step in program.steps:
        do = step.do.strip()
        if step.use is not None and step.use.token not in do:
            do = f"{do} with {step.use.token}"
        lines += [ln for ln in do.split("\n") if ln.strip()]
        check = step.check
        if check is None:
            continue
        rule = step.if_not or IfNot()
        lines.append(f"if not {check.text}:")
        if rule.action == "exit" and rule.exit and rule.exit not in BUILT_IN_EXITS:
            lines.append(f'    stop {rule.exit} "{program.exit.get(rule.exit, rule.exit)}"')
        elif rule.action == "goto" and rule.step is not None:
            lines.append(f"    Go back to step {rule.step}.")
        else:
            lines.append("    stop failed")
    return "\n".join(lines)
