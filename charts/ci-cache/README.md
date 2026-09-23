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

## Package-download caching is already covered — don't add a node-level cache

`actions/cache` and `Swatinem/rust-cache` already route to the `gha-cache`
server in this chart, because the runner pods set `ACTIONS_RESULTS_URL` and
the runner image carries the `Runner.Worker.dll` patch that stops the runner
overwriting it. Verified live on 2026-09-20: **15 cache entries, 4.5 GB**, in
`s3://gha-cache/gh-actions-cache/` on this cluster's RustFS.

Every repository that compiles Rust in these orgs already caches the cargo
registry through that path — `vaam-apps/vaam-apps` via `Swatinem/rust-cache@v2`
in three jobs, `vaam-store/mobile` via `actions/cache@v4` on `~/.cargo/registry`,
`~/.cargo/git` and its `target/`. So the cargo, pnpm, pub, Gradle and pip
caches are in-cluster and repo-scoped today.

A `hostPath` cache shared across runner pods (a recurring suggestion, since it
needs no workflow changes) would be a **regression**, for four reasons — each
one checked, not assumed:

1. **No isolation.** `vymalo`, `vaam-store` and `vaam-apps` runners share
   nodes, so one org's job would write the package store another org's job
   executes from. `gha-cache` derives its scope from the `repository_id` claim
   in the runner's GitHub JWT and rejects a token without it, so it isolates
   per repository by construction. (Runner pods are already `privileged`, so
   this is not a new trust boundary — but it lowers the bar from "escape the
   container" to "write a file", and it catches accidents as well as attacks.)
2. **Unbounded.** `emptyDir` has `sizeLimit`; **`hostPath` has none**. It
   writes to the node root filesystem with no quota and no GC, so a runaway
   store fills the disk and evicts every pod on that node.
3. **It breaks cargo's locking.** Cargo's inter-process locks live at
   `$CARGO_HOME/.package-cache` and `.package-cache-mutate`, NOT inside
   `registry/` (verified by running `cargo fetch` in the runner image). Sharing
   `registry/` while leaving `$CARGO_HOME` pod-local gives every pod a private
   lock over a shared tree — mutual exclusion defeated, with up to 10 runners
   per node.
4. **`chown -R` on every pod start** walks every inode, getting slower exactly
   as the cache becomes worth having.

If a repository is genuinely missing package caching, add `actions/cache` or
`Swatinem/rust-cache` to that workflow. One line, repo-scoped, bounded, and it
lands here.

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

## The provisioning Job guarantees ordering, not persistence — the CronJob covers the rest

The Sync-phase hook above only ever runs when ArgoCD performs a sync. If the
RustFS PVC is replaced while the Application is already `Synced`, nothing in
this chart's manifests changes, so ArgoCD performs no sync, so the hook never
re-runs — every bucket silently disappears with nothing to trigger their
recreation. This already happened once in production: the buckets had to be
created by hand in-cluster to unblock CI. It's broader than the one server
that complains loudly — only `gha-cache`, of the consumers **this chart**
deploys, validates its bucket at startup and CrashLoops; a missing
`sc-cache` bucket instead fails every Rust CI job at a tool-*install* step,
which reads as an unrelated tooling problem until you think to check the
buckets. There is at least one other consumer this chart does not deploy
and so cannot speak for: `turbo-cache-netcup`
(`charts/cd-ci/values.yaml`, `STORAGE_PROVIDER: s3` / `STORAGE_PATH:
turbo-cache` against this same RustFS), a third-party chart on a floating
`targetRevision: 0.1.*` whose own startup behaviour against a missing
bucket is unverified from here.

`provisioning/cronjob.yaml` (`ci-cache-provisioning-reconcile`) closes that
gap: it runs the exact same idempotent script — shared with the Job via
`templates/_helpers.tpl`'s `ci-cache.provisioning.script` and
`ci-cache.provisioning.podTemplate`, not copy-pasted — on a schedule
(`provisioning.reconcile.schedule`, default every 15 minutes). It carries no
ArgoCD hook annotation; it's an ordinary managed resource, because it is the
continuous reconciler for an invariant no Kubernetes controller watches (S3
buckets are not Kubernetes objects) rather than a step in the sync sequence.

Both stay, deliberately:

- The **Sync-phase Job** is the only thing that guarantees provisioning
  happens *before* wave 2 (`gha-cache`) on a first install. A CronJob's
  schedule cannot make that promise.
- The **CronJob** heals a bucket lost between syncs — a replaced PVC, or
  someone deleting a bucket by hand — which the Job structurally cannot do,
  since nothing about that event causes ArgoCD to sync.

`concurrencyPolicy: Forbid` because two provisioners racing `bucket create`
buys nothing; `successfulJobsHistoryLimit: 1` / `failedJobsHistoryLimit: 3`
so a 15-minute schedule doesn't accumulate Job objects forever;
`startingDeadlineSeconds` (defaulted in the template, not only in
`values.yaml`, so an explicit `null` override can't silently unset the
guard) so a missed run is skipped rather than backlogged;
`activeDeadlineSeconds: 600` on the `jobTemplate` so a `rustfs-svc` endpoint
that accepts a connection but never answers can't wedge the reconciler
pod forever — the readiness loop in the script bounds attempt *count*
(60 x 5s), not attempt *duration*, and no `rc` call carries its own
timeout. This ships live — durability for a production CI dependency is
not the kind of thing to gate behind an opt-in flag.

**This reconciler is authoritative, not additive — it overwrites drift on
every run, including a deliberate one.** `bucket lifecycle rule import`
replaces a bucket's *entire* lifecycle configuration (see the comment in
`provisioning/config.yaml`), so the script is idempotent with respect to
this chart's declared state, not merely non-destructive: it is designed to
overwrite anything that disagrees with `values.yaml`, which is what makes
it fit for reconciling drift at all. On `main` that only fires at sync
time; with this CronJob it fires up to every 15 minutes. Concretely: if
someone lengthens or removes `build-artifacts`' `ci-cache-expiry` rule by
hand during an incident, to stop a 30-day expiry from deleting objects
they still need, this CronJob reverts that change within one schedule
tick and the objects expire on the chart's original schedule — silently,
with no event or alert. Change the bucket's lifecycle in `values.yaml`
first if you need it to stick.

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
