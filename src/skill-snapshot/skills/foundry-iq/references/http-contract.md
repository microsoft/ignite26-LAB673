# HTTP contract

Use HTTPS, the exact `api-version` resolved for the request's plane by the [API version policy](api-version-policy.md), `Authorization: Bearer`, `Content-Type: application/json`, and a generated client request ID. Preserve service request IDs. Follow continuation URLs without reconstructing them. Honor `Retry-After`, bound retries to 408/429/5xx and idempotent operations, and never retry unsafe writes without an idempotency or state check.

## User-agent attribution

Add `foundry-iq-skill-v{skillVersion}` to `User-Agent` for skill-executed Search management and data-plane requests, including standalone operations, hero scenarios, troubleshooting, retries, polling, and pagination. Resolve `skillVersion` from `metadata.version` in the [loaded skill](../SKILL.md), stamped by upstream packaging.

Preserve the client's identity and append the token once, scoped to these requests. Respect user or organization telemetry restrictions; never include private data or secrets.

| Interface | How to apply the token |
|---|---|
| Azure CLI `az rest` | Add `"User-Agent=$skillUserAgent"` to existing `--headers`; CLI retains its identity. Do not also set the token through `AZURE_HTTP_USER_AGENT`. |
| SDK | Use a supported application-ID or user-agent extension; retain `azsdk-*`. |
| Direct HTTP, including file upload | Append to the client's existing `User-Agent`; preserve other headers. |
| MCP or another managed client | Use a documented attribution option. If unavailable, report it; do not invent arguments or switch clients solely for telemetry. |

After resolving `$skillVersion` and `$dataApiVersion`:

```powershell
$skillUserAgent = "foundry-iq-skill-v$skillVersion"
az rest --method get --url "https://<search-service>.search.windows.net/indexes?api-version=$dataApiVersion" --headers "User-Agent=$skillUserAgent"
```

Do not tag generated customer application code. Exclude the live-validation token `foundry-iq-skill-live-v1` from skill-usage counts, even when other inherited tags are present.

References: [SDK telemetry](https://azure.github.io/azure-sdk/general_azurecore.html#telemetry-policy), [Azure CLI REST](https://github.com/Azure/azure-cli/blob/dev/src/azure-cli-core/azure/cli/core/util.py).
