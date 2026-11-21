"""A skill written as plain text, read into the steps the kernel runs. The one reader of a skill's text: a save, the
editor's read-as-you-type call and the publish check all call `read`, and a skill saved as a list of steps is shown
as text by `render`, so nothing is migrated by hand.

The text is a prompt with three things the kernel also enforces:

- a line that mentions a tool, an agent, a workflow or a skill (`@tool:find_customer`) is a step that may use it;
  plain lines before it are part of that step's instruction;
- `if <condition>:` with an indented block is a path, and `else:` at the same indent is the other one;
- `stop "reason"` (or `stop <exit> "reason"`) ends the skill with that reason; a bare `stop <exit>` names an exit the
  skill declares (or `done`, `failed`), and any other bare `stop …` line is an instruction;
- under `if not <check>:`, a block of only `try again` (`try again 2 times`) or `go back to step 3` makes the check
  the step's own, retried or sent back when it fails; a step line ending in `(locked)` keeps even a read tool to it.

Nothing here refuses a text. Free text is valid and saves; what the reader cannot use becomes a hint on its line,
and so does a tool that changes something on a path the agent decides. The errors are a mention of something that no
longer exists (`missing`) and a text whose steps cannot run (`unrun`); each blocks a publish, never a save.

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
# A path is a line that starts with "if" (any case) and ends in a colon; `else:` or `otherwise:` is the other one. A
# stop line holds nothing but an exit name and a quoted reason, so prose that starts with "If", "Else" or "Stop" and
# runs on stays an instruction.
_IF = re.compile(r"^if\s+(.+?)\s*:\s*$", re.IGNORECASE)
_ELSE = re.compile(r"^(?:else|otherwise)\s*:\s*$", re.IGNORECASE)
# A pasted list item: `•`, `-`, `*`, `1.` or `1)`. Its indent opens nothing, and its marker is not read: `2. If
# found:` is a path like `If found:`.
_LIST = re.compile(r"^(?:[\u2022\u2023\u25e6\u2043\u2219*-]|\d{1,3}[.)])\s+")
# The keyword reads in any case, as `if` and `else` do; an exit name stays lower case.
_STOP = re.compile(r"^(?i:stop)(?:\s+([a-z][a-z0-9_]{0,31}))?(?:\s+([\"\u201c'].*[\"\u201d']))?\s*$")
_QUOTES = "\"'\u201c\u201d\u2018\u2019"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RETRY = re.compile(r"^try again(?:\s+(once|[1-3])(?:\s+times?)?)?\.?$")
_BACK = re.compile(r"^go back to step\s+(\d{1,2})\.?$")
_LOCKED = re.compile(r"\s*\(locked\)\s*$")
# Text that can only be an expression: it reads `result.`/`inputs.` or calls a check function.
_EXPRESSION = re.compile(r"\b(?:result|inputs)\.|\b(?:exists|len)\s*\(")
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
    # How many path levels in the line is, as the reader counts its indent.
    depth: int


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
    # Why a text that has steps runs none of them (more than the kernel takes, or not readable as steps). It blocks
    # a publish, like a missing mention: the tools it mentions still join the skill, and none would be held to a line.
    unrun: list[Note] = field(default_factory=list[Note])
    # Each line that runs a tool that changes something under a condition the agent decides, outermost condition
    # first: a hint on its line, and what a team with strict publishing refuses (`skill_content.publish_problems`).
    unguarded: list[Note] = field(default_factory=list[Note])

    def json(self) -> Json:
        return {
            "hints": list(self.hints),
            "errors": [*self.errors, *({**n, "id": "steps"} for n in self.unrun)],
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
    # Named by the author (`stop blocked "…"`), not made from the reason.
    named: bool = False


@dataclass
class _Again:
    """`try again` or `go back to step n` as the whole block of an `if not …:`: the check's own "if not"."""

    line: int
    rule: IfNot


@dataclass
class _If:
    line: int
    cond: str
    body: list[_Item]
    orelse: list[_Item]


_Item = _Text | _Stop | _If | _Again


