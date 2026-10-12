# Carefold Connectors Framework

Core protocol, declarative manifest models, and sandboxed egress HTTP client for Carefold clinical data and EHR connectors.

## Overview
`carefold-connectors` provides:
- `@runtime_checkable class Connector(Protocol)`: Core interface for external data sources and EHR systems.
- `ConnectorManifest`: Pydantic model for validating `connector.yaml` definitions.
- `ScopedHttp`: Security-hardened HTTP client enforcing manifest `data_flows.allowed_hosts` and blocking anti-SSRF targets (cloud metadata and link-local addresses).
- Interoperable data structures: `ToolContext`, `StreamSpec`, `Page`, `NormalisedRecord`, and `ToolSpec`.

## Installation
```bash
pip install -e libs/connectors
```

## Security Invariants
- Egress strictly confined to `data_flows.allowed_hosts`.
- Link-local and cloud metadata addresses (`169.254.169.254`, `169.254.170.2`) are unconditionally blocked.
- Non-HTTP/HTTPS schemes (such as `file://`, `ftp://`, `gopher://`) are strictly rejected.
