# The Ops Assistant

Status: current. What the assistant does in a chat, and how it uses the Apps your team turned on.

The Ops Assistant answers in a chat by looking things up in your team's Apps, then replying with what it read. It acts
as you, so it reaches only what your own sign-in allows.

## A checklist for longer asks

An ask that needs several lookups, more than one App, or a change shows a short checklist above the answer. The assistant
ticks each step off as it finishes it.

## When a sign-in is needed

If a step needs an App you have not connected, the assistant stops at that step and shows a **Connect** card. Press it,
sign in, and the chat carries on at the same step. Nothing is retyped.

## Think harder

A reply that took a plan or several lookups offers **Think harder**. One press answers the same question again on the
deeper model. Writing "think harder" in a message, alone or with the question, does the same.

## Saving to an App

Before it changes anything in an App, the assistant reads the change back to you. It writes only after you say **Save**.
Until then nothing in the App has changed.

## Follow-ups

- **Reused reads.** A chat reuses what it already read from an App for 5 minutes, so a follow-up answers faster. The reply
  says when it used an earlier read. A save to that App clears the reused reads, so the next look reads the App again.
- **Suggestion chips.** Under a reply, short chips offer likely next questions. Press one to ask it.
- **Memories.** The assistant suggests what to remember and asks first. It keeps nothing silently.

## Which App and which account

- A chat uses the Apps your team turned on. Before your first message, the chat's connector picker lets you leave an App
  out of that chat.
- With two accounts of the same App connected and no default, the assistant asks which one to use. Your pick becomes the
  default for calls that name no account.
- An App your team has off shows a card with **Ask an admin**.

See [Apps](apps.md#connectors) for Connectors, where you manage your sign-ins.
