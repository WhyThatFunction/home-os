# Contributing

This repository follows the [ADORSYS-GIS AI Governance](https://adorsys-gis.github.io/ai-governance/) discipline:
**AI may accelerate the work, but humans own intent, verification, and consequences.**

## How to contribute

- **Open issues** with the structured forms — [Epic](.github/ISSUE_TEMPLATE/epic.yml),
  [User Story](.github/ISSUE_TEMPLATE/user-story.yml), or
  [Development Ticket](.github/ISSUE_TEMPLATE/dev-ticket.yml). Blank issues are disabled on purpose.
- **Open pull requests** using the [pull request template](.github/PULL_REQUEST_TEMPLATE.md). Fill in every section.
- Always complete the **AI Usage Declaration**, link a **source of truth**, and attach **verification evidence**.

## Definition of Ready / Done gates

Work is **Ready** only when its intent is clear, its source of truth is linked, its scope and acceptance criteria are explicit, and any AI-generated content has been reviewed by a human. Work is **Done** only when acceptance criteria are met, tests pass, verification evidence is attached, and a named human owner accepts responsibility for the result. A governance CI check enforces that every PR body declares AI usage, references a source of truth, and shows verification evidence — see the [AI Working Agreement](https://adorsys-gis.github.io/ai-governance/12-ai-working-agreement) and the [Doctrine](https://adorsys-gis.github.io/ai-governance/13-doctrine).

## Working with AI code review

Automated AI reviewers (Codex, Copilot, and the like) are **advisory — never a merge gate.** Only
**deterministic** checks (the governance CI check, linting, tests) may block a merge, because their
output is reproducible and cannot be confabulated. Keep AI review as a non-required status check.

**Every AI-review finding is a claim, not a verdict.** Before acting on one that asserts a specific
value or behavior, verify it against the actual cited lines. AI reviewers pattern-match known bug
*shapes* and will confidently assert details about code they did not actually read — especially code
in another repository (e.g. a reusable workflow referenced by SHA). The doctrine applies to the
reviewer too: **AI output is not truth.**

### When a finding is a false positive, close the loop — don't just ignore it

1. **Reply with the evidence** — the exact lines or command output that disprove it.
2. **React 👎** on the finding.
3. **Resolve the conversation.**

This three-step loop is not busywork; each step does something silent-ignoring does not:

- **👎 is the only lever that reduces recurrence.** It is the reviewer's feedback channel. Without it,
  the same confabulation fires again every time its trigger reappears — a single false "empty marker"
  finding recurred *three times* across PRs precisely because it was refuted in prose but never
  down-voted.
- **Resolving preserves signal-to-noise.** Real findings get buried under known-false ones if threads
  stay open; resolution stops both humans and the bot from re-litigating settled points.
- **The evidence reply is an audit trail.** The next person — or AI — who hits the same flag finds the
  refutation in-thread and does not have to re-verify from scratch. Silently ignoring a false positive
  looks unaddressed, erodes trust in the review, and teaches the bot nothing.
