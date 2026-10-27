# Errors and acceptance limits

Missing runtime payload, Python, verified bootstrap setup or a supported MCP
version prevents readiness. Inspect bootstrap `status` and complete `setup`
with configured pip sources; do not point the host at an old console executable or
remove negotiation/sandbox checks. Domain failures and disconnected servers are
visible, not empty successful graphs. A cancelled server needs explicit reconnect.

`PROTOCOL_UNSUPPORTED` identifies an explicit incompatible version reply.
`NEGOTIATION_FAILED` means discovery did not establish protocol support: check
bootstrap setup and server startup/dependency failures, not just SDK versions.
The pinned protocol and no-fallback policy are unchanged. Startup log diagnostic
counts cover the primary transport only; the SDK's disposable negotiation probe
may fail before its private stderr is available there. Zero retained bytes is not
proof that the failed server emitted no diagnostics. Mapped errors retain their
original cause and any captured diagnostic tail privately, not in browser output.

Source/protocol fixtures and real-browser host regressions are separate evidence
from installed-plugin and genuine-data acceptance. Actual Python MCP 2.3.0
metadata-only sessions verified all three servers, all supporting tools and six
current HTML resources without tool/model/Azure calls. Those checks do not prove
a new live data journey or stock product-host compatibility. Historical direct-CLI
ZIP/live receipts do not certify this new distribution.

The first external-host candidate is stock Claude Desktop: its primary Apps guide
documents local stdio configuration. Installation, version/account/policy, actual
rendering and agent consumption remain separately scoped acceptance work. No
patched product host or model-backed standalone conversation is part of this host.

[Prerequisites and setup](standalone-setup.md) | [Launch](standalone-launch.md)
