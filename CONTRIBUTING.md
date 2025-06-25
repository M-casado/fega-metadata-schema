# Contributing to **fega-metadata-schema**

Thank you for your interest in improving the FEGA metadata model!  We welcome pull-requests and issue reports from **FEGA nodes, downstream integrators, and the wider community**.  This document explains the conventions and workflow we follow in this repository.

> **Scope** – This repo contains JSON Schemas, JSON-LD contexts/frames, examples, validation utilities and documentation *specific to the Federated EGA metadata model*.  Issues relating to other FEGA software (portal, download client, etc.) should be opened in their respective repositories. For general inquiries, please fill the [**Need-help form**](https://ega-archive.org/need-help/).

## 1  Ways to contribute

| Activity | How |
| --------------------------------------- | ----------------- |
| **Report a bug**                        | Use the *Bug report* issue template. It collects schema/tool versions, reproduction steps, and expected vs. observed behaviour.       |
| **Suggest a change**              | Use the *Change request* issue template. Describe the use-case first, then a proposal (new property, enum value, structural change, etc.). |
| **Direct contributions**               | Open a pull-request containing the pertinent changes, and following the [PR template](./.github/pull_request_template.md). |
| **Ask a question / start a discussion** | Either create a [blank GH issue](https://github.com/EGA-archive/fega-metadata-schema/issues/new) or reach out to the community through the [ELIXIR FEGA Slack channel](https://elixir-europe.slack.com/archives/C05UHABF0CT). |

## 2  Before you start

* **Check existing [issues](https://github.com/EGA-archive/fega-metadata-schema/issues)/[PRs](https://github.com/EGA-archive/fega-metadata-schema/pulls)** – someone might be working on the same topic.
* **Follow the Code of Conduct** – be respectful and constructive.
* **Use descriptive titles** – this helps triaging and search.
* **Provide detailed descriptions** – this helps fixing or improving the content faster.

## 3  Pull-request workflow

1. **Fork** the repository (or create a feature branch if you have push rights).
2. Create a **topic branch** off ``main`` or ``dev``, e.g. `feat/add-sample-tissue-enum`.
3. Make your changes and verify locally that files within ``data`` validate against the local schemas:

   ```bash
   #! TBD - Also will be done automatically through the PR workflows
   ```

4. **Update metadata artefacts** if you changed schemas:

   * Increment the `meta:version` field.
   
5. **Add or update data / docs** so behaviour is demonstrably correct.
6. **Amend `CHANGELOG.md`** under the *Unreleased* section.
7. Commit with a **clear message** (`type(scope): summary`, e.g. `feat(schema): add new library_strategy enum values`).
8. Push and **open the PR**.  The pull-request template will guide you through the last checks.

### Review & merge rules

* Two approving reviews from maintainers are required.
* CI **must pass** (e.g., lints, validation).
* Squash-and-merge is preferred unless history needs to be preserved.

## 4  Coding & style guidelines

| Area                | Tool / Convention   |
| ------------------- | ------------------- |
| **Python**          | Type hints encouraged; keep reusable logic in `src/fega_tools/`.          |
| **JSON Schemas**    | `$id`, `title`, `description` and `meta:version` are mandatory; use `$ref` over copy-paste. More details at [``schemas``](./schemas/README.md). |
| **Commit messages** | Conventional Commits style (`fix:`, `feat:`, `docs:` …).                                       |
| **Docs**            | Markdown (`.md`), diagrams as SVG/PNG in `docs/images/`.                                      |

## 5  License & contributor certificate

By submitting code, documentation or schema changes you agree that your contribution is licensed under the terms stated in [`LICENSE`](./LICENSE).  If you include third-party material, ensure it is compatible with this license and properly attributed.

## 7  Need help?

* **Helpdesk:** [Need-help form](https://ega-archive.org/need-help/)
* **Slack:** [ELIXIR FEGA Slack channel](https://elixir-europe.slack.com/archives/C05UHABF0CT)

We appreciate every contribution – large or small – that makes the FEGA metadata ecosystem more robust and easier to use.  Thank you for helping the community!
