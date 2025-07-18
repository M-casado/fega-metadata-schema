## Overview

The [`schemas/`](./) directory contains the **modular JSON Schema files** that collectively define the **Federated EGA (FEGA) metadata model**. Most JSON schema files in here correspond to a specific metadata **entity type** (e.g., [``FEGA.cohort.json``](./FEGA.cohort.json)) in the FEGA model. Others are common definitions (e.g., [``FEGA.common-definitions.json``](./FEGA.common-definitions.json)) and generic constraints (e.g., [``json-ld.org/``](./json-ld.org/)). By organizing the model into separate schema modules, we achieve a flexible, composable design where each entity (e.g. a *Biomaterial*) can be understood and validated independently. Furthermore, compound groupings like RDF Graphs, which may include flattened information from multiple entities, can be validated through [``FEGA.graph.json``](./FEGA.graph.json). This modular approach also reflects the real-world structure of submissions – for example, a study may involve multiple biomaterials, processes, and data files linked together.

Each JSON Schema is in draft form and subject to change. We follow **JSON Schema best practices**, including using the ``$defs`` section for internal reusable definitions and aligning with schema validation standards (e.g., types, formats). Furthermore, **direct references** to external standards (e.g., beacon-v2) exist within the schemas, asserting compatibility with the referenced properties. Wherever possible, fields are annotated with descriptions to help users understand the expected content.

### Modular Structure and References

The schemas are designed to **work together** to properly represent the FEGA metadata abstract model. The benefit of modular schemas is that **each entity type can evolve independently** to some extent. For instance, if we need to add a new field to the Biomaterial schema or refine the allowed values for Process types, we can do so without altering the others.

### Validation

For validating metadata instances against these schemas, we use the [**ELIXIR Biovalidator**](https://github.com/elixir-europe/biovalidator). Biovalidator is particularly useful as it can handle custom keywords integrating external APIs. For example, the keyword ``graphRestriction`` allows for us to perform ontology term validation. We include examples and test JSON files at [``data``](../data/) to help understand the metadata to be validated and to perform checks within the repository.

To see how **automatic validations** are performed in this repository, take a look at the [``json_validation_deploying_biovalidator.yml``](../.github/workflows/json_validation_deploying_biovalidator.yml) and its [history](https://github.com/M-casado/fega-metadata-schema/blob/main/.github/workflows/json_validation_deploying_biovalidator.yml) of triggers. In fact, if you are a maintainer, you can **quickly check the JSON Schema/data integrity** of a branch, tag or commit by **manually triggering validation**: simply click on ``Run workflow`` [here](https://github.com/M-casado/fega-metadata-schema/actions/workflows/json_validation_deploying_biovalidator.yml).

### RDF and JSON-LD

Importantly, every schema here is also a **JSON-LD context carrier**. At the top level of each schema, `@context` is provided (or referenced) so that any JSON conforming to the schema can be directly interpreted as JSON-LD. This means if you take a metadata JSON that validates against these schemas, you can add ` "@context": "<schema-URL>"` (if not already present) and turn it into RDF linked data with minimal effort. The contexts map our JSON terms (keys and certain values) to unique URIs (e.g., from ontologies). For example, a field `label` would not be a plain 'string', but instead be mapped to ``http://www.w3.org/2000/01/rdf-schema#label``, allowing RDF to recognize it as a standard concept. This strategy ensures that **FEGA metadata is not a silo** – it can be connected with other data representations (e.g., a catalog using DCAT, or a phenopacket, etc.) through shared vocabularies.

We maintain a dedicated **namespace** for FEGA identifiers (*#!* future `fega:` prefix via Identifiers.org) to use in the contexts. FEGA accessions (such as study IDs, dataset IDs, etc.) will be resolvable CURIEs. For instance, `fega:EGAD00010001911` would expand to ``https://ega-archive.org/datasets/EGAD00010001911``. This is still in progress (namespace registration and configuration), but reflects our commitment to **FAIR data principles**, especially **Interoperability** and **Reusability**, by making identifiers globally unambiguous and machine-resolvable.

### Current Status of Schemas

All schemas in this directory are **drafts under development**. They reflect the latest model structure agreed upon by the working group, but have not yet been implemented by one of the FEGA nodes. We expect to update these files frequently, so we advise users to **refer to specific tagged releases** (once available) for stable versions if they are integrating against the model.

Schema filenames and ``$id`` fields may also change to follow naming conventions once finalized. Additionally, certain fields marked with ``#!``, ``TBD`` or ``"$comment": ...`` indicate areas under discussion. We welcome contributions or suggestions for any of these elements.

Please note that until an official release (v1.0 of the model) is announced, **the schemas are not guaranteed to be backward compatible** from commit to commit. If you are experimenting with these drafts, be prepared for modifications. We will use versioning (via Git tags and version fields in the schemas) when we reach a more stable stage. For further details, please refer to the [**release documentation**](../docs/releases).

### Using and Contributing to the Schemas

If you wish to **use these schemas** for trial integration or testing, you can retrieve the ``.json`` files and load them into any JSON Schema–compliant validator. We recommend using the Biovalidator for validation, as our schemas take its custom keywords (e.g., ``graphRestriction``) into account for the validation logic (e.g., ``oneOf``, ``anyOf``, etc.).

 You can also experiment with the JSON-LD aspects by loading example instances (from [``jsonld/``](../data/jsonld/)) into a [JSON-LD Playground](https://json-ld.org/playground/) or an RDF library – the provided contexts (``@context``) in the JSON Schemas should allow you to see the metadata as an RDF graph.

To **contribute** to the repository please refer to the [contributing documentation](../docs/contributing.md). Schema development follows the guidance of the FEGA Metadata Working Group, but we greatly value external contributions and domain-specific insights.

### Alignment with Current Model Terminology

Please note that the schemas here use the **updated terminology** of the new FEGA model. In legacy EGA documentation or older schema drafts, you might see terms like "Experiment" or "Analysis" to describe processes, or "Sample" for biomaterials, etc. We have **aligned the language** to the current model. Please refer to each entities' respective file for further details.