"""The workspace's list of agent instruction sections: which headed sections a builder may add to a brief, under what
label, in what order the prompt writes them, and the menu group, example line and presets the editor shows for each.
No saved list means the default, which writes the prompt the brief wrote before the list existed.

Rules a saved list keeps: the brief's own fields (`fixed`) and the one `custom` entry are never removed, and a fixed
one is never hidden; `hand_off` drives the hand-off and `never` the never rules, which the prompt writes last wherever
the list puts them; a section an admin adds is a `menu` section, its id made from its label. A save is checked here,
and an agent saved later reads the list it was saved under: a change never rewrites a saved agent's prompt.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BeforeValidator, Field

from ops_agent_kernel.prompt_writer import (
    CUSTOM_LIMIT,
    CUSTOM_MAX,
    DEFAULT_HEADINGS,
    HEADINGS_MAX,
    Heading,
)
from ops_agent_kernel.types import NEVER_HEADING
from ops_service_kit.errors import Unprocessable
from ops_service_kit.http import In, Json, Out
from ops_service_kit.names import Name80, slugify, tidy

SectionKindOf = Literal["fixed", "menu", "custom"]
Drives = Literal["none", "handoff", "never-last", "eval-tag"]
# The icons a preset may carry; the console maps each name to its own icon.
PresetIcon = Literal["smile", "sun", "scale", "briefcase", "zap", "message", "heart", "shield", "star", "book"]
PRESETS_MAX = 8
LABEL_MAX = 40
ID_MAX = 40
CUSTOM_ID = "custom"
OWN_GROUP = "Your sections"
# The entries whose job the prompt writer fixes: what each must drive, so neither can be dropped or handed elsewhere.
DRIVERS: dict[str, Drives] = {"hand_off": "handoff", "never": "never-last"}
FIXED_IDS = frozenset(h.id for h in DEFAULT_HEADINGS if h.kind == "fixed")


def _tidied(value: object) -> object:
    return tidy(value) if isinstance(value, str) else value


Text = Annotated[str, BeforeValidator(_tidied)]


class PresetIn(In):
    """A sentence the editor offers as a chip above a section's text; picking it writes the text into the section."""

    id: str = Field(default="", max_length=ID_MAX)
    label: Name80
    icon: PresetIcon = "smile"
    text: str = Field(min_length=1, max_length=300)


class SectionItemIn(In):
    """One entry of the list as an admin sends it. An entry sent without `id` is new and given one from its label."""

    id: str = Field(default="", max_length=ID_MAX)
    label: Annotated[str, BeforeValidator(_tidied)] = Field(min_length=1, max_length=LABEL_MAX)
    hint: str = Field(default="", max_length=300)
    kind: SectionKindOf
    order: int = Field(default=0, ge=0, le=1000)
    required: bool = False
    hidden: bool = False
    drives: Drives = "none"
    group: Text = Field(default="", max_length=LABEL_MAX)
    example: str = Field(default="", max_length=200)
    # At most PRESETS_MAX; counted by `checked`, so a longer list answers 422 with the rest of the list's rules.
    presets: list[PresetIn] = Field(default_factory=list[PresetIn], max_length=100)


class SectionListIn(In):
    """The whole list, replacing the saved one."""

    sections: list[SectionItemIn] = Field(min_length=1, max_length=HEADINGS_MAX * 2)
    custom_max: int = Field(default=CUSTOM_MAX, ge=0, le=CUSTOM_LIMIT)


class Preset(Out):
    id: str
    label: str
    icon: PresetIcon
    text: str


class SectionItem(Out):
    """One entry of the workspace's list, as stored and replied."""

    id: str
    label: str
    hint: str = ""
    kind: SectionKindOf
    order: int
    required: bool = False
    hidden: bool = False
    drives: Drives = "none"
    group: str = ""
    example: str = ""
    presets: list[Preset] = Field(default_factory=list[Preset])


class SectionList(Out):
    """The workspace's list in order, and how many sections of their own a builder may add to one agent."""

    sections: list[SectionItem]
    custom_max: int = CUSTOM_MAX


class SectionStore(Protocol):
    """Where the list is kept (`ops_agents.store.instruction_sections.InstructionSections`)."""

    async def get(self) -> _Saved | None: ...
    async def put(self, document: Json, *, by: str) -> None: ...
    async def delete(self) -> bool: ...


class _Saved(Protocol):
    @property
    def document(self) -> Json: ...


