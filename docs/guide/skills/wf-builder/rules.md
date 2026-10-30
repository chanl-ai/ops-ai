# /wf-builder rules

Status: current. What every workflow the skill draws must follow, beside the engine's own checks.

| Rule | Why |
|---|---|
| Use only the step types `wf_builder.py catalog` lists on the named profile | A type written from memory may not exist there, or may take other parameters |
| Start from a seeded example (`examples.md`) and change it | The examples pass the engine's checks and run on a dev stack |
| A workflow a person starts begins with a Request trigger whose `inputSchema` names each input, with a `title` | The console's start form, a hosted form and a file's columns all read those titles |
| Two sources of the same facts meet at a Join, then Combine facts | Combine facts reads both sources only once both have arrived |
| When sources can disagree, set Combine facts' `onDisagreement` to `port` and send `disagree` to a Human review | A disagreement is settled by a person, never picked silently |
| Every way out of a step that can fail (`error`, `refused`, `timeout`) goes somewhere, and a failure End sets `result: failed` | The run then says which step failed and why |
| A step that calls a system names an operation the team's tools serve | The engine checks the operation exists when the workflow is saved |
| Create only when the developer says so; on a profile that is not local, only with the workflow id typed back | A created workflow is live for the whole team |
