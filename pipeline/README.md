# Python ingestion pipeline

Install the package and its workspace dependencies from this directory:

```sh
uv sync
```

Run commands from the repository root with the installed `vie-pipeline`
entrypoint. The complete architecture, configuration format, staged workflow,
restart semantics, and examples are documented in the repository [README](../README.md).

For example:

```sh
vie-pipeline source discover sources/nlv-cuu-quoc.toml --limit 10
vie-pipeline source fetch sources/nlv-cuu-quoc.toml --limit 10
vie-pipeline images normalize sources/nlv-cuu-quoc.toml
vie-pipeline ocr submit-jobs sources/nlv-cuu-quoc.toml
vie-pipeline ocr check-status sources/nlv-cuu-quoc.toml
```
