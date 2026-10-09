# Data

This folder contains optional Caldova inputs and portable Search index snapshots imported from [ILL344](https://github.com/microsoft/aitour27-ILL344-turning-data-into-agent-ready-knowledge-with-microsoft-iq) at commit `dc74ce12fc9c4d1fc9c49fcd7b0c5cbf482cbcca`.

- `caldova/pdfs/`: 37 PDFs, selected by [corpora.json](caldova/corpora.json): 25 supplier-evidence documents, 11 sourcing documents, and one reserved file-source document.
- [provenance.json](caldova/provenance.json): the original Caldova data repository and revision.
- `index-data/`: index definitions and document/vector snapshots for `supplier-evidence` and `sourcing-documents`.

Provisioning restores the two index snapshots by default. It does not upload PDFs or run live ingestion; the first notebook uploads the reserved purchasing-policy PDF as a file knowledge source. See [infrastructure guidance](../infra/README.md#optional-data-tools) for restoration, live ingestion, and refresh workflows.

Fabric/OneLake JSON inputs and unrelated legacy datasets were not imported. The content is fictional sample data; review it before adapting it to this lab's scenario.
