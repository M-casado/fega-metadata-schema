# HealthDCAT-AP JSON Schema layer

This directory contains JSON Schema files that are derived from HealthDCAT-AP Release 6 artefacts (including SHACL shapes and specification constraints) and curated for use in this repository.

These JSON Schemas are intended to help validate JSON metadata that aims to be compatible with HealthDCAT-AP concepts and constraints. They are **not an official publication of the European Commission and they do not replace the authoritative specification**.

## Upstream source

- **Specification**: HealthDCAT-AP Release 6
- **Copyright** © 2025 European Union
- **Upstream page**: https://healthdataeu.pages.code.europa.eu/healthdcat-ap/releases/release-6/

## How these files were produced

1. Started from upstream [SHACL shapes](https://healthdataeu.pages.code.europa.eu/healthdcat-ap/releases/release-6/#validation-of-healthdcat-ap) (e.g., [``non-public-shapes.ttl``](https://healthdataeu.pages.code.europa.eu/healthdcat-ap/releases/release-6/html/shacl/non-public-shapes.ttl)).
2. Converted SHACL to an initial JSON Schema representation via [SHACL-Play](https://shacl-play.sparna.fr/play/jsonschema).
3. Manually curate the output to add missing details, constraints and properties, and to fit the overall FEGA JSON Schema repository.

All deviations from upstream are intentional adaptations for JSON Schema validation and are tracked in this repository's version control history.

## Licence

The contents of this directory (``schemas/healthdcatap/``) are licensed under Creative Commons Attribution 4.0 International (CC BY 4.0) as stated by the [HealthDCAT-AP Release 6 publication](https://healthdataeu.pages.code.europa.eu/healthdcat-ap/releases/release-6/#speclicence). See [``LICENSE``](./LICENSE) for further details.

## No endorsement

HealthDCAT-AP, the European Commission, and the European Union **do not** endorse this repository or these derived JSON Schemas.
