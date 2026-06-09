# home-os

GitOps source-of-truth for a self-hosted Kubernetes homelab — Helm charts,
values, and Kustomize manifests that **ArgoCD** reconciles onto live clusters.
No application code, no build step: change a chart or a value, ArgoCD applies
it. Almost every Application is `automated` (`prune` + `selfHeal`), so merged
changes go live and out-of-band edits are reverted.

The OS layer is **Talos Linux** (immutable). Storage is **Longhorn**, databases
**CloudNativePG**, ingress **Traefik**, certs **cert-manager**, secrets
**external-secrets** (AWS backend).

> **Deep architecture & conventions live in [`CLAUDE.md`](CLAUDE.md)** — the
> bootstrap chain, the two-cluster model, the `valuesObject` override pattern,
> and the bjw-s common-library gotchas are documented there in full.

## Layout

```
.
├── charts/
│   ├── cd/                    Root platform layer (chart `cd-tools`): renders the
│   │                          ArgoCD AppProjects + every platform Application, and
│   │                          manages itself. Start here.
│   ├── apps/                  Applications app-of-apps (chart `apps`): declares the
│   │                          user-facing apps, each pointing at a home-apps leaf.
│   ├── home-apps/             Leaf charts (jellyfin, keycloak-ha, redis-ha, music, …)
│   │                          + `common` — the bjw-s app-template, vendored locally.
│   ├── argocd/                ArgoCD install values (bootstrapped once, by hand).
│   ├── argocd-image-updater/  Image-updater configuration.
│   ├── cert/                  cert-manager issuers (chart `home-cert`).
│   ├── s3/                    Object-storage wiring.
│   └── storage/               Longhorn / storage classes.
├── cluster/                   Talos machine configs (controlplane / worker /
│                              worker-nvidia). Generated artifacts are gitignored.
└── serverless/k/              Kustomize apps (vymalo-shop, opfs-webauthn) wired in
                               as ArgoCD Applications from charts/apps.
```

## The big picture

1. **Talos** provisions the nodes (machine configs in `cluster/`).
2. **ArgoCD** is installed once, by hand (`charts/argocd`).
3. **`charts/cd`** (`cd-tools`) is the root: it renders every AppProject and
   platform Application (cert-manager, CloudNativePG, Traefik, external-secrets,
   knative/kserve, ARC runners, otel, s3, storage, nvidia…), plus an `apps`
   Application and a self-referencing `cd` Application — so the platform manages
   itself.
4. **`charts/apps`** (`apps`) fans out to the user-facing leaf charts under
   **`charts/home-apps/<app>`**, most wrapping the bjw-s `app-template`.
5. **`serverless/k/*`** Kustomize deployments are wired in as Applications too.

**Two clusters.** ArgoCD destinations target either `home-remote` (the Hetzner
box — full platform: external-secrets/AWS, cert-manager, Keycloak) or the
in-cluster `kubernetes.default.svc` (local; usually without those shared deps).
A change that works on `home-remote` may need TLS / secrets / oauth stripped for
the local variant.

**Override model.** Configure a leaf chart from its **Application definition**
(`source.helm.valuesObject` in `charts/apps` / `charts/cd` values) rather than
editing the leaf's `values.yaml` — ArgoCD deep-merges it over the chart defaults
(maps merge key-by-key; lists and scalars replace wholesale). See
[`CLAUDE.md`](CLAUDE.md) for the full pattern and gotchas.

## Validate a change

No test suite or CI — validation is rendering with Helm:

```bash
helm dependency build charts/<chart>   # once, for charts with a Chart.lock
helm template apps charts/apps          # render & sanity-check after a values edit
helm template cd   charts/cd
```

## Provisioning reference

### Talos images (image-factory schematics, Talos v1.12.0)

Build or tweak these at [factory.talos.dev](https://factory.talos.dev/); the
**schematic ID** is what you feed to Talos.

| Variant | System extensions | Schematic ID |
| --- | --- | --- |
| [Simple (x86)](https://factory.talos.dev/?arch=amd64&board=undefined&cmdline-set=true&extensions=-&extensions=siderolabs%2Fqemu-guest-agent&platform=metal&secureboot=undefined&target=metal&version=1.12.0) | `qemu-guest-agent` | `ce4c980550dd2ab1b17bbf2b08801c7eb59418eafe8f279833297925d67c7515` |
| [Longhorn-ready (x86)](https://factory.talos.dev/?arch=amd64&board=undefined&cmdline-set=true&extensions=-&extensions=siderolabs%2Fiscsi-tools&extensions=siderolabs%2Fqemu-guest-agent&extensions=siderolabs%2Futil-linux-tools&platform=metal&secureboot=undefined&target=metal&version=1.12.0) | `iscsi-tools`, `qemu-guest-agent`, `util-linux-tools` | `88d1f7a5c4f1d3aba7df787c448c1d3d008ed29cfb34af53fa0df4336a56040b` |
| [Nvidia-ready (x86)](https://factory.talos.dev/?arch=amd64&board=undefined&cmdline-set=true&extensions=-&extensions=siderolabs%2Fiscsi-tools&extensions=siderolabs%2Fnvidia-container-toolkit-production&extensions=siderolabs%2Fqemu-guest-agent&extensions=siderolabs%2Futil-linux-tools&extensions=siderolabs%2Fnonfree-kmod-nvidia-production&platform=metal&secureboot=undefined&target=metal&version=1.12.0) | `iscsi-tools`, `nonfree-kmod-nvidia-production`, `nvidia-container-toolkit-production`, `qemu-guest-agent`, `util-linux-tools` | `c35d5bd14fd96abc839f9f44f5effd00c48f654edb8a42648f4b2eb6051d1dd6` |

Example customization (Longhorn-ready):

```yaml
customization:
  systemExtensions:
    officialExtensions:
      - siderolabs/iscsi-tools
      - siderolabs/qemu-guest-agent
      - siderolabs/util-linux-tools
```

### Longhorn & Nvidia

- **Longhorn on Talos** — [integration guide](https://longhorn.io/docs/1.9.0/advanced-resources/os-distro-specific/talos-linux-support/). Managed by ArgoCD.
- **Nvidia on Talos** — [GPU guide](https://www.talos.dev/v1.11/talos-guides/configuration/nvidia-gpu). Managed by ArgoCD.

### CloudNativePG smoke test

CNPG is managed by ArgoCD. A quick throwaway cluster to confirm storage works:

```shell
kubectl apply -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: postgresql-storage
spec:
  instances: 2
  affinity:
    nodeSelector:
      data-node: "true"
  storage:
    storageClass: longhorn-local
    size: 1Gi
EOF
```
