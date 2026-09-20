# ci-cache

RustFS object storage dedicated to in-cluster CI build caches on the
`netcup-k8s` cluster, namespace `ci-cache`.

## Why this exists

CI workloads on `netcup-k8s` (ARC GitHub runners, turbo-cache) previously
cached against the shared `charts/s3` instance over the public internet
(`s3.ssegning.me`) or against `turbo-cache-api.ai.camer.digital`. That put
high-volume, disposable cache traffic on the public path for no reason: every
consumer already runs on the same cluster as the object store. This chart
gives CI its own RustFS instance reachable only from inside `netcup-k8s`, so
cache reads/writes never leave the cluster network.

- **Cluster:** `netcup-k8s` (`kubectl` context `admin@netcup`)
- **Namespace:** `ci-cache`
- **In-cluster endpoint:** `http://rustfs-svc.ci-cache.svc.cluster.local:9000`
- **Console:** enabled on `:9001` but deliberately NOT admitted by the
  NetworkPolicy — it is administration surface with no in-cluster consumer.
  Reach it with
  `kubectl --context admin@netcup -n ci-cache port-forward svc/rustfs-svc 9001:9001`
  (kubelet-mediated, so NetworkPolicy does not apply).

## Buckets

| Bucket | Written by | Lifecycle |
| --- | --- | --- |
| `turbo-cache` | the turborepo remote-cache server (npm/Turbo task outputs) | expires after 30 days |
| `sc-cache` | sccache (Rust compilation cache) | expires after 30 days |
| `gha-cache` | general-purpose bucket for jobs that cache to S3 directly | expires after 14 days |
| `build-artifacts` | job build outputs | expires after 30 days |

Lifecycle rules exist because the volume is a fixed-size Longhorn claim
(`200Gi`) — caches must expire or the volume fills.

## How the runners pick this up automatically

Nothing in a workflow has to opt in. `charts/cd/templates/arc-runner-pools.yaml`
presets the environment on every runner container, sourced from the
`arcRunnerCache` block in `charts/cd/values.yaml`:

| Env | Value | Effect |
| --- | --- | --- |
| `TURBO_API` | `http://turbo-cache.ci-cache.svc.cluster.local:3000` | `turbo build` hits the in-cluster remote cache |
| `TURBO_TEAM` / `TURBO_TOKEN` | per-pool team, shared token | namespaces the cache per org |
| `SCCACHE_ENDPOINT` / `SCCACHE_BUCKET` | `rustfs-svc.ci-cache…:9000` / `sc-cache` | `RUSTC_WRAPPER=sccache` writes here |
| `SCCACHE_S3_USE_SSL` | `false` | plaintext pod-to-pod hop; nothing terminates TLS in front of the ClusterIP |
| `AWS_ENDPOINT_URL_S3` | the RustFS URL | an *unconfigured* S3 client (`aws s3 cp`, any SDK) defaults here instead of AWS. The service-specific name only — the generic `AWS_ENDPOINT_URL` would redirect *every* AWS client (sts, ecr, …) here too |
| `AWS_REQUEST_CHECKSUM_CALCULATION`, `AWS_RESPONSE_CHECKSUM_VALIDATION` | `when_required` | newer AWS SDKs otherwise send CRC32 trailers RustFS rejects |
| `CI_ARTIFACTS_BUCKET` | `build-artifacts` | documented default so jobs need not hardcode a bucket |

Those names are an **unenforced contract**: the Service names `rustfs-svc` and
`turbo-cache`, this namespace, and the bucket names are fixed here and in
`charts/cd-ci/values.yaml`, while `charts/cd/values.yaml` restates them as
strings. Nothing fails at render time if they drift — every runner just
silently loses its cache. Change one side, change all three.

## Root credential trade-off

The RustFS root credential (`ci-cache-root`, synced from
`prod/artifact-cache/env` via ExternalSecret) is the same `artifact-cache`
identity the ARC runners and turbo-cache already hold elsewhere, rather than
a separate root plus per-user policies the way `charts/s3` does it. This
store holds nothing but disposable CI caches, has no ingress, and every
consumer would need `s3:*` on every bucket here anyway — a dedicated
provisioned user would add ceremony without adding isolation. See the
comment above `rootSecret` in `values.yaml` for how to split them later if
that trade-off ever needs revisiting.

## Registry pull-through caches

Runner pods are ephemeral (one per job): podman/buildah's graphroot is wiped
with the pod, and `STORAGE_DRIVER=vfs` copies every layer in full instead of
sharing it, so every job re-downloads its base images from upstream. This
chart runs two `registry:3.1.1` instances in proxy (pull-through cache) mode
to remove that cost:

