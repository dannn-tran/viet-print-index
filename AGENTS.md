# Principles for readable, consistent, testable Python

Use these principles before adding or refactoring code. The aim is not maximal
abstraction or maximal functional style: it is code whose responsibilities,
control flow, interfaces, effects, and failure modes are evident to a reader.

## Start with boundaries and ownership

- Give every policy one owner. If a rule can be applied in several layers
  (batch limits, retries, validation, formatting, deduplication), state which
  layer owns it and apply it there once.
- Acquire a resource at the narrowest boundary that needs it. Open files,
  database connections, network clients, worker pools, and locks explicitly;
  close them in the same scope with a context manager or `try`/`finally`.
- Let the owner of a resource own its lifetime. Do not create a client merely
  because a deeper function *might* use it.
- Keep presentation at the outermost boundary. Library and workflow functions
  return typed values; CLI/UI code formats, prints, or displays them.

## Model valid states and variants explicitly

- Prefer immutable `@dataclass(frozen=True)` values for stable domain data.
- When inputs have distinct shapes or behaviour, use a discriminated union of
  dataclasses rather than one “god config” with a string `type` plus many
  optional fields. Parse untyped input into one validated variant at the edge.
- Match on the variant object—not repeated string tags—at the behaviour
  boundary. Keep decoding of external tags and dispatch of runtime behaviour
  separate, but centralize each in one clear place.
- Make invalid states unrepresentable when practical. If a variant requires a
  URL, date range, or credential, its constructor should require it rather
  than relying on downstream `assert`s or fallback defaults.
- Keep JSON, TOML, HTTP payloads, and database rows at persistence/I/O edges.
  Convert them to typed values before business logic consumes them.

## Choose functions, objects, and factories deliberately

- Use a function for a stateless transformation with explicit inputs and
  output. Prefer a pure function when it can express the work directly.
- Use an object when it represents a domain value, owns mutable state, groups
  a coherent capability, or owns a resource/lifecycle. Do not introduce a
  class just to namespace one function.
- Do not pass bare `Callable`s as ad-hoc dependency injection through a call
  graph. A callback is appropriate for a small local algorithm hook; a named
  object is clearer when the dependency has state, multiple operations,
  configuration, or a lifetime.
- Use a factory when construction depends on a validated variant or when it
  selects among interchangeable implementations. The factory should return a
  common protocol/interface and should create only the dependencies required
  by the chosen implementation.
- Match a discriminated union once in the factory, construct the selected
  implementation there, and let that implementation run directly. Do not
  first categorize variants (for example, “HTTP” versus “static”) and then
  match the same variant again inside a generic implementation.
- Keep factory selection comparable: implementations should expose the same
  primary method and follow one naming grammar. Put shared lifecycle handling
  at the factory/context-manager boundary, not in callers.
- Use an `ABC` for a closed, factory-owned family with a lifecycle or a runtime
  contract that implementations must satisfy. Use `Protocol` for an open
  boundary where independently defined or third-party implementations should
  participate structurally. Keep concrete implementation details internal.

## Make control flow linear and unsurprising

- Prefer guard clauses and inverted conditions to reduce indentation.
- A helper earns its existence when it names a reusable domain operation,
  isolates a meaningful I/O boundary, or makes a long function genuinely
  easier to read. Inline one-use plumbing and needless forwarding methods.
- Prefer one clear Python idiom per transformation: a direct loop, one
  generator expression, or one comprehension. Do not combine `map`, `filter`,
  `partial`, generators, and comprehensions merely to look functional.
- Use `match` for a closed set of meaningful variants. Avoid long `if`/`elif`
  chains over discriminator strings and avoid duplicating the same dispatch in
  multiple modules.
- Avoid boolean flag bundles and positional tuple returns. Use named arguments
  for optional behaviour and named result dataclasses for multi-field results.
- Name values by what they represent, not how they happen to be implemented.
  Comparable functions should use comparable names that describe their output
  and source of input.

## Separate pure logic from effects

- Keep selection, parsing, validation, and transformation as pure as possible.
  Make HTTP, filesystem, database, queue, clock, randomness, logging, and
  mutation visible at an execution boundary.
- Group a stage's stable external dependencies into a small immutable context
  only when passing them individually obscures the operation. Do not use a
  context object as a miscellaneous dependency bag.
- Do not hide effects in convenience helpers whose names sound pure. A caller
  should be able to tell when an operation reads, writes, submits, deletes, or
  makes a network request.

## Handle errors as part of the interface

- Validate external input early and produce errors that identify the bad field,
  value, and source where safe to do so.
- Catch only errors the layer can actually handle. Unexpected programming,
  schema, and configuration errors should surface; do not silently convert
  them into retries or empty results.
- Classify retryable failures explicitly. Retry only known transient failures,
  with bounded attempts, backoff, and a documented restart/idempotency model.
- Log malformed external records or anomalous state at the parsing boundary
  when they may be systematic. Log concise, actionable context; avoid noisy
  per-item stack traces for expected bad input.

## Design and test contracts

- Document public semantics that are easy to misplace: ordering, limits,
  deduplication, pagination, retries, resource ownership, and idempotency.
- Add a regression test whenever a boundary changes. Test the contract rather
  than private implementation details: variant dispatch, resource creation and
  cleanup, malformed input, retry classification, restart behaviour, and
  ordering are valuable examples.
- Prefer fakes that implement a small protocol over patches of deep internal
  functions. Patch only at true external boundaries.
- Keep tests deterministic: inject or control clocks, randomness, I/O, and
  concurrency at their boundaries.

## Maintain a coherent codebase

- Before editing, inspect neighbouring code and established conventions. Do
  not introduce a second naming, error, iteration, or dependency style without
  a deliberate migration plan.
- Refactor coherently: update callers, tests, documentation, and terminology
  in the same change. Remove superseded compatibility code unless it is a
  documented public requirement.
- Keep commits narrow and independently verifiable. Run the formatter/linter,
  relevant tests, and a whitespace diff check before committing.
