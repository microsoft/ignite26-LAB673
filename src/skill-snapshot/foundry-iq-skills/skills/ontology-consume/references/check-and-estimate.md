# Check and estimate

## Quick starts

- "Is `wiki.owl` valid against the flat-owl profile?"
- "Why does this OWL file fail validation?"
- "How much would a proposal cost under a two-dollar cap?"

## Use this path

Use this path to validate an OWL file, or hand off a pricing request without writing state.

## Check a file

`ontology-consume check <file>` validates an RDF/XML file against the flat-owl profile and prints its SHA-256. It reports every violation in document order by rule code:

- `doctype`, `not_well_formed`: no DOCTYPE or ENTITY, well-formed XML with an `rdf:RDF` root. Nothing else is reported.
- `ontology_count`, `imports`: exactly one `owl:Ontology`, and no `owl:imports`.
- `unsupported_element`: only `owl:Ontology`, `owl:Class`, `owl:ObjectProperty`, and `owl:DatatypeProperty`, with only label, subclass, domain, range, and comment children.
- `invalid_name`, `duplicate_name`: names match `^[A-Za-z][A-Za-z0-9_]*$`, avoid reserved words, and are unique case-insensitively.
- `domain_count`, `range_count`, `dangling_domain`, `dangling_range`, `datatype_range`, `dangling_parent`: one domain and one range per property, all pointing at declared classes; datatype ranges are `xsd:string`, `xsd:double`, `xsd:boolean`, or `xsd:dateTime`.
- `label_order`, `not_canonical`: one label first and one comment last, and bytes equal the canonical re-serialization.

Fixing a file is out of scope here. Offer to import it into ontology-build as a new version.

## Estimate

There is no read-only estimate verb in `ontology-consume`. Hand off to `ontology-build` with the
same absolute `--state-dir` and requested budget; do not execute its plan under this read-only skill.
The build skill's `plan --model-max-spend-usd <cap>` samples the connected corpus and **persists**
a priced plan. It calls no model, but running propose/refine/critique still requires approval of
the exact card. Never label persisted planning a nonpersisting preview.

## Return

Report pass or the first violations with their rule codes, the SHA-256, and one safe next action.