| Service | In-cluster address | Upstream |
| --- | --- | --- |
| `registry-cache-dockerio` | `http://registry-cache-dockerio.ci-cache.svc.cluster.local:5000` | `https://registry-1.docker.io` |
| `registry-cache-ghcr` | `http://registry-cache-ghcr.ci-cache.svc.cluster.local:5000` | `https://ghcr.io` |

Measured locally: a cold pull of `alpine:3.20` through `registry:2` in proxy
mode took 41.2s; the same pull warm from the cache took 3.0s (~14x). Docker
Hub's anonymous pull limit is enforced per source IP, and netcup's nodes
share egress and can burst to ~40 concurrent runners, so an uncached burst
risks HTTP 429s surfacing mid-build as a confusing, unrelated-looking
failure — the cache also removes that risk.

**Why two Deployments instead of one:** `distribution`'s proxy mode accepts
exactly one `proxy.remoteurl` per instance — there's no multi-upstream proxy
mode to configure — so each upstream gets its own
Deployment/Service/PVC (`registryCache.upstreams` in `values.yaml`). A side
effect: each mirror serves the exact same repository paths as its own
upstream, so there's no cross-registry naming to reconcile.

**No credentials are configured on these, on purpose.** A pull-through cache
holding an upstream credential would let any pod in the cluster pull that
upstream's *private* images without ever presenting the real pull secret.
Left anonymous, public images cache normally, and a miss on a private image
falls through to the primary upstream (this is how `containers/image`
resolves a mirror miss) — private pulls still work, they're just never
cached. That fallback-on-miss is what makes "no credentials" safe here, not
a missing feature.

**NetworkPolicy trap:** the pre-existing `ci-cache-rustfs` NetworkPolicy
selects `app.kubernetes.io/instance: ci-cache`, which every pod in this
chart carries — including the registry caches. The allowed ingress ports
are now values-driven (`networkPolicy.ports: [9000, 5000, 3000]`) precisely
because a port missing from that list is a pod that renders and schedules
fine but is silently unreachable from every runner pod. Adding a workload to
this chart means adding its port to that list — and, conversely, RustFS's
console port is absent from it on purpose (see above).

**What this chart does NOT wire up:**

- Pointing runner containers at these mirrors (an `/etc/containers/registries.conf`
  with `[[registry.mirror]]` entries for `docker.io` → `registry-cache-dockerio`
  and `ghcr.io` → `registry-cache-ghcr`) is applied by
  `charts/cd/templates/arc-runner-pools.yaml`, not by this chart. The two
  upstream names (`dockerio`, `ghcr`) in `values.yaml` are a contract with
  that file — rename one here and the other side must change too.
- Talos node-level pulls (`kubelet`/containerd pulling node images, e.g. for
  DaemonSets) are a **separate, currently unwired** concern. Routing those
  through these caches needs `machine.registries.mirrors` in the Talos
  machine config (`cluster/`), which this chart cannot reach — it only
  affects pods, not the node's own containerd.

## GitHub Actions cache server (`gha-cache`)

