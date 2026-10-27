# Create Or Update Remote SharePoint Knowledge Sources

## Quick reference

- **Kind:** `remoteSharePoint` (preview; stateless passthrough, no index/indexer).
- **Operations:** [create](../../operations/data-plane/knowledge-sources/create.md) or [create/update](../../operations/data-plane/knowledge-sources/create-or-update.md).
- **`dataApiVersion`:** `2026-08-01-preview`. [Policy](../api-version-policy.md):
  verify source/KB/retrieve compatibility and honor explicit pins/GA-only constraints.
  Documented version selection needs no separate permission.

## When to use / Do not use

Use for live text retrieval with native query-time permissions. Choose
`indexedSharePoint` for multimodal/retrieval-control needs or unmet Remote
prerequisites; its ingestion-time ACL model is not interchangeable.

## Inputs and context discovery

Verify agentic regional support and the **same Entra tenant** for Azure/M365.
For **each querying user**, verify a Copilot add-on or enabled Retrieval API
pay-as-you-go (preview). Paygo needs M365 admin, Azure Owner/Contributor,
resource group and a tenant Copilot license throughout use. Never enable it
implicitly or borrow another user's entitlement; missing eligibility blocks queries.

## Preconditions and authentication

Search-audience Entra; KS creation needs **Search Service Contributor**,
not pipeline/model roles. KB/model/query permissions are verified separately.

## Safety or approval gate

Disclose preview status and the per-user licensing/paygo prerequisite before
creating. No ingestion costs, but paygo consumption bills the tenant.

## Request contract

```json
{
  "name": "<source-name>",
  "kind": "remoteSharePoint",
  "remoteSharePointParameters": {
    "filterExpression": "Path:\"https://tenant.sharepoint.com/sites/approved-site\"",
    "containerTypeId": null,
    "resourceMetadata": null
  }
}
```

`filterExpression` uses KQL (`SiteID`, `Path`, `LastModifiedTime`,
`FileExtension`, `InformationProtectionLabelId`). An invalid filter is **silently
ignored**, not rejected. Substitute the approved site; test syntax and both
an in-scope hit and an entitled out-of-scope exclusion. A permission denial
alone does not validate scope. Unverified filtering blocks restricted use. Use
`If-None-Match: *` for creation; use the current ETag with `If-Match` for an
approved update.

## Execution and validation

No generated resources/sync. PUT makes a source queryable, not content verified.
Use the selected [KB/retrieve recipe](../knowledge-base-retrieval.md).
Verify each test user's token in
`x-ms-query-source-authorization`; permissions enforce per request, not
ingestion. Hybrid retrieval supports `.doc/.docx/.pptx/.pdf/.aspx/.one`;
other supported extensions, including `.txt`, use **lexical retrieval**, not a
format blocker. Results are unordered/capped at 25; no multimodal content.
Respect 200 requests/user/hour, a
1,500-character query limit, and 1 concurrent query/replica (dedicated) or 1
total (serverless) across **all** remote SharePoint sources on the service.

## Rollback or recovery

Use ETags for restoration. Teardown deletes the KS itself; there are no
generated indexer/index objects. Follow
[scenario cleanup](../safety-and-idempotency.md#scenario-cleanup) for any owned
KB that referenced it.

## Error and output contract

Return kind, filter expression, version/source, correlation ID,
and validation. Redact credentials/private content. Results include
`resourceMetadata`/`webUrl`/`searchSensitivityLabelInfo`; do not fabricate a
download URL from these.

## Official references

- [Remote SharePoint knowledge sources](https://learn.microsoft.com/azure/search/agentic-knowledge-source-how-to-sharepoint-remote)
- [Retrieval API format limits](https://learn.microsoft.com/microsoft-365/copilot/extensibility/api/ai-services/retrieval/overview#known-limitations)
- [Retrieval API pay-as-you-go](https://learn.microsoft.com/microsoft-365-copilot/extensibility/api/overview-retrieval-pay-as-you-go)
