"""Experiment 1 of docs/design/agents-v2/experiments.md: pause for approval in process A, resume in a fresh process B.

Usage: python experiment1.py pause STATEFILE [--two]   |   python experiment1.py resume STATEFILE approved|rejected
       python experiment1.py helper-pause STATEFILE    |   python experiment1.py helper-resume STATEFILE
"""

import hashlib
import json
import sys
from pathlib import Path

import httpx
import openai
from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models.openai import OpenAIModel
from strands.types._snapshot import Snapshot

LOG = {"requests": [], "tool_runs": []}
STRIP = {"stream", "user", "metadata", "stream_options"}


def _hash(body):
    b = {k: v for k, v in body.items() if k not in STRIP}
    return hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest()[:16]


def sse(chunks):
    out = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=out.encode())


def chunk(delta, finish=None):
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "scripted",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def tool_calls(calls):
    cs = [
        chunk(
            {
                "role": "assistant",
                "tool_calls": [
                    {"index": i, "id": cid, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                    for i, (cid, n, a) in enumerate(calls)
                ],
            }
        )
    ]
    cs.append(chunk({}, "tool_calls"))
    cs.append({**chunk({}), "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    return sse(cs)


def text(t):
    return sse(
        [
            chunk({"role": "assistant", "content": t}),
            chunk({}, "stop"),
            {**chunk({}), "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        ]
    )


def script(body):
    """The scripted model decides from the tool results already in the conversation."""
    msgs = body["messages"]
    sysmsg = next((m for m in msgs if m["role"] == "system"), {"content": ""})
    s = json.dumps(sysmsg.get("content"))
    done = {m.get("tool_call_id") for m in msgs if m["role"] == "tool"}
    if "HELPER" in s:
        if "h_w1" not in done:
            return tool_calls([("h_w1", "write_record", {"value": "from-helper"})])
        return text("helper done")
    if "OUTER" in s:
        if "o_a1" not in done:
            return tool_calls([("o_a1", "ask_helper", {"question": "do it"})])
        return text("outer done")
    two = "TWO" in s
    if "r1" not in done:
        return tool_calls([("r1", "read_record", {"key": "a"})])
    if two and not {"w1", "w2"} <= done:
        return tool_calls([("w1", "write_record", {"value": "x"}), ("w2", "write_record", {"value": "y"})])
    if not two and "w1" not in done:
        return tool_calls([("w1", "write_record", {"value": "x"})])
    return text("all done")


def handler(req: httpx.Request):
    body = json.loads(req.content)
    LOG["requests"].append(_hash(body))
    return script(body)


def model():
    client = openai.AsyncOpenAI(
        api_key="k",
        base_url="http://gateway.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return OpenAIModel(client=client, model_id="scripted")


@tool
def read_record(key: str) -> str:
    """Read a record."""
    LOG["tool_runs"].append(f"read:{key}")
    return f"value-of-{key}"


@tool
def write_record(value: str) -> str:
    """Write a record."""
    LOG["tool_runs"].append(f"write:{value}")
    return "written"


class Approval(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kw):
        registry.add_callback(BeforeToolCallEvent, self.before)

    def before(self, event: BeforeToolCallEvent):
        if event.tool_use["name"] != "write_record":
            return
        answer = event.interrupt("approval", reason={"tool": "write_record", "input": event.tool_use["input"]})
        if answer != "approved":
            event.cancel_tool = "The person refused this change."


def agent(system):
    return Agent(
        model=model(),
        tools=[read_record, write_record],
        hooks=[Approval()],
        system_prompt=system,
        callback_handler=None,
    )


def save(path, a, extra=None):
    snap = a.take_snapshot(preset="session").to_dict()
    blob = json.dumps({"snap": snap, "log": LOG, **(extra or {})}).encode()
    Path(path).write_bytes(blob)
    return len(blob)


def load(path):
    d = json.loads(Path(path).read_bytes())
    LOG["requests"] = d["log"]["requests"]
    LOG["tool_runs"] = d["log"]["tool_runs"]
    return d


def responses(interrupts, answer):
    return [{"interruptResponse": {"interruptId": i["id"], "response": answer}} for i in interrupts]


# --- helper: outer before_tool runs a nested agent; its pause becomes the outer pause -----------------

HELPER_SNAPS = {}  # tool_use_id -> helper snapshot dict, carried in the outer interrupt's reason


@tool
def ask_helper(question: str) -> str:
    """Ask a helper agent. The body never runs: the hook supplies the result."""
    LOG["tool_runs"].append("ask_helper_body")
    return "should not run"


class HelperHook(HookProvider):
    def register_hooks(self, registry, **kw):
        registry.add_callback(BeforeToolCallEvent, self.before)

    def before(self, event: BeforeToolCallEvent):
        if event.tool_use["name"] != "ask_helper":
            return
        tid = event.tool_use["toolUseId"]
        saved = HELPER_SNAPS.get(tid)
        if saved is not None:
            # Resumed: the outer interrupt already holds its answer, so `interrupt` returns it without raising. The
            # helper is rebuilt from its saved state and answered; it makes no model call it made before the pause.
            ans = event.interrupt("helper_pause")
            h = agent("HELPER")
            h.load_snapshot(Snapshot.from_dict(saved["snap"]))
            r = h(responses(saved["interrupts"], ans))
        else:
            h = agent("HELPER")
            r = h(event.tool_use["input"]["question"])
            if r.stop_reason == "interrupt":
                ints = [i.to_dict() for i in r.interrupts]
                HELPER_SNAPS[tid] = {"snap": h.take_snapshot(preset="session").to_dict(), "interrupts": ints}
                event.interrupt("helper_pause", reason={"helper_interrupts": ints})
        event.cancel_tool = False
        result_text = str(r)
        event.selected_tool = None

        # Supply the helper's reply as the tool result by replacing the tool with a constant one.
        @tool(name="ask_helper")
        def _const(question: str) -> str:
            """Helper reply."""
            return result_text

        event.selected_tool = _const


def outer():
    return Agent(
        model=model(),
        tools=[ask_helper, write_record],
        hooks=[HelperHook()],
        system_prompt="OUTER",
        callback_handler=None,
    )


def main():
    mode, path = sys.argv[1], sys.argv[2]
    if mode == "pause":
        two = "--two" in sys.argv
        a = agent("TWO" if two else "ONE")
        r = a("do the thing")
        ints = [i.to_dict() for i in r.interrupts or []]
        n = save(path, a, {"interrupts": ints, "system": "TWO" if two else "ONE"})
        print(json.dumps({"stop": r.stop_reason, "interrupts": len(ints), "bytes": n, "log": LOG}))
    elif mode == "resume":
        d = load(path)
        a = agent(d["system"])
        a.load_snapshot(Snapshot.from_dict(d["snap"]))
        r = a(responses(d["interrupts"], sys.argv[3]))
        print(
            json.dumps(
                {
                    "stop": r.stop_reason,
                    "text": str(r).strip(),
                    "log": LOG,
                    "snap_bytes_after": len(json.dumps(a.take_snapshot(preset="session").to_dict())),
                }
            )
        )
    elif mode == "reload10":
        d = load(path)
        sizes = []
        a = agent(d["system"])
        for _ in range(10):
            a.load_snapshot(Snapshot.from_dict(d["snap"]))
            snap = a.take_snapshot(preset="session").to_dict()
            d["snap"] = snap
            sizes.append(len(json.dumps(snap)))
        print(json.dumps({"sizes": sizes}))
    elif mode == "helper-pause":
        o = outer()
        r = o("go")
        ints = [i.to_dict() for i in r.interrupts or []]
        n = save(path, o, {"interrupts": ints, "helpers": HELPER_SNAPS})
        print(json.dumps({"stop": r.stop_reason, "interrupts": [i["name"] for i in ints], "bytes": n, "log": LOG}))
    elif mode == "helper-resume":
        d = load(path)
        HELPER_SNAPS.update(d["helpers"])
        o = outer()
        o.load_snapshot(Snapshot.from_dict(d["snap"]))
        r = o(responses(d["interrupts"], "approved"))
        print(json.dumps({"stop": r.stop_reason, "text": str(r).strip(), "log": LOG}))


main()
