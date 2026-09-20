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
  (console on `:9001`)

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
| `AWS_ENDPOINT_URL`, `AWS_ENDPOINT_URL_S3` | the RustFS URL | an *unconfigured* S3 client (`aws s3 cp`, any SDK) defaults here instead of AWS |
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
