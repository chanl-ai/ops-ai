"""Experiment 3 of docs/design/agents-v2/experiments.md, steps 1 to 4 and part a: the events `stream_async` yields for
five scripted turns, and what arrives when a turn is cancelled mid-stream.

Usage: python strands_stream_events.py
"""

import asyncio
import inspect
import json

import httpx
import openai
from pydantic import BaseModel
from strands import Agent, tool
from strands.models.openai import OpenAIModel

USAGE = {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15,
    "prompt_tokens_details": {"cached_tokens": 4},
}


def chunk(delta, finish=None):
    return {
        "id": "c",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "scripted",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def sse(chunks):
    chunks = [*chunks, {**chunk({}), "choices": [], "usage": USAGE}]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def text(*pieces):
    return sse([*(chunk({"role": "assistant", "content": p}) for p in pieces), chunk({}, "stop")])


def calls(*named):
    tcs = [
        {"index": i, "id": cid, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
        for i, (cid, n, a) in enumerate(named)
    ]
    return sse([chunk({"role": "assistant", "tool_calls": tcs}), chunk({}, "tool_calls")])


def script(kind):
    def answer(req: httpx.Request):
        msgs = json.loads(req.content)["messages"]
        done = {m.get("tool_call_id") for m in msgs if m["role"] == "tool"}
        if kind == "text":
            return text("Hel", "lo ", "there")
        if kind == "one_tool":
            return text("found it") if "t1" in done else calls(("t1", "lookup", {"key": "a"}))
        if kind == "two_tools":
            return (
                text("both")
                if {"t1", "t2"} <= done
                else calls(("t1", "lookup", {"key": "a"}), ("t2", "lookup", {"key": "b"}))
            )
        if kind == "typed":
            # Strands asks for the typed answer through a tool named after the output model.
            return calls(("s1", "Answer", {"value": "42"}))
        if kind == "steps_limit":
            return calls((f"t{len(done)}", "lookup", {"key": str(len(done))}))
        if kind == "cancel":
            return text("one ", "two ", "three ", "four")
        raise AssertionError(kind)

    return answer


@tool
def lookup(key: str) -> str:
    """Look a key up."""
    return f"value of {key}"


def agent(kind, **kw):
    client = openai.AsyncOpenAI(
        api_key="k",
        base_url="http://gateway.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(script(kind))),
    )
    return Agent(model=OpenAIModel(client=client, model_id="scripted"), tools=[lookup], callback_handler=None, **kw)


def shape(event):
    """One event as its keys, with the inner event's type for model stream events."""
    keys = sorted(
        k
        for k in event
        if k
        not in {
            "agent",
            "event_loop_cycle_id",
            "event_loop_cycle_trace",
            "event_loop_cycle_span",
            "request_state",
            "invocation_state",
            "event_loop_parent_span",
            "model",
            "messages",
            "system_prompt",
            "tool_config",
            "event_loop_parent_cycle_id",
        }
    )
    inner = event.get("event")
    if isinstance(inner, dict):
        keys = [*keys, "event." + ",".join(sorted(inner))]
    return "+".join(keys)


async def turn(kind, **kw):
    class Answer(BaseModel):
        value: str

    seen, texts, usage, stop = [], [], None, None
    a = agent(kind)
    try:
        if kind == "typed":
            stream = a.stream_async("go", structured_output_model=Answer)
        elif kind == "steps_limit":
            stream = a.stream_async("go", limits={"turns": 3})
        else:
            stream = a.stream_async("go")
        async for e in stream:
            seen.append(shape(e))
            if "data" in e:
                texts.append(e["data"])
            if "result" in e:
                stop = str(e["result"].stop_reason)
                usage = e["result"].metrics.accumulated_usage
            if kind == "cancel" and len(texts) == 2:
                a.cancel()
    except Exception as err:
        seen.append(f"raised {type(err).__name__}: {err}")
    distinct = list(dict.fromkeys(seen))
    print(
        json.dumps(
            {
                "turn": kind,
                "events": len(seen),
                "distinct": distinct,
                "text_pieces": texts,
                "stop": stop,
                "usage": usage,
            },
            default=str,
        )
    )


async def main():
    for kind in ("text", "one_tool", "two_tools", "typed", "steps_limit", "cancel"):
        await turn(kind)
    params = inspect.signature(OpenAIModel.__init__).parameters
    print(
        json.dumps(
            {
                "OpenAIModel.__init__": list(params),
                "AsyncOpenAI": [
                    p
                    for p in inspect.signature(openai.AsyncOpenAI.__init__).parameters
                    if p in {"base_url", "default_headers", "http_client"}
                ],
                "Agent.cancel": hasattr(Agent, "cancel"),
            }
        )
    )


asyncio.run(main())