def _presets(*named: tuple[str, PresetIcon, str]) -> list[Preset]:
    return [Preset(id=slugify(label, sep="_"), label=label, icon=icon, text=text) for label, icon, text in named]


_DETAILS: dict[str, tuple[str, str, str]] = {
    # id: (hint, group, example)
    "purpose": ("What the agent is for, in one sentence.", "", "Help customers dispute a card charge."),
    "goal": ("What a finished conversation achieves.", "", "Every dispute is opened with the right charge."),
    "personality": ("Who the agent is to the person it talks to.", "Voice and style", "Patient and steady."),
    "tone": ("How the agent's words sound, in one place.", "Voice and style", "Warm, plain words, no jargon."),
    "environment": ("Where the agent works and who it talks to.", "Context", "You answer in the bank's chat."),
    "context": ("Facts the agent needs that are not in its knowledge.", "Context", "Disputes close after 120 days."),
    "how_to_answer": (
        "What an answer holds and its format: length, structure, what to include.",
        "",
        "Two short paragraphs at most.",
    ),
    "tool_use": ("When and how the agent uses its tools.", "Behaviour", "Read the charge before you answer."),
    "error_handling": ("What the agent does when a tool fails.", "Behaviour", "Say so and try once more."),
    CUSTOM_ID: ("A section a builder names and writes; prompt text only.", "", "Refund wording"),
    "hand_off": ("When the agent passes the conversation to a person.", "", "The person asks for a human."),
    "escalation": ("What the agent says as it hands off.", "Behaviour", "Say: I am passing you to a colleague."),
    "examples": ("A question and the answer you want.", "", "Q: Is it fraud? A: Tell me the amount."),
    "never": ("What the agent must never do; the prompt ends with these.", "", "Never promise a refund date."),
}
_PRESETS: dict[str, list[Preset]] = {
    "personality": _presets(
        ("Warm", "smile", "You are warm and patient, and you treat each person as someone you want to help."),
        ("Neutral", "scale", "You are even and factual, and you keep your own views out of your answers."),
        ("Formal", "briefcase", "You are courteous and professional, as a careful bank officer would be."),
        ("Concise", "zap", "You are direct and get to the point without small talk."),
        ("Plain-spoken", "message", "You speak as a person would across a counter, in everyday words."),
    ),
    "tone": _presets(
        ("Warm", "smile", "Use a friendly, encouraging tone and thank the person when they help you."),
        ("Neutral", "scale", "Use a calm, neutral tone; state facts without emphasis."),
        ("Formal", "briefcase", "Use a formal tone: full sentences, no slang, no exclamation marks."),
        ("Concise", "zap", "Keep each reply short: one or two sentences unless the person asks for more."),
        ("Plain-spoken", "message", "Use short, everyday words and explain any term the person may not know."),
    ),
}


def default_list() -> SectionList:
    """The list a workspace starts from, in the order the prompt writes it."""
    items: list[SectionItem] = []
    for n, h in enumerate(DEFAULT_HEADINGS):
        hint, group, example = _DETAILS[h.id]
        items.append(
            SectionItem(
                id=h.id,
                label=h.label,
                hint=hint,
                kind=h.kind,
                order=n,
                # Only the purpose must be written; the other fields of the brief may stay empty.
                required=h.id == "purpose",
                drives=DRIVERS.get(h.id, "eval-tag" if h.kind == "menu" else "none"),
                group=group,
                example=example,
                presets=_PRESETS.get(h.id, []),
            )
        )
    return SectionList(sections=items, custom_max=CUSTOM_MAX)


def headings(listing: SectionList) -> tuple[Heading, ...]:
    """The list as the prompt writer reads it, in order."""
    return tuple(Heading(s.id, s.label, s.kind) for s in sorted(listing.sections, key=lambda s: s.order))


def _refused(problem: str) -> Unprocessable:
    return Unprocessable(f"sections: {problem}", code="validation_failed")


def _slug(text: str, taken: set[str]) -> str:
    base = slugify(text, sep="_", width=ID_MAX, reserve=3, fallback="section")
    if base[0].isdigit():
        base = f"s_{base}"[: ID_MAX - 3]
    found, n = base, 2
    while found in taken:
        found, n = f"{base}_{n}", n + 1
    return found


def _id_problem(section_id: str) -> bool:
    return not section_id or slugify(section_id, sep="_", width=ID_MAX) != section_id or section_id[0].isdigit()


