# FEGA Metadata Schemas
<img src="./docs/images/logos/FEGA-logo-generic.svg"
     alt="Federated EGA logo"
     width="300"
     align="right" />

Machine-readable definitions of the **Federated European Genome-phenome Archive (FEGA)** metadata model, together with examples, JSON-LD resources, validation utilities, and documentation.

The resources in this repository help you to:

* **Validate** metadata against the EGA Metadata model locally.
* **Integrate** EGA-compatible metadata into your own pipelines.
* **Explore** the structure, relationships, and linked-data semantics of the EGA metadata model.

> **Work is in progress**

> **Transparency disclaimer**: AI tools were used to assist in the writing and review of this repository. Ultimately, everything was reviewed by the (human) maintainer(s). Yes, everyone uses them. Yes, we do too. But at least we say so.

## Quick links

| What | Where |
|------|-------|
| **FEGA Metadata Technical Report** | [`docs/FEGA-metadata-technical-report.md`](./docs/FEGA-metadata-technical-report.md) |
| **Schema release process** | [`docs/releases/README.md`](./docs/releases/README.md) |
| **Background on the FEGA project** | [About FEGA](https://ega-archive.org/about/projects-and-funders/federated-ega/) |
| **FEGA onboarding guide** | [FEGA-Onboarding](https://ega-archive.github.io/FEGA-onboarding/) |
| **Metadata schemas** | [`schemas/`](./schemas/) |
| **Entity schemas** | [`schemas/entities/`](./schemas/entities/) |
| **Examples** | [`schemas/entities/*/examples/`](./schemas/entities/) |
| **JSON-LD contexts and frames** | [`schemas/entities/*/context.jsonld`](./schemas/entities/) and [`schemas/entities/*/frame.jsonld`](./schemas/entities/) |
| **Third-party standards** | [`standards/`](./standards/) |

## Overview of repository structure

Shared schema definitions live in [`schemas/common/`](./schemas/common/). Third-party JSON Schema and RDF/SHACL resources are kept under [`standards/`](./standards/) with their own licensing notes.

Each EGA entity schema ([`schemas/entities/`](./schemas/entities/)) is paired with local examples, a JSON-LD context, and a JSON-LD frame. The validation scripts ([`scripts/`](./scripts/)) use those files together to check JSON Schema validity, JSON-LD parsing, context/frame coverage, RDF reconstruction, and SHACL compatibility where applicable.

## Setup

The Python validation scripts expect the repository helper package and dependencies to be installed:

```bash
# Optional if you don't want to affect root
python -m venv .venv
source .venv/bin/activate
# Install dependencies
pip install -r requirements.txt
pip install -e .[dev]
```

Some validation commands also expect an already-running [Biovalidator fork](https://github.com/M-casado/biovalidator/tree/main) endpoint. From the repository root, start Biovalidator with the local schemas loaded:

```bash
# Optionally, uninstall any previous global Biovalidator installation
# npm uninstall -g biovalidator
npm install -g "github:M-casado/biovalidator#main"
node "$(npm root -g)/biovalidator/src/biovalidator.js" \
  --port 3020 \
  --ref "./schemas/**/schema.json" \
  --ref "./standards/json-schema/**/*.json"
```

## Validation

### Complete Schema and Example Suite

Run **all** valid and invalid metadata JSON (e.g., [`cohort-valid-detailed-study-defined.json`](./schemas/entities/cohort/examples/valid/cohort-valid-detailed-study-defined.json)) examples under `schemas/entities`:

```bash
python scripts/py/validate_examples.py -v
```

The script exits with code `0` if all suites pass and `1` otherwise. No output is printed to stdout by default; add `--print-summary` to get the full JSON report:

```bash
python scripts/py/validate_examples.py --root schemas/entities --print-summary
```

To save the report to a file instead of (or in addition to) printing it, use `--summary-dir`:

```bash
python scripts/py/validate_examples.py --root schemas/entities --summary-dir .
```

Validate a single entity (e.g., all ``cohort`` examples):
```bash
python scripts/py/validate_examples.py --root schemas/entities --entity cohort
```

See more options:
```bash
python scripts/py/validate_examples.py --help
```

### JSON-LD Context Smoke Tests

Check that every valid example can be parsed into RDF (with `rdflib`) and that required JSON-LD fields (`data.@context`, `data.@type`, `schema.$ref`) are present. This step resolves all context references from local files (i.e., we are not fetching from the remote, which is what normal RDF parsing would do) and does **not** require Biovalidator.

```bash
python scripts/py/validate_jsonld_contexts.py -v
```

See more options:
```bash
python scripts/py/validate_jsonld_contexts.py --help
```

A passing test confirms that (1) the **local context chain** (i.e., a JSON doc referencing the JSON Schema, which references the JSON-LD context) is self-consistent, that (2) at least **one type statement** (e.g., ``"@type": "ega:cohort"``) **expands** to an RDF triple (e.g., ``ega:EGAH00000000001 --> rdf:type --> ega:cohort``), and that (3) the document can be parsed into a **non-empty RDF graph**, entirely from local files. 

It does **not** verify that every term in the document is defined in the context (undefined terms are silently ignored by JSON-LD), nor that the expanded URIs are dereferenceable or semantically correct.

### JSON-LD Context and Frame Coverage

Check that every direct property declared in each entity's `schema.json` is covered by its materialized JSON-LD context (`context.jsonld`) and its frame (`frame.jsonld`). The goal is to catch schema terms that would otherwise be ignored during JSON-LD parsing or framing (i.e., added to the schemas but not to the contexts and frames).

```bash
python scripts/py/validate_jsonld_coverage.py -v
```

See more options:
```bash
python scripts/py/validate_jsonld_coverage.py --help
```

### JSON-LD Frame Validation

Confirm that every valid example can be reconstructed from both flattened JSON-LD and a generated RDF graph into schema-shaped JSON-LD, without semantic RDF loss, and then pass Biovalidator.

This requires a running Biovalidator instance and a `frame.jsonld` file inside each entity directory. Missing frames fail the suite.

```bash
python scripts/py/validate_jsonld_frames.py -v
```

Use single-file debug mode to print complete snapshots after each transformation stage to stdout. This helps figuring out how the transformations work during the tests. Normal log records remain on stderr:

```bash
python scripts/py/validate_jsonld_frames.py \
  --file schemas/entities/cohort/examples/valid/cohort-valid-minimal-study-defined.json \
  -vv
```

See more options:
```bash
python scripts/py/validate_jsonld_frames.py --help
```

### RDF/SHACL Example Suite

Validate wrapped JSON-LD examples against RDF/SHACL shapes. This does not require Biovalidator.

The test scope (i.e., which entities we are validating in each run) is explicit, since for now we only have the HealthDCAT-AP SHACL shapes that apply to Datasets only. For example:

```bash
python scripts/py/validate_rdf_shacl.py \
  --entity dataset \
  --shapes standards/rdf/healthdcat-ap/release-6.0.0/shacl/non-public-shapes-v6.ttl \
  -v
```

See more options:
```bash
python scripts/py/validate_rdf_shacl.py --help
```

### Validate One JSON Document

For one-off validation, wrap the JSON data and target schema in a document with top-level `data` and `schema` keys. For example, to validate a `cohort` (i.e., the data representing an EGA Cohort entity) against the `cohort` schema:

```json
{
  "schema": {
    "$ref": "https://raw.githubusercontent.com/M-casado/fega-metadata-schema/main/schemas/entities/cohort/schema.json"
  },
  "data": {
    "@context": "https://raw.githubusercontent.com/M-casado/fega-metadata-schema/main/schemas/entities/cohort/context.jsonld",
    "@type": "ega:cohort",
    "id": "ega:EGAC00001000001",
    "name": "Example rare disease cohort"
  }
}
```

Then validate that wrapper document with a running Biovalidator instance:

```bash
python scripts/py/validate_metadata.py <path/to/document.json>
```

## Contributing

We welcome [issues](https://github.com/M-casado/fega-metadata-schema/issues/new/choose) and [pull requests](https://github.com/M-casado/fega-metadata-schema/pulls). Please read [`CONTRIBUTING.md`](./CONTRIBUTING.md) before contributing.

If you want to contribute in other ways to the group, please reach out to the FEGA Metadata Working Group leads listed in [`AUTHORS.md`](./AUTHORS.md).

## License

Original work in this repository is licensed under the terms of the license found in [`LICENSE`](./LICENSE). Third-party materials are licensed as stated in their respective directories.

### Third-party Material

- Files in [`standards/json-schema/json-ld.org/`](./standards/json-schema/json-ld.org/) incorporate work originally published by the World Wide Web Consortium (W3C) under the W3C Software and Document Licence 2023. They remain available under that licence; see [`standards/json-schema/json-ld.org/LICENSE`](./standards/json-schema/json-ld.org/LICENSE) for details.

- Files in [`standards/json-schema/isa/`](./standards/json-schema/isa/) contain modified work from the ISA-API project: https://github.com/ISA-tools/isa-api. These files are licensed under CPAL-1.0; see [`standards/json-schema/isa/LICENSE`](./standards/json-schema/isa/LICENSE) for details.

- Files in [`standards/json-schema/bioschemas/`](./standards/json-schema/bioschemas/) were adapted from BioSchemas definitions published via BioSchemas specification GitHub and the BioThings Data Discovery Engine. Except where otherwise noted on the source pages, the original content is licensed under the Creative Commons Attribution 4.0 International licence (CC BY 4.0); see [`standards/json-schema/bioschemas/LICENSE`](./standards/json-schema/bioschemas/LICENSE) for details.

- Files in [`standards/json-schema/beacon-v2/`](./standards/json-schema/beacon-v2/) vendor Beacon v2 JSON Schemas from the Beacon v2 project snapshot used for FEGA validation. These files are licensed under the Creative Commons Zero v1.0 Universal licence (CC0 1.0); see [`standards/json-schema/beacon-v2/LICENSE`](./standards/json-schema/beacon-v2/LICENSE) for details.

- Files in [`standards/rdf/healthdcat-ap/`](./standards/rdf/healthdcat-ap/) were adapted from HealthDCAT-AP definitions published via _healthdataeu.pages.code.europa.eu_. Except where otherwise noted on the source pages, the original content is licensed under the Creative Commons Attribution 4.0 International licence (CC BY 4.0); see [`standards/rdf/healthdcat-ap/LICENSE`](./standards/rdf/healthdcat-ap/LICENSE) for details.

## Contact
For general questions, or if you are unsure where to begin, follow the [_Need-help_](https://ega-archive.org/need-help/) form at the EGA website.
