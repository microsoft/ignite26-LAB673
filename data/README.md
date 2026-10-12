# Data

The active lab corpus is Cocoarynth, a fictional chocolate retailer. Documents were imported from [the developer KB lab](https://github.com/pamelas-organization/developer-kb-for-github-copilot) at commit `1cdf35934462a46752da542f0c856ac82b475075`.

- [Cocoarynth manifest](cocoarynth/corpora.json): four product/traceability PDFs and four engineering-practice PDFs, with the data-sharing policy also selected for the file-source exercise.
- [Cocoarynth provenance](cocoarynth/provenance.json): source repository, revision, ingestion references, and deliberate adaptations.
- `cocoarynth/documents/`: the eight original PDFs and their eight editable HTML sources. PDFs are the indexed inputs; HTML sources are retained for editing and provenance.
- `index-data/`: the destination for portable Cocoarynth index definitions and document/vector snapshots after the maintainer capture step.

No Cocoarynth snapshots have been captured yet. Follow [index preparation](../deploy_yourself.md#prepare-the-cocoarynth-indexes) to ingest the PDFs once and export real text/vector snapshots. Provisioning then restores the two Cocoarynth indexes by default, without running Content Understanding. The first notebook separately uploads the data-sharing policy as a file knowledge source.

The previous `caldova/` inputs and `supplier-evidence`/`sourcing-documents` snapshots are retained unchanged for reference. They are not used by the adapted notebook, ingestion, restoration, or export scripts. Review and remove them separately when finalizing the repository; they are not substitutes for Cocoarynth snapshots.
