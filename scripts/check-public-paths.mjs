#!/usr/bin/env node
// Refuses a tracked file that names a local-only path (PRIVATE below), which a reader of the repository does not have.
// Usage: check-public-paths.mjs [--self-test] [file...]   (files given: only those; scripts/verify-staged.sh passes a
// commit's staged files, so a one-file commit does not read every tracked file)
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

// Only hidden folders and whole file paths are matched: plain words such as `evidence/` also name object-store prefixes.
const dot = (name) => `.${name}/`;
const PRIVATE = [
  dot("claude"),
  dot("cursor"),
  ["docs", "agent-handoff.md"].join("/"),
];
const NEVER_SENT = [...PRIVATE, "shape/", "evidence/"];
// The skills generated from docs/guide/skills/ are tracked, so a path under them is public: ops-* and `usecase`.
const PUBLISHED = [
  `${dot("claude")}skills/ops-`,
  `${dot("claude")}skills/usecase/`,
];
// Ignore files name private folders on purpose; they point at nothing.
const IGNORE_FILE = /(^|\/)\.[a-z]*ignore$|\.dockerignore$/;
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const MENTION = new RegExp(
  `(?<![\\w/.-])(?:\\.\\./)*(?:\\./)?(?:${PRIVATE.map(escape).join("|")})`,
  "g",
);

export function mentions(path, text) {
  const published = PUBLISHED.some((p) => path.startsWith(p));
  if (
    IGNORE_FILE.test(path) ||
    (!published &&
      NEVER_SENT.some(
        (p) => path === p || (p.endsWith("/") && path.startsWith(p)),
      ))
  )
    return [];
  const out = [];
  for (const m of text.matchAll(MENTION)) {
    const named = text.slice(m.index).replace(/^(\.\.\/)*(\.\/)?/, "");
    if (PUBLISHED.some((p) => named.startsWith(p))) continue;
    out.push(
      `${path}:${text.slice(0, m.index).split("\n").length}  ${text
        .slice(m.index)
        .split(/[\s`'")\],;]/)[0]
        .slice(0, 70)}`,
    );
  }
  return out;
}

function selfTest() {
  const [local, agents] = [dot("cursor"), dot("claude")];
  const cases = [
    ["docs/a.md", `See \`${local}evidence/500/uc-red.txt\`.`, 1],
    ["services/x/m.py", `# (${local}wiki/decisions/x.md)`, 1],
    ["docs/a.md", `Linked from ../../${agents}commands/x.md`, 1],
    [`${local}wiki/a.md`, `${local}specs/x`, 0],
    [".gitignore", local, 0],
    [`apps/x/${agents}settings.json`, `apps/x/${agents}settings.json`, 0],
    ["docs/a.md", 'evidenceDir("500", "uc")', 0],
    ["docs/a.md", `Generated into \`${agents}skills/ops-run/SKILL.md\`.`, 0],
    ["docs/a.md", `Not \`${agents}skills/spec/SKILL.md\`.`, 1],
    [`${agents}skills/ops-run/SKILL.md`, `See ${local}specs/x`, 1],
  ];
  const bad = cases.filter(([p, t, n]) => mentions(p, t).length !== n);
  for (const c of bad)
    console.log(`FAIL ${c[0]}: ${JSON.stringify(c[1])} expected ${c[2]}`);
  return bad.length === 0;
}

if (process.argv.includes("--self-test")) process.exit(selfTest() ? 0 : 1);
const named = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const files = named.length
  ? named
  : execFileSync("git", ["ls-files", "-z"], {
      encoding: "utf8",
      maxBuffer: 64 << 20,
    })
      .split("\0")
      .filter(Boolean);
const hits = [];
for (const f of files) {
  let text;
  try {
    text = readFileSync(f, "utf8");
  } catch {
    continue;
  }
  if (text.includes("\0")) continue;
  hits.push(...mentions(f, text));
}
if (hits.length) {
  console.error(
    `check-public-paths: ${hits.length} private path(s) in files the public repo receives; cite docs/ instead:\n${hits.map((h) => `  ${h}`).join("\n")}`,
  );
  process.exit(1);
}
console.log(`check-public-paths: ${files.length} files clean`);