def normalised(text: str) -> str:
    """The text as the reader and the store keep it: one kind of line ending, and every leading space a plain one,
    so a text pasted from a document (non-breaking or full-width spaces, Windows line endings) reads as it looks."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        body = raw.lstrip()
        lead = raw[: len(raw) - len(body)]
        out.append("".join(c if c == "\t" else " " for c in lead) + body)
    return "\n".join(out)


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


def _bare(txt: str) -> str:
    """The line without a pasted list marker, for reading its keyword."""
    return _LIST.sub("", txt, count=1)


def _stop_of(txt: str, declared: frozenset[str]) -> tuple[str | None, str] | None:
    """(exit name, reason) of a stop line; None for a line that reads as an instruction (`stop now`)."""
    m = _STOP.match(txt)
    if m is None:
        return None
    name, rest = m.group(1), _unquote(m.group(2) or "")
    if name and not m.group(2) and name not in declared and name not in BUILT_IN_EXITS:
        return None
    return name, rest


class _Parser:
    def __init__(self, text: str, hints: list[Note], declared: frozenset[str], marks: dict[int, Mark]) -> None:
        self.rows = [(n, _indent(raw), raw.strip()) for n, raw in enumerate(text.split("\n"), start=1) if raw.strip()]
        self.hints = hints
        self.declared = declared
        self.marks = marks
        self.i = 0

    def block(self, level: int, depth: int = 0) -> list[_Item]:
        items: list[_Item] = []
        while self.i < len(self.rows):
            line, ind, txt = self.rows[self.i]
            if ind < level:
                break
            self.marks[line]["depth"] = depth + (1 if ind > level else 0)
            if ind > level and not _LIST.match(txt):
                self.hints.append(
                    {
                        "line": line,
                        "message": (
                            "This line is indented, but no “if …:” line above it starts a path, so it is read as an "
                            "ordinary line. Take out the indent, or add an “if …:” line above it."
                        ),
                    }
                )
            self.i += 1
            word = _bare(txt)
            if m := _IF.match(word):
                body = self._inner(line, ind, depth)
                orelse: list[_Item] = []
                if self.i < len(self.rows) and self.rows[self.i][1] == ind and _ELSE.match(_bare(self.rows[self.i][2])):
                    else_line = self.rows[self.i][0]
                    self.i += 1
                    self.marks[else_line]["depth"] = depth
                    orelse = self._inner(else_line, ind, depth)
                items.append(_If(line, m.group(1).strip(), body, orelse))
            elif _ELSE.match(word):
                self.hints.append(
                    {
                        "line": line,
                        "message": (
                            "This “else:” has no “if …:” line just above it at the same indent, so it is read as an "
                            "ordinary line. Line it up under its “if”."
                        ),
                    }
                )
                items.extend(self._inner(line, ind, depth))
            elif (stop := _stop_of(word, self.declared)) is not None:
                name, rest = stop
                ruled = name in BUILT_IN_EXITS or name in self.declared
                rest = rest or (name.replace("_", " ") if name and not ruled else "")
                exit_name = name or (_slug(rest) if rest else "failed")
                items.append(_Stop(line, exit_name, rest[:300], named=name is not None))
            else:
                if _STOP.match(word):
                    self.marks[line]["kind"] = "text"
                # The step the agent reads drops a pasted list marker, as the keywords above do.
                items.append(_Text(line, word))
        return items

    def _inner(self, line: int, ind: int, depth: int) -> list[_Item]:
        if self.i < len(self.rows) and self.rows[self.i][1] > ind:
            body = self.block(self.rows[self.i][1], depth + 1)
            if len(body) == 1 and isinstance(only := body[0], _Text):
                if m := _RETRY.match(only.text.lower()):
                    n = 1 if m.group(1) in (None, "once") else int(m.group(1))
                    return [_Again(only.line, IfNot(action="retry", retries=n))]
                if (m := _BACK.match(only.text.lower())) and 1 <= int(m.group(1)) <= MAX_STEPS:
                    return [_Again(only.line, IfNot(action="goto", step=int(m.group(1))))]
            return body
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
    check: tuple[str, IfNot] | None = None
    locked: bool = False


@dataclass
class _Compiler:
    fields: Mapping[str, Fields]
    labels: Mapping[str, str]
    hints: list[Note]
    marks: dict[int, Mark]
    out: list[_Step] = field(default_factory=list[_Step])
    # The endings declared beside the text (the form's results section), then those its stop lines add.
    exits: dict[str, str] = field(default_factory=dict[str, str])

    def exit_for(self, stop: _Stop) -> str:
        if stop.name in BUILT_IN_EXITS:
            return stop.name
        name, meaning = stop.name, stop.meaning or stop.name.replace("_", " ")
        if not stop.named and name in self.exits and stop.meaning and self.exits[name] != meaning:
            # Two reasons that start alike are two endings: `stop "Card blocked by the bank"` and `stop "Card blocked
            # by the owner"` cut to one slug, so the second gets a number.
            for n in range(2, EXITS_MAX + 2):
                cut = f"{name[: 32 - len(str(n)) - 1]}_{n}"
                if cut not in self.exits or self.exits[cut] == meaning:
                    name = cut
                    break
        if name not in self.exits and len(self.exits) >= EXITS_MAX:
            self.hints.append(
                {"line": stop.line, "message": f"A skill ends {EXITS_MAX} ways at most; this stop ends it as failed."}
            )
            return "failed"
        if stop.meaning or name not in self.exits:
            self.exits[name] = meaning
        return name

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

        for entry in items:
            if isinstance(entry, _Again):
                said = "try again" if entry.rule.action == "retry" else f"go back to step {entry.rule.step}"
                item: _Text | _Stop | _If = _Text(entry.line, said)
            else:
                item = entry
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
                locked = _LOCKED.search(item.text) is not None
                lines = [*buffer, (item.line, _LOCKED.sub("", item.text))]
                idx = emit(_Step(lines[0][0], [t for _, t in lines], use=runs[0], locked=locked))
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
                # A step that runs a skill is decided by that skill's ending, so a path never hangs on it.
                runs_skill = last is not None and (u := self.out[last].use) is not None and u.kind == "skill"
                free = (
                    last is not None
                    and self.out[last].test is None
                    and self.out[last].next is None
                    and self.out[last].check is None
                )
                tool_above = last is not None and (u := self.out[last].use) is not None and u.tool_name is not None
                if buffer and free and not waiting and tool_above and not runs_skill:
                    # Sentences between a tool's line and the `if` are part of that step: the condition reads the
                    # nearest tool's result above it in its block, which only its own step has.
                    assert last is not None
                    self.out[last].do += [t for _, t in buffer]
                    for n, _ in buffer:
                        self.marks[n]["step"] = last + 1
                    buffer = []
                if (idx := flush()) is not None:
                    last = idx
                free = last is not None and self.out[last].test is None and self.out[last].next is None
                free = free and last is not None and self.out[last].check is None
                runs_skill = last is not None and (u := self.out[last].use) is not None and u.kind == "skill"
                if last is not None and not waiting and free and not runs_skill:
                    host = last
                else:
                    host = emit(_Step(item.line, [f"Decide whether {item.cond}."]))
                self.marks[item.line]["step"] = host + 1
                test, how, swap = self.condition(item, self.out[host])
                self.marks[item.line]["how"] = how
                if len(item.body) == 1 and isinstance(again := item.body[0], _Again) and not item.orelse:
                    if swap or (how == "agent" and re.match(r"^\s*not\s+", item.cond, re.IGNORECASE)):
                        # `if not <check>:` with only `try again` or `go back to step n`: the check is the step's own.
                        own = test if swap else re.sub(r"^\s*not\s+", "", test, flags=re.IGNORECASE)
                        self.out[host].check = (own, again.rule)
                        self.marks[again.line]["step"] = host + 1
                        last = host
                        continue
                    said = "try again" if again.rule.action == "retry" else f"go back to step {again.rule.step}"
                    item = _If(item.line, item.cond, [_Text(again.line, said)], [])
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
        # Words the tool returns come first: `status is shipped` is a rule on the result even though it does not
        # parse as one. The expression parser reads only text that names `result.` or `inputs.` or calls a check.
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
        if _EXPRESSION.search(cond):
            try:
                # `if not <rule>:` is the other path of the rule, never `not (rule)`: a rule with no answer (a value
                # that is not there) holds neither way, so it must take the path the author guards with.
                inner = re.sub(r"^\s*not\s+", "", cond, flags=re.IGNORECASE)
                if (
                    inner != cond
                    and expr.kind_of(inner) == "rule"
                    and (tool is not None or not expr.reads_result(inner))
                ):
                    return inner, "checked", True
                if expr.kind_of(cond) == "rule":
                    if expr.reads_result(cond) and tool is None:
                        self.hints.append(
                            {
                                "line": item.line,
                                "message": (
                                    "This rule reads a result, and no tool runs on the line above it; the agent "
                                    "decides it instead."
                                ),
                            }
                        )
                        return f"this holds: {cond.replace('result.', 'the result ')}", "agent", False
                    return cond, "checked", False
            except expr.CheckError as e:
                self.hints.append(
                    {
                        "line": item.line,
                        "message": (
                            f"This reads like a rule but is not a valid one ({e}); the agent decides it instead."
                        ),
                    }
                )
                return f"this holds: {cond.replace('result.', 'the result ')}", "agent", False
        words = set(re.findall(r"[\w=<>]+", cond.lower()))
        if tool is None and words & _COMPARING:
            self.hints.append(
                {
                    "line": item.line,
                    "message": (
                        "No tool runs above this line in its block, so nothing here can be checked and the agent "
                        "decides it from the conversation. Put the line with the tool just above it to check it."
                    ),
                }
            )
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
    exits: Mapping[str, str] | None = None,
    access: Mapping[str, str] | None = None,
) -> Reading:
    """The text as the kernel will run it. `fields` is what each mentioned tool returns (by its `@kind:id` token),
    from its output schema; `labels` the names of what the text mentions; `missing` the mentions (token to label)
    that no longer exist. With `plain` (a reason), the text is read as plain instructions whatever it holds: a skill
    that is always on, or written in parts, cannot run step by step. `exits` are the endings declared beside the text
    (name to meaning): the program keeps them, and a bare `stop <name>` ends the skill only with one of them.
    `access` is each offered tool's access by grant id, None when the directory could not answer: with it, a line
    whose tool changes something behind a condition the agent decides is a hint (`Reading.unguarded`)."""
    fields, labels, missing, declared = fields or {}, labels or {}, missing or {}, dict(exits or {})
    text = normalised(text)
    hints: list[Note] = []
    marks: dict[int, Mark] = {}
    for n, raw in enumerate(text.split("\n"), start=1):
        t = _bare(raw.strip())
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
        marks[n] = {"line": n, "kind": kind, "step": None, "how": None, "tool": None, "depth": _indent(raw) // 4}
    tree = _Parser(text, hints, frozenset(declared), marks).block(0) if text.strip() else []
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
    c = _Compiler(fields, labels, hints, marks, exits=declared)
    c.block(tree, _Label("done"))
    if len(c.out) > MAX_STEPS:
        unrun: Note = {
            "line": c.out[MAX_STEPS].line,
            "message": (
                f"The text makes {len(c.out)} steps and a skill runs {MAX_STEPS} at most, so none of its tools or "
                "paths would be enforced. Your draft is saved; split it into two skills to publish."
            ),
        }
        return Reading(None, hints, errors, uses, list(marks.values()), phrases, [], refs, [unrun])
    total = len(c.out)
    built: list[SkillStep] = []
    for i, s in enumerate(c.out):
        do = "\n".join(s.do)
        if len(do) > DO_MAX:
            hints.append(
                {
                    "line": s.line,
                    "message": (
                        f"A step's instruction is read up to {DO_MAX} characters; the agent does not see the rest. "
                        "Split the line into two."
                    ),
                }
            )
            do = do[: DO_MAX - 1] + "…"
        branch = None
        if s.test is not None and s.otherwise is not None:
            otherwise = _jump(s.otherwise, i, total, default_next=False)
            assert otherwise is not None
            branch = Branch(test=StepCheck(text=s.test), otherwise=otherwise)
        check, if_not = (StepCheck(text=s.check[0]), s.check[1]) if s.check is not None else (None, None)
        built.append(
            SkillStep(
                do=do,
                use=s.use,
                check=check,
                if_not=if_not,
                branch=branch,
                next=_jump(s.next, i, total, default_next=True),
                locked=s.locked or None,
            )
        )
    try:
        program = steps.judged(SkillProgram(steps=built, exit=c.exits))
    except (ValidationError, expr.CheckError) as e:
        why: Note = {
            "line": 1,
            "message": f"The text could not be read into steps ({e}). Your draft is saved; fix it to publish.",
        }
        return Reading(None, hints, errors, uses, list(marks.values()), phrases, [], refs, [why])
    for p in steps.problems(program):
        if p.kind != "bad_use":
            line = c.out[p.step - 1].line if p.step else 1
            hints.append({"line": line, "message": p.message})
    unguarded = _unguarded(tree, marks, labels, access) if access is not None else []
    hints += unguarded
    return Reading(
        program, hints, errors, uses, list(marks.values()), phrases, [s.line for s in c.out], refs, [], unguarded
    )


def _unguarded(
    items: Sequence[_Item], marks: Mapping[int, Mark], labels: Mapping[str, str], access: Mapping[str, str]
) -> list[Note]:
    """The lines whose tool changes something (`steps.changes`, by the directory's `access` for each grant id) and
    that run only on a path the agent decides, on either side of it and at any depth below it."""
    out: list[Note] = []

    def walk(block: Sequence[_Item], cond: str | None) -> None:
        for item in block:
            if isinstance(item, _If):
                decided = cond if cond is not None else item.cond if marks[item.line]["how"] == "agent" else None
                walk(item.body, decided)
                walk(item.orelse, decided)
            elif isinstance(item, _Text) and cond is not None:
                runs = [r for r in Ref.found_in(item.text) if r.kind in _STEP_KINDS]
                name = runs[0].tool_name if runs else None
                if name is None or not steps.changes(name, access.get(runs[0].grant or "")):
                    continue
                label = labels.get(runs[0].token, runs[0].id)
                out.append(
                    {
                        "line": item.line,
                        "message": (
                            f"{label} changes something, and it runs only when the agent decides “{cond}” from the "
                            "conversation. To check it on a tool's result instead, put the line with the tool that "
                            "returns the answer just above the “if”."
                        ),
                    }
                )

    walk(items, None)
    return out


def stop_exits(text: str) -> dict[str, str]:
    """The endings a text's own `stop "…"` lines make (name to reason). A save drops them from the endings it was
    sent before it reads the new text, so an ending the text no longer says goes with it, and only the endings the
    form declares itself are kept."""
    out: dict[str, str] = {}
    marks: dict[int, Mark] = {
        n: {"line": n, "kind": "text", "step": None, "how": None, "tool": None, "depth": 0}
        for n in range(1, text.count("\n") + 2)
    }
    stack: list[_Item] = list(_Parser(normalised(text), [], frozenset(), marks).block(0))
    while stack:
        item = stack.pop()
        if isinstance(item, _If):
            stack += [*item.body, *item.orelse]
        elif isinstance(item, _Stop) and item.name not in BUILT_IN_EXITS and item.meaning:
            out.setdefault(item.name, item.meaning)
    return out


def render(instructions: str, program: SkillProgram | None) -> str:
    """A skill saved as a list of steps, written as text that `read` reads back to the same steps: each step's
    instruction with the line naming its tool last (so its check reads that tool's result), `(locked)` on a step a
    builder locked, then its check as `if not <check>:` with what a failure does: `try again`, `go back to step n`
    or the ending it takes. Notes shared by every step come first. A step with no tool and no check joins the step
    after it, and a jump back counts the steps as the text reads them."""
    lines = list(instructions.strip().split("\n")) if instructions.strip() else []
    if program is None:
        return "\n".join(lines)
    # Where each stored step lands once read back: a step ends at a tool or a check.
    read_as: dict[int, int] = {}
    n = 1
    for k, step in enumerate(program.steps, start=1):
        read_as[k] = n
        if step.use is not None or step.check is not None:
            n += 1
    for step in program.steps:
        do = [ln for ln in step.do.strip().split("\n") if ln.strip()]
        if step.use is not None:
            named = [ln for ln in do if step.use.token in ln]
            do = [ln for ln in do if step.use.token not in ln] + named
            if not named:
                do = [*do[:-1], f"{do[-1]} with {step.use.token}"] if do else [f"Use {step.use.token}"]
            if step.locked:
                do[-1] = f"{do[-1]} (locked)"
        lines += do
        check = step.check
        if check is None:
            continue
        rule = step.if_not or IfNot()
        lines.append(f"if not {check.text}:")
        if rule.action == "exit" and rule.exit and rule.exit not in BUILT_IN_EXITS:
            lines.append(f'    stop {rule.exit} "{program.exit.get(rule.exit, rule.exit)}"')
        elif rule.action == "goto" and rule.step is not None:
            lines.append(f"    go back to step {read_as.get(rule.step, rule.step)}")
        elif rule.action == "retry" and rule.retries > 0:
            lines.append("    try again" if rule.retries == 1 else f"    try again {rule.retries} times")
        else:
            lines.append("    stop failed")
    return "\n".join(lines)
