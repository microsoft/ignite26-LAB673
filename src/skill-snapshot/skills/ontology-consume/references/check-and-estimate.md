# Check and estimate

## Quick starts

- "Is `wiki.owl` valid against the flat-owl profile?"
- "Why does this OWL file fail validation?"
- "How much would a proposal cost under a two-dollar cap?"

## Use this path

Use this path to validate any OWL file or to price a proposal without saving a plan.

## Check a file

`ontology-skills-ontology_check` or `ontology-consume check <file>` validates an RDF/XML file against the flat-owl profile and prints its SHA-256. It reports every violation in document order by rule code:

- `doctype`, `not_well_formed`: no DOCTYPE or ENTITY, well-formed XML with an `rdf:RDF` root. Nothing else is reported.
- `ontology_count`, `imports`: exactly one `owl:Ontology`, and no `owl:imports`.
- `unsupported_element`: only `owl:Ontology`, `owl:Class`, `owl:ObjectProperty`, and `owl:DatatypeProperty`, with only label, subclass, domain, range, and comment children.
- `invalid_name`, `duplicate_name`: names match `^[A-Za-z][A-Za-z0-9_]*$`, avoid reserved words, and are unique case-insensitively.
- `domain_count`, `range_count`, `dangling_domain`, `dangling_range`, `datatype_range`, `dangling_parent`: one domain and one range per property, all pointing at declared classes; datatype ranges are `xsd:string`, `xsd:double`, `xsd:boolean`, or `xsd:dateTime`.
- `label_order`, `not_canonical`: one label first and one comment last, and bytes equal the canonical re-serialization.

Fixing a file is out of scope here. Offer to import it into ontology-build as a new version.

## Estimate

`ontology-skills-ontology_plan_estimate` prices a proposal and never saves a plan or calls a model. Saving a plan, approving, and running belong to ontology-build.

## Return

Report pass or the first violations with their rule codes, the SHA-256, and one safe next action.
