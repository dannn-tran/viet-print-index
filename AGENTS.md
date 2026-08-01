# Python design rules

These rules apply to `pipeline/` and take precedence over local stylistic
preferences. Make a deliberate design check before adding code; do not rely on
reviewers to discover basic structural inconsistencies.

## Boundaries and ownership

- Give each policy one owner. In particular, adapters enumerate; workflow
  stages select and limit candidates; the CLI renders output.
- Acquire a resource only at the narrowest boundary that needs it, and make its
  lifetime explicit. A source factory may create an HTTP-backed source reader;
  static URL or local-file sources must not create an HTTP client.
- Do not pass bare `Callable`s as ad-hoc dependency injection through the call
  graph. If behaviour needs state, a lifecycle, or multiple operations, expose
  a small typed object with a named method.
- Classes are justified for immutable domain values and resource-owning or
  lifecycle-owning adapters. Prefer functions for stateless transformations.

## Types and interfaces

- Model variants as typed dataclasses/unions, not one record with many optional
  fields plus a string discriminator. Parse TOML into a valid variant at the
  boundary.
- Define one comparable interface for interchangeable implementations. Use one
  naming grammar that describes the returned value, e.g. `iter_source_items`.
- Return named result records, never positional tuples or boolean flag bundles.
- Keep JSON/JSONL dictionaries at persistence boundaries. Project them into
  typed values before workflow logic consumes them.

## Control flow and Python idioms

- Prefer the simplest single idiom in a function: a direct loop, one generator
  expression, or one comprehension. Do not mix `map`, `filter`, `partial`, and
  comprehensions merely to appear functional.
- Use a helper only when it names a reusable domain operation, isolates a
  non-trivial boundary, or materially improves a long function. Inline one-use
  iterator plumbing.
- Use guard clauses or inverted conditions to avoid nesting. Do not replace
  clear linear code with abstract chaining.
- Handle expected malformed external data explicitly. Log actionable anomalies
  once at the parsing boundary; do not silently discard systematic defects.

## Effects, errors, and tests

- Keep pure selection/transformation separate from HTTP, GCS, ledger writes,
  logging, and CLI output. Effects belong in an explicit execution boundary.
- Retry only known transient infrastructure failures. Do not turn programming,
  schema, or configuration errors into retries.
- Add or update a contract test with every boundary change: variant dispatch,
  limit placement, resource ownership, restart behaviour, and malformed input
  are all public behaviour.
- Run Ruff, the full Python test suite, and `git diff --check` before each
  commit. Commit coherent changes only; preserve unrelated working-tree files.
