# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **GitOps repository** for a self-hosted Kubernetes platform. There is no
application source code and no build step — it is Helm charts + values +
Kustomize manifests that **ArgoCD** reconciles onto live clusters. You change
a chart or a value, ArgoCD applies it. Almost every Application is
`automated` with `prune: true` and `selfHeal: true`, so merged changes go
live without manual `kubectl apply`, and out-of-band edits get reverted.

The OS layer is **Talos Linux** (immutable). Storage is Longhorn; databases
are CloudNativePG; ingress is Traefik; certs are cert-manager; secrets are
external-secrets (AWS backend).

## Two clusters — know which you are targeting

ArgoCD `destination`s point at one of two clusters. This distinction drives
most config decisions:

- **`name: home-remote`** — a registered external cluster = the **Hetzner**
  box (x86 AMD). Most "real" production apps live here. It has the full
  platform: external-secrets/AWS, cert-manager issuers, Keycloak.
- **`server: https://kubernetes.default.svc`** — the **in-cluster** /
  **local** cluster (where ArgoCD itself runs). "Local deployment" means
  this destination; it generally lacks the AWS/Keycloak/cert-manager deps.

A change that works on `home-remote` may not work in-cluster if it depends on
those shared services — strip TLS/external-secrets/oauth for local variants.

## Bootstrap chain (read top-down to understand the whole system)

1. **Talos** provisions nodes. Machine configs live in `cluster/`;
   generated artifacts (`gen/`, `kubeconfig`, `talosconfig`) are
   **gitignored** — don't expect them in the tree.
2. **ArgoCD** is installed manually once (see `charts/argocd/README.md`:
   `helm upgrade -i -n argocd argocd argo/argo-cd --values values.yaml`).
3. **`charts/cd`** (chart name `cd-tools`) is the **root / platform layer**.
   Its `values.yaml` renders, via `templates/`:
   - ArgoCD repo-credential Secrets (`argoCdConfigs.secretMap`)
   - all **AppProjects** (`projects:` → `templates/projects.yaml`)
   - the **platform Applications** (`applications:` → `templates/applications.yaml`):
     cert-manager, CloudNativePG, Traefik, external-secrets, knative/kserve,
     **ARC GitHub runners**, otel, s3, storage, nvidia, etc. — plus an `apps`
     Application (`path: charts/apps`) and a self-referencing `cd` Application
     (`path: charts/cd`), so the platform manages itself.
4. **`charts/apps`** (chart name `apps`) is the **applications app-of-apps**.
   Its `values.yaml` `applications:` list declares the user-facing apps, each
   pointing at a leaf chart under `charts/home-apps/<app>`.
5. **`charts/home-apps/<app>`** are the leaf charts (jellyfin, keycloak-ha,
   redis-ha, music, endpoints, vaam-store-*, …). Most wrap the **bjw-s common
   library** (`app-template`). `charts/home-apps/common` is that library
   vendored locally and consumed by `apps`/`cd-tools` as `file://../home-apps/common`.
6. **`serverless/k/*`** — Kustomize deployments (vymalo-shop, opfs-webauthn)
   referenced as ArgoCD Applications from `charts/apps`.

Nesting goes deeper where needed: e.g. `vaam-store-prod-deployer` is itself
an app-of-apps that fans out child Applications ordered by **sync-waves**
(secrets → pg + redis → app).

## The override model (the most important pattern here)

The dominant way to configure a leaf chart is **not** editing the leaf
chart's `values.yaml` — it's `source.helm.valuesObject` (or
`sources[].helm.valuesObject`) **inside the Application definition** in
`charts/apps/values.yaml` / `charts/cd/values.yaml`. ArgoCD feeds that object
to Helm as an extra values layer, so it **deep-merges** over the chart
defaults: **maps merge key-by-key; lists and scalars replace wholesale.**
This lets you reshape an upstream/leaf chart from the Application without
forking it — the preferred approach in this repo. Use the same Application to
target different clusters with different `valuesObject`s (e.g. full-HA vs
single-node), and pin `helm.releaseName` when you need stable resource/DNS
names across clusters.

### bjw-s common gotchas (verified)

- **Disable a sub-resource with `enabled: false`** — honored (default true)
  on `controllers`, `service`, `ingress`, `persistence`, `configMaps`,
  `rawResources`.
- **PodDisruptionBudget ignores `enabled`** — it renders whenever the
  `podDisruptionBudget` map exists. To remove it, set
  `controllers.<c>.podDisruptionBudget: null` (Helm null-coalesce deletes the
  key).
- **rawResource names come from `forceRename`**, not `name`. With a single
  enabled rawResource the identifier isn't appended and the name collapses to
  the release fullname — use `forceRename: "{{ .Release.Name }}-foo"`.

## Commands

There is no test suite, Makefile, or CI. Validation = rendering with Helm.

```bash
# One-time per chart with remote/file deps (Chart.lock present for
# apps, cd, cert, s3, storage): fetch dependencies before rendering.
helm dependency build charts/<chart>

# Render & sanity-check a chart locally before committing a values change.
# This is the primary "did my edit work" loop — always run it.
helm template <release> charts/<chart>

# e.g. validate the two app-of-apps after editing their values:
helm template apps charts/apps
helm template cd   charts/cd

# Install/upgrade ArgoCD itself (rarely needed — see charts/argocd/README.md)
helm upgrade -i -n argocd argocd argo/argo-cd --values charts/argocd/values.yaml
```

To inspect a single Application's rendered output, render the parent chart
and grep the doc whose `name:` matches, or render the leaf chart directly
with the same `valuesObject` saved to a temp values file (`-f`).

## Working conventions

- **Commits go directly to `main`** — this repo has no PR flow and no
  required CI. Make the edit, validate with `helm template`, then commit.
- **`gh` and `git push` need the interactive zsh profile** for credentials:
  `zsh -i -c 'git push origin main'` (the token is loaded there; a plain
  non-interactive shell is unauthenticated).
- Repo URL appears as `whythatfunction` (lowercase) in some values but the
  canonical remote is `github.com/WhyThatFunction/home-os` — both resolve.

<!-- ai-governance:stanza -->
## AI Governance

<!-- BEGIN: AI Governance stanza (managed by ADORSYS-GIS/ai-governance) -->
## AI Governance

AI may accelerate the work, but humans own intent, verification, and consequences.
AI output is not truth: review AI-generated code as untrusted, and never submit work you cannot explain.

When opening issues or pull requests in this repo:

- Use the provided **issue forms** (Epic, User Story, Dev Ticket) and the **pull request template** — do not open blank issues/PRs.
- Fill in the **AI Usage Declaration** honestly (what AI was used for, what you verified).
- Include a **source-of-truth link** (a URL or `#123` reference). No source of truth means the work is not ready.
- Provide **verification evidence** (commands, logs, links, or checked verification boxes). No evidence means it is not done.

Source of truth and full doctrine: https://adorsys-gis.github.io/ai-governance/
This stanza is intentionally thin — read the site; do not duplicate the doctrine here.
<!-- END: AI Governance stanza -->
