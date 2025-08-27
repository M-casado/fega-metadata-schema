# Changes to ISA-derived schemas

## 2025-08-27

Modified files (CPAL-covered):
- **``comment_schema.json``** — Removed ``additionalProperties``, changed ``$id``, added ``$comment``, removed ``name``, added ``@context``, added ``examples``.
- **``process_parameter_value_schema.json``** — Removed ``additionalProperties``, changed ``$id``, added ``$comment``, removed ``name``, replaced ``ontology_annotation_schema.json`` with ``FEGA.common-definitions.json#/$defs/ontologyTerm``, added ``@context``, added ``examples``.
- **``protocol_parameter_schema.json``** — Removed ``additionalProperties``, changed ``$id``, added ``$comment``, removed ``name``, replaced ``ontology_annotation_schema.json`` with ``FEGA.common-definitions.json#/$defs/ontologyTerm``, added ``@context``, added ``examples``.

Notes:
- These files are derived from ISA-API and remain under CPAL-1.0. See [``README.md``](./README.md) for attribution.
