# ADR-0018 Template copies take updates field by field against a stored base

Status: proposed, 2026-11-10. Accepted when a maintainer accepts it. Supersedes, for updates only, the apps design's
rule that taking a template update makes a whole new draft and drops the team's edits; that design's states, routes and
confirm-before-dropping stay, as reset.

## Context

A team adds an agent, skill or workflow from a plugin's template and gets its own copy: an ordinary record with its own
versions and publish review, and a `template_copies` row that says where it came from. Taking a newer template made a
whole new draft from the template, after the person confirmed the edits it would drop. That held for two reasons in
the code: nothing kept the body a copy was made from, so a merge had no base (the row kept only digests, and a moved
plugin pin keeps one commit); and a save rewrites an unpublished draft in place, so once the team saved over the
install draft its edits could not be told apart from the install. Teams edit their copies often, and a whole-copy
update drops every edit on every edited copy.

## Decision

| Part | Rule |
|---|---|
| Base | Each copy link stores the template body it was last made or merged against, binding fields left out and no choices applied, in the same statement that writes the row (`store/template_copies.py`, column `base`) |
| Merge | An update compares base, the copy's newest version and the template now, field by field over the kind's own store field list (`ops_service_kit.template_merge`): a field only the template changed is taken; a field only the team changed is kept; a field both changed is a conflict kept as the team's unless the person chooses the template's |
| Bindings | Name, model and knowledge bases (agents) and name, slug and knowledge bases (skills) are the team's and never part of an update |
| Versions | The result is saved through the kind's own save, so a published version, or a draft a publish request names, never changes; an open draft nobody asked to publish is merged into |
| Stale | A take names the template digest and record digest it reviewed; if either moved it is refused with 409 `update_stale` and nothing is saved |
| Reset | Reset keeps the old behaviour: a draft from the template with the bindings kept, after a confirm that lists the edits it drops |
| Detach | A detached copy is the team's own, takes no update, and its template is offered again for a fresh copy |
| Workflows | Merge as a whole definition, by digest, until a node-by-node rule is decided |
| Strictness | A merge of a guardrail or an approval setting never ends less strict than the team's value |

## Consequences

| Consequence | Detail |
|---|---|
| Storage | One JSON column per copy link; a skill or agent body is a few kilobytes |
| One copy per template | A team holds one live copy of a template at any version; Add after a pin moves answers that copy |
| Older consoles | A body of `{confirm: true}` with no mode is a reset, which is what such a console meant |
| Links made before the base | Their first update uses the record's version whose digest the link names as base; with none, every difference is a conflict kept as the team's, so nothing is lost |
| Field lists | The store's field list is the one list an update compares; the templates router keeps none of its own |
