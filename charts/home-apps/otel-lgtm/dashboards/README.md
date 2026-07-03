# Grafana dashboards-as-code

**House rule: never hand-write a Grafana dashboard JSON.** Every dashboard for
the otel-lgtm Grafana is generated from a typed Python module here, using the
official [`grafana-foundation-sdk`](https://github.com/grafana/grafana-foundation-sdk).
The generator wraps each dashboard in a `GrafanaDashboard` CR that the Grafana
Operator reconciles into the external Grafana (see
[`../templates/grafana-instance.yaml`](../templates/grafana-instance.yaml)).

## Layout

```
dashboards/
├── lib.py                 # shared: datasource refs, panel/query factories, CR wrapper
├── generate.py            # entrypoint: renders every registered dashboard to a CR
├── requirements.txt       # pinned deps (SDK + PyYAML)
├── dashboards/            # one module per dashboard
│   ├── vymalo_mobile.py   # uid vymalo-mobile  (ported from the old hand-written CR)
│   └── global_errors.py   # uid global-errors  (cross-service error zones)
└── README.md              # this file
```

Generated CRs land in [`../templates/generated/`](../templates/generated/) and are
picked up by Helm/Argo automatically. They are marked `# GENERATED — do not edit
by hand` — edit the `.py` and regenerate.

## Regenerate

```sh
# from the repo root
make dashboards

# or directly (from this dir)
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python generate.py
```

`.venv/` is local-only; do not commit it. Commit only the `.py` sources and the
regenerated CRs under `../templates/generated/`.

## Add a new dashboard

1. **Create a module** `dashboards/<name>.py` exposing three names:
   - `UID` — the stable Grafana uid (keeps the dashboard URL fixed across regen).
   - `CR_NAME` — the `metadata.name` of the `GrafanaDashboard` CR.
   - `build() -> grafana_foundation_sdk.builders.dashboard.Dashboard`.

   Use the helpers in `lib.py` so you never touch raw panel JSON:

   ```python
   from grafana_foundation_sdk.builders import dashboard as dash
   from grafana_foundation_sdk.models.dashboard import GridPos
   import lib

   UID = "my-service"
   CR_NAME = "my-service-overview"

   def build() -> dash.Dashboard:
       panel = lib.timeseries_panel(
           "Requests/s", lib.PROMETHEUS,
           # ... a prometheus/loki/tempo target ...
       ).grid_pos(GridPos(h=8, w=12, x=0, y=0))
       return dash.Dashboard("My Service — Overview").uid(UID).with_panel(panel)
   ```

2. **Register it** in `generate.py`'s `DASHBOARDS` dict:
   `"my_service": "dashboard-my-service"` (module name → output filename stem).

3. **Regenerate** (`make dashboards`) and commit the `.py` + the new CR YAML.

### Available helpers (`lib.py`)

- Datasource refs (uids the otel-lgtm image provisions): `lib.PROMETHEUS`,
  `lib.LOKI`, `lib.TEMPO`, `lib.PYROSCOPE`.
- Query factories: `lib.loki_query(expr)`, `lib.tempo_traceql(query, limit=…)`.
  (Prometheus targets: use the SDK's `prometheus.Dataquery().expr(...)` directly.)
- Panel factories: `lib.timeseries_panel`, `lib.logs_view`, `lib.table_view`,
  `lib.stat_view` — each takes `(title, datasource, *targets)` and returns an SDK
  panel builder you finish with `.grid_pos(...)` and any extra SDK setters.
- `lib.wrap_cr(...)` / `lib.dashboard_to_dict(...)` — used by `generate.py`; you
  won't normally call these directly.

## Datasources (Postgres + Redis)

Two `GrafanaDatasource` CRs live in `../templates/` (they're not dashboards, so
they're hand-authored, not generated):

- **`../templates/datasource-postgres.yaml`** — Postgres (primary), wired as a
  concrete example to the vymalo backend CNPG DB. **Review before applying:** it
  references the live `vymalo-backend-cnpg-app` secret; the operator reads
  `valuesFrom` secrets from the CR's own namespace, so you must either mirror the
  secret into the otel-lgtm namespace or move the CR into `vymalo`. See the
  header comment in the file.
- **`../templates/datasource-redis.yaml`** — Redis (next up). **Requires the
  `redis-datasource` plugin**, which is NOT in the otel-lgtm image. Install it via
  `GF_INSTALL_PLUGINS=redis-datasource` on the lgtm container (values.yaml) and
  restart the pod before applying. URL/auth are TODO placeholders — fill in with
  the owner.

Both are `instanceSelector`-matched to the same otel-lgtm Grafana and use the
operator's INLINE secret-ref shape (`{name, key}`, matching
`grafana-instance.yaml`).