def checked(body: SectionListIn) -> SectionList:
    """The list `body` sends, in order, with ids given to new entries and renumbered from 0.

    Raises:
        Unprocessable: `validation_failed` (422) naming `sections` when the list breaks a rule in the module doc,
            repeats an id or a label, or gives an entry more than eight presets.
    """
    sent = sorted(enumerate(body.sections), key=lambda pair: (pair[1].order, pair[0]))
    if len(sent) > HEADINGS_MAX:
        raise _refused(f"a list holds at most {HEADINGS_MAX} sections.")
    given = [s.id for _, s in sent if s.id]
    if twice := next((i for i in given if given.count(i) > 1), None):
        raise _refused(f"two sections have the id {twice}.")
    taken = set(given) | FIXED_IDS | {CUSTOM_ID}
    labels: set[str] = set()
    items: list[SectionItem] = []
    for n, (_, s) in enumerate(sent):
        if not s.id and s.kind != "menu":
            raise _refused(f"{s.label} is new, and a section added to the list is a menu section.")
        section_id = s.id or _slug(s.label, taken)
        taken.add(section_id)
        if _id_problem(section_id):
            raise _refused(f"{section_id} is not an id: use lower-case letters, digits and underscores.")
        if (section_id in FIXED_IDS) != (s.kind == "fixed") or (section_id == CUSTOM_ID) != (s.kind == "custom"):
            raise _refused(f"{s.label} cannot change what kind of section it is.")
        if s.kind == "fixed" and s.hidden:
            raise _refused(f"{s.label} is part of every brief and cannot be hidden.")
        wanted = DRIVERS.get(section_id)
        if wanted is not None and s.drives != wanted:
            raise _refused(f"{s.label} drives {wanted}, and no other section can.")
        if wanted is None and s.drives != "none" and (s.kind != "menu" or s.drives != "eval-tag"):
            raise _refused(f"{s.label} can drive eval-tag only if it is a menu section, or nothing.")
        folded = " ".join(s.label.split()).casefold()
        if folded in labels:
            raise _refused(f"two sections are labelled {s.label}. Give each its own label.")
        labels.add(folded)
        if len(s.presets) > PRESETS_MAX:
            raise _refused(f"{s.label} has {len(s.presets)} presets; a section offers at most {PRESETS_MAX}.")
        preset_ids: set[str] = set()
        presets: list[Preset] = []
        for p in s.presets:
            preset_id = p.id or _slug(p.label, preset_ids)
            if preset_id in preset_ids:
                raise _refused(f"{s.label} has two presets with the id {preset_id}.")
            preset_ids.add(preset_id)
            presets.append(Preset(id=preset_id, label=p.label, icon=p.icon, text=p.text))
        own = s.kind == "menu" and section_id not in _DETAILS
        items.append(
            SectionItem(
                id=section_id,
                label=s.label,
                hint=s.hint,
                kind=s.kind,
                order=n,
                required=s.required,
                hidden=s.hidden,
                drives=s.drives,
                group=s.group or (OWN_GROUP if own else ""),
                example=s.example,
                presets=presets,
            )
        )
    missing = (FIXED_IDS | {CUSTOM_ID}) - {s.id for s in items}
    if missing:
        named = ", ".join(h.label for h in DEFAULT_HEADINGS if h.id in missing)
        raise _refused(f"{named} {'is' if len(missing) == 1 else 'are'} part of every brief and cannot be removed.")
    return SectionList(sections=items, custom_max=body.custom_max)


async def effective(store: SectionStore) -> SectionList:
    """The workspace's saved list, or the default when it has none."""
    saved = await store.get()
    return SectionList.model_validate(saved.document) if saved is not None else default_list()


async def replace(store: SectionStore, body: SectionListIn, *, by: str) -> SectionList:
    """Checks and stores `body` as the workspace's list (422 as `checked`); returns it as stored."""
    listing = checked(body)
    await store.put(listing.model_dump(mode="json", by_alias=True), by=by)
    return listing


async def reset(store: SectionStore) -> SectionList:
    """Deletes the workspace's list; returns the default it now uses."""
    await store.delete()
    return default_list()


def never_label(listing: SectionList) -> str:
    """The heading the never rules are written under: the label of the section that drives never-last."""
    return next((s.label for s in listing.sections if s.drives == "never-last"), NEVER_HEADING)


def menu_labels(listing: SectionList) -> dict[str, str]:
    """Each menu section's label by id: the name a saved section of that kind is stored and replied with."""
    return {s.id: s.label for s in listing.sections if s.kind == "menu"}
