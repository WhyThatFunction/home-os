# Commit message conventions

This repo uses **[Conventional Commits](https://www.conventionalcommits.org/)** —
a small, machine-checkable structure for commit subjects. It keeps history
readable, makes changelogs/releases automatable, and is **enforced** (see
[Enforcement](#enforcement)).

- **Validator (single source of truth):** [`tools/commit-lint.sh`](../tools/commit-lint.sh)
- **Enforced by:** the local `commit-msg` hook + the `Commit Lint` CI gate (both call that script).

---

## The format

```
<type>[optional scope][!]: <description>

[optional body — explain WHY, wrap ~72 cols]

[optional footer(s)]
```

- **`<type>`** — one of the [types below](#types). Lowercase. **Required.**
- **`[scope]`** — `(name)`, lowercase — the area touched (a chart/module/component name, or `deps`, `ci`, `docs`). Optional.
- **`!`** — breaking-change marker before the colon: `feat(api)!: …`. See [Breaking changes](#breaking-changes).
- **`: <description>`** — the mandatory `": "` separator then a **non-empty**, imperative summary (“add …”, not “added …”). No trailing period. Keep it ≤ ~100 chars (the validator nudges past that; it doesn’t fail).
- **body** — explain **why**, not what (the diff shows *what*). Substantive bodies are encouraged for non-trivial changes.
- **footers** — `BREAKING CHANGE: …`, `Co-Authored-By: …`, `Refs: #123`.

---

## Types

| Type | Use for |
|---|---|
| `feat` | New user-facing behavior / capability |
| `fix` | A bug fix |
| `perf` | Performance improvement, no behavior change |
| `refactor` | Restructure with no behavior change |
| `docs` | Documentation only |
| `revert` | Reverting a prior change |
| `chore` / `ci` / `build` / `test` / `style` | Maintenance, CI, build/deps, tests, formatting |

> If this repo later adopts **release-please** (or similar), the `type` also drives
> the version bump: `feat` → MINOR, `fix` → PATCH, `!`/`BREAKING CHANGE:` → MAJOR.
> Structuring commits now makes that a drop-in later.

---

## Breaking changes

Use `!` and/or a `BREAKING CHANGE:` footer:

```
feat(api)!: rename the auth header key

BREAKING CHANGE: `X-Old` → `X-New`; update callers before upgrading.
```

---

## The PR title matters too

If this repo squash-merges, the **PR title** is what lands on the default branch —
so it must itself be a valid Conventional Commit. The CI gate checks the PR title
**and** every non-merge commit in the PR.

---

## AI-assisted commits

Add the co-author trailer with the running model version:

```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

## Examples

**Good**

```
feat(cert): add self-signed-ca ClusterIssuer for internal TLS
fix(redis-ha): trust the internal CA on the haproxy sidecar
docs: document the two-cluster kubeconfig split
chore(deps): bump cert-manager to v1.16
refactor(cnpg)!: rename the backup bucket prefix
```

**Rejected**

| Subject | Why |
|---|---|
| `add a thing` | no type |
| `Feat(x): …` | type must be lowercase |
| `feature(x): …` | `feature` isn’t a valid type (use `feat`) |
| `fix: ` | empty description |
| `wip` / `update` | not Conventional |

Auto-generated `Merge …`, `Revert "…"`, and `fixup!/squash!` subjects are **skipped** (allowed).

---

## Enforcement

Two layers, both driven by the same validator so they can’t disagree:

### 1. Local `commit-msg` hook (reject at `git commit`)

Not installed automatically. Enable once per clone:

```bash
git config core.hooksPath .githooks
```

Bad messages are then rejected before the commit is created. Bypass a single
commit with `git commit --no-verify`.

### 2. CI gate — `Commit Lint`

[`.github/workflows/commit-lint.yml`](../.github/workflows/commit-lint.yml) runs on
every PR and validates the PR title + every non-merge commit, using the same
[`tools/commit-lint.sh`](../tools/commit-lint.sh) (no third-party actions / npm).

To make it **block merges**, add `commit-lint` to the default branch’s required
status checks (repo Settings → Branches / Rules). _(Not available on private repos
without a paid plan — the check still runs and reports.)_

### Changing the rules

Edit `TYPES` / `PATTERN` in [`tools/commit-lint.sh`](../tools/commit-lint.sh) — the
hook and CI both pick it up.
