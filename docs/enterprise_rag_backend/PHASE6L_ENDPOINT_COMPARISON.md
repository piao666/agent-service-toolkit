# Phase 6L Endpoint Comparison Notes

## Phase 6L-2 baseline

The initial 24-case artifact recorded successful HTTP/schema behavior and zero request errors or
timeouts. It also recorded `graph_debug_present_count=0` for the custom label. These values do not
prove a retrieval-quality difference: the runner sent both labels to the same service URL while
`ENTERPRISE_AGENT_GRAPH_MODE` can only change when the service process starts.

The Phase 6L-2 files remain unchanged as historical baseline artifacts.

## Phase 6L-3 correction

The runner now accepts two explicit endpoints:

```text
--legacy-url http://127.0.0.1:8000/enterprise/agent/query
--custom-graph-url http://127.0.0.1:8001/enterprise/agent/query
```

The corresponding services must be started separately with:

```text
ENTERPRISE_AGENT_GRAPH_MODE=legacy
ENTERPRISE_AGENT_GRAPH_MODE=custom_graph
```

For custom responses, successful debug surfacing requires all of the following:

- top-level `graph_debug` is a non-empty object;
- `graph_debug.graph_mode` equals `custom_graph`;
- `graph_debug.nodes_executed` is a non-empty list.

Missing custom debug is included in bad-case computation. Empty legacy debug remains valid.

## Next validation

Phase 6L-4 may rerun the comparison against two correctly configured service processes. This phase
does not run that comparison, a 240-case evaluation, an HPC workload, or a real LLM.
