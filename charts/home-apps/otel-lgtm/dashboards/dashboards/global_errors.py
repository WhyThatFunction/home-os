"""Global error-zone dashboard — cross-cutting error view across ALL services.

The owner's "zones to capture global error cases": error-log rate by service,
the latest ERROR/FATAL lines across the whole estate, errored spans by service,
and a total-errors stat for the window. A `service` multi-select (Loki label
values) lets you narrow without overfitting to one app.
"""

from __future__ import annotations

from grafana_foundation_sdk.builders import dashboard as dash
from grafana_foundation_sdk.models.dashboard import GridPos

import lib

UID = "global-errors"
CR_NAME = "global-errors"

# A `$service` multi-select driven by Loki's service_name label values. "All"
# resolves to `.+` (see lib.service_query_variable) so the =~ selector spans
# every service without an empty-compatible matcher Loki would reject.
SERVICE_MATCHER = 'service_name =~ "$service"'
ERROR_SEVERITY = "severity_text =~ `ERROR|FATAL`"


def build() -> dash.Dashboard:
    total_errors = lib.stat_view(
        "Total ERROR/FATAL logs (window)",
        lib.LOKI,
        lib.loki_query(
            f"sum(count_over_time({{{SERVICE_MATCHER}}} | {ERROR_SEVERITY} "
            f"[$__range]))"
        ),
        unit="short",
        calc="lastNotNull",
    ).grid_pos(GridPos(h=6, w=6, x=0, y=0))

    services_with_errors = lib.stat_view(
        "Services emitting errors",
        lib.LOKI,
        lib.loki_query(
            f"count(sum by (service_name) "
            f"(count_over_time({{{SERVICE_MATCHER}}} | {ERROR_SEVERITY} [$__range])))"
        ),
        unit="short",
        calc="lastNotNull",
    ).grid_pos(GridPos(h=6, w=6, x=6, y=0))

    error_rate_by_service = lib.timeseries_panel(
        "Error-log rate by service",
        lib.LOKI,
        lib.loki_query(
            f"sum by (service_name) "
            f"(count_over_time({{{SERVICE_MATCHER}}} | {ERROR_SEVERITY} [$__auto]))"
        ),
    ).grid_pos(GridPos(h=8, w=12, x=12, y=0))

    latest_errors = lib.logs_view(
        "Latest ERROR/FATAL across all services",
        lib.LOKI,
        lib.loki_query(f"{{{SERVICE_MATCHER}}} | {ERROR_SEVERITY}"),
    ).grid_pos(GridPos(h=10, w=12, x=0, y=6))

    errored_spans = lib.table_view(
        "Errored spans by service",
        lib.TEMPO,
        # TraceQL: spans in an error status, grouped by service in the results.
        lib.tempo_traceql(
            "{ status = error } | by(resource.service.name)", limit=100
        ),
    ).grid_pos(GridPos(h=10, w=12, x=12, y=8))

    return (
        dash.Dashboard("Global — Error Zones")
        .uid(UID)
        .refresh("1m")
        .time("now-6h", "now")
        .tags(["errors", "global", "sre"])
        .with_variable(lib.service_query_variable())
        .with_panel(total_errors)
        .with_panel(services_with_errors)
        .with_panel(error_rate_by_service)
        .with_panel(latest_errors)
        .with_panel(errored_spans)
    )
