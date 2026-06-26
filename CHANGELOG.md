# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project will follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once schema releases begin.

## [Unreleased]
- Testing biovalidator-monitoring webhook
### Added

- Draft FEGA metadata schemas for the EGA entities
- Shared schema modules for common definitions validation.
- JSON-LD contexts and frames for entity schemas, with local examples covering valid and invalid validation cases.
- Validation tooling for JSON Schema/Biovalidator checks, JSON-LD context smoke tests, context/frame coverage, JSON-LD frame round-trip checks, and RDF/SHACL validation.
- Reusable Python helper package for validation, JSON-LD processing, RDF handling, logging, JSON Pointer access, and Biovalidator integration.
- Pytest coverage.
- Third-party standards material (e.g., ISA) used by the model.
- Technical report, release process documentation, and repository-level usage instructions.
