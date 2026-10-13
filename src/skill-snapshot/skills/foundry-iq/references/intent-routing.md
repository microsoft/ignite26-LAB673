# Other Intent Routes

Use for troubleshooting or tasks outside the [router's](../SKILL.md) Hero routes.
Failures take precedence over setup. Read only the selected guide; ask when
the intent is unclear.

| Intent | Load |
|---|---|
| Failure | Matching `troubleshooting/`, then original operation |
| REST operation | [catalog](operation-catalog.yaml) -> leaf |
| Service setup | [service](service-provisioning.md) |
| File -> KB | [File](knowledge-sources/file.md) |
| Blob/ADLS -> KB | [Blob](knowledge-sources/azure-blob.md) |
| Other KS -> KB | [types](../operations/data-plane/knowledge-sources/create.md) |
| Connect Foundry agent | Unsupported; explain and hand off |

KS -> KB: verify readiness, then [KB](../operations/data-plane/knowledge-bases/create-or-update.md) and [retrieve](../operations/data-plane/knowledge-retrieval/retrieve.md).

Apply the router's shared API, authentication, safety and output contracts to
every route. This reference grants no additional approval or resource scope.