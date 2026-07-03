"""Vymalo Mobile telemetry dashboard.

Faithful port of the former hand-written templates/dashboard-vymalo-mobile.yaml.
Targets the OTel export of the vymalo mobile app (service_name `vymalo-mobile`,
see vymalo-shop mobile/lib/app/otel.dart). uid stays `vymalo-mobile` so the
dashboard URL does not change.
"""

from __future__ import annotations

from grafana_foundation_sdk.builders import dashboard as dash
from grafana_foundation_sdk.models.dashboard import GridPos

import lib

# uid is load-bearing (stable URL) — do not change without intent.
UID = "vymalo-mobile"
CR_NAME = "vymalo-mobile-telemetry"

SERVICE = "vymalo-mobile"


def build() -> dash.Dashboard:
    log_severity = lib.timeseries_panel(
        "Log records by severity",
        lib.LOKI,
        lib.loki_query(
            f'sum by (severity_text) '
            f'(count_over_time({{service_name="{SERVICE}"}} [$__auto]))'
        ),
    ).grid_pos(GridPos(h=8, w=12, x=0, y=0))

    errors = lib.logs_view(
        "Errors & fatals",
        lib.LOKI,
        lib.loki_query(f'{{service_name="{SERVICE}"}} | severity_text =~ `ERROR|FATAL`'),
    ).grid_pos(GridPos(h=8, w=12, x=12, y=0))

    http_spans = lib.table_view(
        "HTTP client spans (sampled)",
        lib.TEMPO,
        lib.tempo_traceql(f'{{resource.service.name="{SERVICE}"}}', limit=50),
    ).grid_pos(GridPos(h=9, w=24, x=0, y=8))

    return (
        dash.Dashboard("Vymalo Mobile — Telemetry")
        .uid(UID)
        .refresh("1m")
        .time("now-24h", "now")
        .with_panel(log_severity)
        .with_panel(errors)
        .with_panel(http_spans)
    )
