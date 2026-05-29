# FEGA Metadata Schemas
<img src="./docs/images/logos/FEGA-logo-generic.svg"
     alt="Federated EGA logo"
     width="300"
     align="right" />

Machine-readable definitions of the **Federated European Genome-phenome Archive (FEGA)** metadata model, together with examples, validation utilities, and documentation.

The resources in this repository allow you to:

* **Validate** metadata against the EGA Metadata model locally.
* **Integrate** EGA-compatible metadata into your own pipelines.
* **Explore** the structure and semantics of the EGA metadata model.

> **Work is in progress**

> **Transparency disclaimer**: AI tools were used to assist in the writing and review of this repository. Ultimately, everything was reviewed by the (human) maintainer(s). Yes, everyone uses them. Yes, we do too. But at least we say so.

## Quick links

| What | Where |
|------|-------|
| **FEGA Metadata Technical report _(in preparation)_** | [`docs/technical-report.md`](./docs/technical-report.md) |
| **Background on the FEGA project** | [About FEGA](https://ega-archive.org/about/projects-and-funders/federated-ega/) |
| **FEGA onboarding guide** | [FEGA-Onboarding](https://ega-archive.github.io/FEGA-onboarding/) |
| **Metadata schemas** | [`schemas/`](./schemas/) |
| **Examples (test data)** | [`schemas/entities/*/examples/`](./schemas/entities/) |
| **JSON-LD frames** | [`schemas/entities/*/frame.jsonld`](./schemas/entities/) |
| **Further documentation** | [`docs/`](./docs/) |

## Code

### Validation

The Python validation scripts expect the repository helper package to be importable:

```bash
pip install -e .[dev]
```

They also expect an already-running [Biovalidator fork](https://github.com/M-casado/biovalidator/tree/dev) endpoint. From the repository root, start Biovalidator with the local schemas loaded:

```bash
npm install -g "github:M-casado/biovalidator#dev"
node "$(npm root -g)/biovalidator/src/biovalidator.js" \
  --port 3020 \
  --ref "./schemas/**/schema.json" \
  --ref "./standards/json-schema/**/*.json"
```

#### Complete Schema and Example Suite

Run **all** valid and invalid metadata JSON (e.g., [`cohort-valid-detailed-study-defined.json`](./schemas/entities/cohort/examples/valid/cohort-valid-detailed-study-defined.json)) examples under `schemas/entities`:

```bash
python scripts/py/validate_examples.py --root schemas/entities
```

Validate a single entity (e.g., all ``cohort`` examples):
```bash
python scripts/py/validate_examples.py --root schemas/entities --entity cohort
```

See more options:
```bash
python scripts/py/validate_examples.py --help
```

#### Validate One JSON Document

For one-off validation, wrap the JSON data and target schema in a document with top-level `data` and `schema` keys. For example, to validate a `cohort` (i.e., the data representing an EGA Cohort entity) against the `cohort` schema:

```json
{
  "schema": {
    "$ref": "https://raw.githubusercontent.com/M-casado/fega-metadata-schema/main/schemas/entities/cohort/schema.json"
  },
  "data": {
    "@context": "https://raw.githubusercontent.com/M-casado/fega-metadata-schema/main/schemas/entities/cohort/schema.json",
    "@type": "ega:cohort",
    "id": "ega:EGAC00001000001",
    "name": "Example rare disease cohort"
  }
}
```

Then validate that wrapper document (assuming you have a Biovalidator instance running):

```bash
python scripts/py/validate_metadata.py <path/to/document.json>
```

## Contributing

We welcome [issues](https://github.com/EGA-archive/fega-metadata-schema/issues/new/choose) and [pull requests](https://github.com/EbiEga/ega-metadata-schema/pulls). Please read [`CONTRIBUTING.md`](./CONTRIBUTING.md) to know more on how to provide your help to the project.

If you want to contribute in other ways to the group, please reach out to the lead(s) of the FEGA-MWG (see [AUTHORS.md](./AUTHORS.md))

## License

Original work in this repository is licensed under the terms of the license found in [`LICENSE`](./LICENSE). Third-party materials are licensed as stated in their respective directories (see [Third-party material](#third-party-material))

### Third-party material

- File(s) in [`standards/json-schema/json-ld.org/`](./standards/json-schema/json-ld.org/) incorporate work originally published by the World Wide Web Consortium (W3C) under the "W3C Software and Document Licence 2023". They remain available under that licence; see [`standards/json-schema/json-ld.org/LICENSE`](./standards/json-schema/json-ld.org/LICENSE) for details.

- File(s) in [``standards/json-schema/isa/``](./standards/json-schema/isa/) contain modified work from the ISA-API project: https://github.com/ISA-tools/isa-api. These files are licensed under CPAL-1.0; see [``standards/json-schema/isa/LICENSE``](./standards/json-schema/isa/LICENSE) for details.

- File(s) in [`./standards/json-schema/bioschemas/`](./standards/json-schema/bioschemas/) were adapted from BioSchemas definitions published via BioSchemas specification GitHub and the BioThings Data Discovery Engine. Except where otherwise noted on the source pages, the original content is licensed under the Creative Commons Attribution 4.0 International licence (CC BY 4.0); see [``./standards/json-schema/bioschemas/LICENSE``](./standards/json-schema/bioschemas/LICENSE) for details.

- File(s) in [`./standards/rdf/healthdcat-ap/`](./standards/rdf/healthdcat-ap/) were adapted from HealthDCAT-AP definitions published via _healthdataeu.pages.code.europa.eu_. Except where otherwise noted on the source pages, the original content is licensed under the Creative Commons Attribution 4.0 International licence (CC BY 4.0); see [``./standards/rdf/healthdcat-ap/LICENSE``](./standards/rdf/healthdcat-ap/LICENSE) for details.

## Contact
For general questions, or if you are unsure where to begin, follow the [_Need-help_](https://ega-archive.org/need-help/) form at our website.
