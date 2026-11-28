"""What a model call's budget and replay headers ask for, and the replay record's contents: the request hash, the
estimate a reservation holds, and the provider's final answer as a stream or a reply delivered it
(docs/design/agents-v2/model-gateway.md, "Gateway rules")."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ops_service_kit.http import Json
from ops_service_kit.narrow import json_object

from .providers import Completion

PURPOSES = frozenset({"turn", "closing", "check", "judge", "summary"})
# Four covers the deepest chain: a step in a group in a run started by a team test's eval budget.
MAX_BUDGETS = 4
MAX_BUDGET_ID = 200
# Fields a client sets per attempt, never part of what the request asks; left out of the hash so a re-run matches.
UNHASHED = ("stream", "user", "metadata", "stream_options")


@dataclass(frozen=True)
class CallHeaders:
    """`X-Budget-Id`, `X-Replay-Key` and `X-Call-Purpose` as one call sent them."""

    budget_ids: list[str]
    replay_key: str | None
    purpose: str

    @property
    def bounded(self) -> bool:
        """Whether the call names a budget, and so reserves before the provider is called."""
        return bool(self.budget_ids)


def call_headers(
    budget_header: str | None, replay_key: str | None, purpose: str | None, *, replayable: bool = True
) -> CallHeaders | tuple[int, str, str]:
    """The headers read, or the refusal (status, code, message) for ones the gateway cannot act on. A call that is
    not `replayable` (an embedding) names a budget without a replay key."""
    ids = [part.strip() for part in budget_header.split(",")] if budget_header is not None else []
    if budget_header is not None and (not ids or any(not i for i in ids)):
        return 422, "budget_header_invalid", "X-Budget-Id lists one to four budget ids, comma separated, none empty."
    if len(ids) > MAX_BUDGETS:
        return 422, "budget_header_invalid", f"X-Budget-Id lists {len(ids)} budgets; at most {MAX_BUDGETS}."
    if any(len(i) > MAX_BUDGET_ID for i in ids):
        return 422, "budget_header_invalid", f"A budget id in X-Budget-Id is over {MAX_BUDGET_ID} characters."
    chosen = (purpose or "turn").strip()
    if chosen not in PURPOSES:
        return 422, "budget_header_invalid", f"X-Call-Purpose is one of {', '.join(sorted(PURPOSES))}, not {chosen}."
    key = replay_key.strip() if replay_key else None
    if ids and not key and replayable:
        # The closing and check caps are counted per replay key, so a budget without one could not hold them.
        return 422, "replay_key_required", "A call that sends X-Budget-Id sends X-Replay-Key too."
    return CallHeaders(ids, key or None, chosen)


def request_hash(body: Mapping[str, Any], strip: Iterable[str] = ()) -> str:
    """SHA-256 of the body as the caller sent it, as canonical JSON with keys sorted, the per-attempt fields left out:
    the same bytes on a re-run give the same hash, and any change to what is asked gives another."""
    left_out = {*UNHASHED, *strip}
    kept = {k: v for k, v in body.items() if k not in left_out}
    canonical = json.dumps(kept, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def prompt_tokens(messages: Sequence[Json]) -> int:
    """A ceiling-side guess at the prompt's tokens, about four characters each, for the reservation only: the call
    settles to what the provider counts."""
    return max(1, len(json.dumps(messages, default=str)) // 4)


def recorded(done: Completion) -> str:
    """The answer as the replay row keeps it."""
    return json.dumps(
        {
            "text": done.text,
            "input_tokens": done.input_tokens,
            "output_tokens": done.output_tokens,
            "tool_calls": done.tool_calls,
            "ended": done.ended,
            "refusal": done.refusal,
        }
    )


def replayed(response: str) -> Completion:
    """A replay row's answer, as the provider gave it."""
    data = json_object(json.loads(response))
    text = data.get("text")
    calls = data.get("tool_calls")
    return Completion(
        text=None if text is None else str(text),
        input_tokens=int(str(data.get("input_tokens") or 0)),
        output_tokens=int(str(data.get("output_tokens") or 0)),
        tool_calls=[json_object(c) for c in calls] if isinstance(calls, list) else [],
        # A replayed reply ends the way the recorded one did, so a cut-off or filtered answer never replays as whole.
        ended=str(data["ended"]) if data.get("ended") else None,
        refusal=str(data["refusal"]) if data.get("refusal") else None,
    )


@dataclass
class StreamedAnswer:
    """A streamed reply put back together from its chunks, so a stream's replay row holds the same message a
    non-streamed reply would: the text concatenated, and each tool call's argument fragments joined by index."""

    parts: list[str] = field(default_factory=lambda: [])
    calls: dict[int, dict[str, Any]] = field(default_factory=lambda: {})
    ended: str | None = None

    def add(self, chunk: Json) -> None:
        choices = chunk.get("choices")
        for choice in choices if isinstance(choices, list) else []:
            if isinstance(choice, dict) and isinstance(finish := json_object(choice).get("finish_reason"), str):
                self.ended = finish
            delta = json_object(choice).get("delta") if isinstance(choice, dict) else None
            if not isinstance(delta, dict):
                continue
            content = delta.get("content")
            if isinstance(content, str):
                self.parts.append(content)
            calls = delta.get("tool_calls")
            for call in calls if isinstance(calls, list) else []:
                if isinstance(call, dict):
                    self._call(json_object(call))

    def _call(self, call: Json) -> None:
        index = int(str(call.get("index") or 0))
        found = self.calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        if call.get("id"):
            found["id"] = str(call["id"])
        function = call.get("function")
        if isinstance(function, dict):
            fn = json_object(function)
            if fn.get("name"):
                found["function"]["name"] = str(fn["name"])
            found["function"]["arguments"] += str(fn.get("arguments") or "")

    def completion(self, input_tokens: int, output_tokens: int) -> Completion:
        calls = [self.calls[i] for i in sorted(self.calls)]
        text = "".join(self.parts)
        # A reply of tool calls only has no text, as a non-streamed one says with a null content.
        return Completion(
            text=text if text or not calls else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_calls=calls,
            ended=self.ended,
        )