A self-hosted implementation of the GitHub Actions cache protocol
([falcondev-oss/github-actions-cache-server](https://github.com/falcondev-oss/github-actions-cache-server),
pinned to `9.8.0`), so `actions/cache` — and therefore `setup-node`'s,
`setup-java`'s, `setup-python`'s, and `setup-go`'s built-in `cache:` input,
plus Gradle's and pub's own opt-in use of the same action — stores to this
in-cluster RustFS instead of GitHub's real cache backend.

- **In-cluster address:** `http://gha-cache.ci-cache.svc.cluster.local:3000`
- **Backing bucket:** `gha-cache`
- **Object layout:** the server writes under a fixed key prefix inside the
  bucket, e.g. `gh-actions-cache/6398716841/parts/0` (verified with
  `rc ls --recursive`). The bucket's lifecycle rule has no prefix filter, so
  it already covers everything the server writes — don't add a prefix
  filter later without checking this.

### Retention: two numbers, deliberately different

| Setting | Value | Why |
| --- | --- | --- |
| `ghaCache.cleanupOlderThanDays` | 14 | The server's own cleanup job, backed by its sqlite index. |
| `gha-cache` bucket lifecycle (`provisioning.buckets`) | 21 | A backstop, one week longer. |

The server keeps a sqlite index of every object it has written to the
bucket. If the bucket's S3 lifecycle rule deleted an object first, the
server's index would still point at something that no longer exists — a
dangling reference. Making the server's own cleanup run first (14 days)
means that by the time the bucket rule could fire on the same object (21
days), the server has already forgotten about it through its own
bookkeeping. The bucket rule only exists to catch objects orphaned some
other way (e.g. a crash mid-write) — `ORPHANED_STORAGE_GRACE_PERIOD_HOURS`
(left at its default) is the mechanism actually meant for that case.

### Auth model: no shared secret

Unlike `TURBO_TOKEN`/`SCCACHE_ENDPOINT` style shared credentials, this
server validates the runner's **real GitHub Actions JWT** on every request
(`ACTIONS_TOKEN_ISSUER` defaults to `https://token.actions.githubusercontent.com`,
`SKIP_TOKEN_VALIDATION` left at its default `false`). Verified: a token
missing the `ac`, `repository_id`, or `scp` claims gets a specific 401, not
a generic one. This means:

- The server needs real egress to GitHub (to fetch JWKS for signature
  verification) — it is not purely cluster-internal like RustFS itself.
- There is no bearer token or URL secret to provision, mirror, or rotate.
- There is also no unauthenticated health route to probe — every
  meaningful HTTP path is token-gated, which is why the Deployment uses a
  `tcpSocket` readiness/liveness probe instead of an HTTP one.

### It proxies, it does not redirect

Verified end-to-end against a real RustFS backend (full
CreateCacheEntry → PUT blob → FinalizeCacheEntryUpload →
GetCacheEntryDownloadURL → GET round trip, byte-correct): the download URL
this server hands back streams the object through the pod itself
(`Transfer-Encoding: chunked`), it does **not** 302-redirect the client to
RustFS — even with `ENABLE_DIRECT_DOWNLOADS=true` set. Every cache blob
(node_modules, Gradle caches, often hundreds of MB) therefore transits this
one pod, which is why its `resources` in `values.yaml` are sized well above
a typical thin proxy.

### This does nothing until BOTH of these, owned by `charts/cd`, are true

1. **A patched runner image.** `actions/cache` v4.2+ talks to Cache Service
   v2 via `ACTIONS_RESULTS_URL`, and the runner process unconditionally
   overwrites that env var from the job context at startup — anything set
   on the pod is clobbered before the action ever reads it. The fix is a
   byte patch to `Runner.Worker.dll` renaming the UTF-16LE string
   `ACTIONS_RESULTS_URL` to `ACTIONS_RESULTS_ORL` so an externally-injected
   value survives. That patch lives in the `vymalo/arc-runners` image, not
   in this chart. (Notably, the upstream cache-server project's own
   pre-patched image shipped with this exact patch **missing** from the
   compiled DLL for three releases —
   [falcondev-oss/github-actions-cache-server#265](https://github.com/falcondev-oss/github-actions-cache-server/issues/265),
   open as of writing.)
2. **`ACTIONS_RESULTS_URL` actually set on runner pods**, in
   `charts/cd/templates/arc-runner-pools.yaml`.

If either is missing, `actions/cache` silently keeps talking to GitHub's
real backend and this server logs **zero** requests — there is no error,
just a cache that quietly never gets used. That is the documented upstream
failure mode, not a bug in this chart.

## Sync ordering (this bit is load-bearing)

| Wave | Resource | Why |
| --- | --- | --- |
| `-1` | `ExternalSecret ci-cache-root` | ArgoCD has a health check for ExternalSecret, so the Secret exists before anything mounts it |
| `0` | RustFS, both registry caches | the object store and the pull-through proxies have no cross-dependencies |
| `1` | provisioning Job (**Sync**-phase hook) | creates the buckets and imports lifecycle rules |
| `2` | `gha-cache` | the only workload that validates its bucket at startup |

The provisioning Job is a **Sync**-phase hook, not `PostSync`. `PostSync`
deadlocked on first install and the failure is worth remembering, because it
presents as an application bug rather than an ordering one:

```
gha-cache:  Failed to initialize storage: Bucket gha-cache does not exist
            → CrashLoopBackOff
ArgoCD:     phase=Running  msg=waiting for healthy state of apps/Deployment/gha-cache
Jobs:       No resources found
```

The server will not start without its bucket, so the Deployment never goes
Healthy, so the sync never completes, so the `PostSync` hook that would have
*created* the bucket never runs. Circular. Sync-phase hooks participate in
wave ordering, which breaks the cycle.

Adding a workload here means asking whether it needs a bucket to pre-exist.
If it does, it belongs at wave 2 or later — not wave 0 alongside RustFS.

## Validating a change

```bash
helm dependency build charts/ci-cache
helm template ci-cache charts/ci-cache --namespace ci-cache
```

Against the live cluster:

```bash
kubectl --context admin@netcup -n ci-cache get pods,pvc,svc,externalsecret
kubectl --context admin@netcup -n ci-cache logs job/ci-cache-provisioning
```

## Related

The `turbo-cache` Deployment that consumes the `turbo-cache` bucket lives in
this same `ci-cache` namespace but is a separate ArgoCD Application, defined
in `charts/cd-ci/values.yaml` — it is not part of this chart.
