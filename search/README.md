# viet-print-index / search

Scala 3 library for indexing and searching Google Cloud Vision OCR data from the Thanh Nghi newspaper archive into a SQLite FTS5 database.

## Modules

| Module | Purpose |
|--------|---------|
| `db` | Shared schema, transactor, Vietnamese text normalisation |
| `ingest` | Parse GCV JSON → insert into SQLite (`OcrSource` × `OcrFormat`) |
| `search` | FTS5 keyword search → image URIs + snippets |
| `cli` | Command-line tool: `index`, `search`, `get`, `context`, `view` subcommands |

## Prerequisites

- JDK 11+
- [Mill](https://mill-build.org) 1.1.6+ (`brew install mill`)
- For `index gcs`: Application Default Credentials (`gcloud auth application-default login`)

## Build

```sh
mill __.compile       # compile all modules
mill __.test          # run all tests
```

All commands below must be run from the `search/` directory.

## CLI

Two orthogonal dimensions control ingestion:

| Dimension | Options |
|-----------|---------|
| **Source** | `local` — read from local filesystem; `gcs` — stream from GCS bucket |
| **Format** | `single` — one GCV response per file; `batched` — `{"responses":[...]}` batch file |

### `index local` — index local OCR files

```sh
mill cli.run index local \
  --db ../data/index.db \
  --ocr-dir ../data/thanh-nghi/ocr/20260405_gc_vision \
  [--format single|batched]   # default: single
```

Progress is printed per file:

```
[    1/3320] 001/000.json
[    2/3320] 001/001.json
...
Done.
```

### `index gcs` — stream directly from GCS (resumable)

Each blob is committed atomically together with a checkpoint row. Interrupted runs skip already-committed blobs on resume.

```sh
mill cli.run index gcs \
  --db ../data/index.db \
  --bucket vie-doc \
  --prefix thanh-nghi/ocr/ \
  [--format single|batched]          # default: batched
  [--download-concurrency N]         # default: 1; increase for faster GCS downloads
```

Progress is printed per blob:

```
1500 items pending, 0 already done
[    1/1500] thanh-nghi/ocr/batch-001.json (28 pages)
[    2/1500] thanh-nghi/ocr/batch-002.json (30 pages)
...
Done.
```

Re-run after interruption resumes automatically:

```
300 items pending, 1200 already done
[    1/ 300] thanh-nghi/ocr/batch-1201.json (28 pages)
...
```

### `search` — interactive REPL or one-shot query

```sh
# Interactive REPL
mill cli.run search --db ../data/index.db

# One-shot with JSON output (for agents/scripts)
mill cli.run search --db ../data/index.db --json "hội nghị"
mill cli.run search --db ../data/index.db --pub thanh-nghi --limit 10 --json "hội nghị"
```

```
Enter query (Ctrl-D to exit)
> hội nghị
  1  gs://vie-doc/thanh-nghi/images/001/003.png  ...>>>hoi nghi<<<...
(12 results)
> :1          ← type :N to fetch + open that image
> /clear      ← clears the screen
> ^D
```

- Queries accept original Vietnamese or diacritic-stripped form.
- Trigram tokenizer matches substrings (`nghi` is a superset of `hoi nghi`).
- FTS5 syntax works: `"exact phrase"`, `term1 OR term2`, `term NOT excluded`.

### `get` — full page text

```sh
mill cli.run get --db ../data/index.db --uri gs://vie-doc/thanh-nghi/images/001/003.png [--json]
```

### `context` — surrounding pages

```sh
mill cli.run context --db ../data/index.db --uri gs://... --window 2 [--json]
```

Returns up to `2×window + 1` pages centred on the given URI, in page order.

### `view` — open page image

```sh
mill cli.run view --uri gs://vie-doc/thanh-nghi/images/001/003.png
```

Fetches from GCS to `~/.vpi/cache/`, opens with system viewer.

### Run as a standalone fat jar

```sh
mill cli.assembly
# jar written to: out/cli/assembly.dest/out.jar

java -jar out/cli/assembly.dest/out.jar index local --db /path/to/index.db --ocr-dir /path/to/ocr
java -jar out/cli/assembly.dest/out.jar index gcs   --db /path/to/index.db --bucket my-bucket --prefix ocr/
java -jar out/cli/assembly.dest/out.jar search      --db /path/to/index.db
```

## Schema

```sql
pages     (image_uri TEXT PRIMARY KEY, text TEXT, text_norm TEXT, publication_id TEXT)
pages_fts — FTS5 virtual table over text_norm, trigram tokenizer
gcs_blobs (blob_name TEXT PRIMARY KEY, indexed_at TEXT)  -- GCS resumption checkpoint
```

`image_uri` is the GCS URI of the original scan image (e.g. `gs://vie-doc/thanh-nghi/images/105/000.png`).

## Ingest API

```scala
// Compose any source × format combination
Indexer.indexAll(
  dbPath = "data/index.db",
  source = LocalSource("data/thanh-nghi/ocr/20260405_gc_vision"),
  format = SingleFormat,
)

Indexer.indexAll(
  dbPath = "data/index.db",
  source = GcsSource(bucket = "vie-doc", prefix = "thanh-nghi/ocr/"),
  format = BatchedFormat,
)
```

## Search API

```scala
import cats.effect.unsafe.implicits.global
import doobie.implicits.*
import vpi.db.Db
import vpi.search.Search

Db.transactor("data/index.db").use { xa =>
  // keyword search (optional pub filter + pagination)
  Search.search("hội nghị", pub = Some("thanh-nghi"), limit = 20).transact(xa)
  // List[SearchResult(imageUri, snippet, publicationId)]

  // full page text
  Search.getPage("gs://vie-doc/thanh-nghi/images/001/003.png").transact(xa)
  // Option[PageResult(imageUri, text, publicationId)]

  // surrounding pages
  Search.contextPages("gs://vie-doc/thanh-nghi/images/001/003.png", window = 2).transact(xa)
  // List[PageResult] — up to 5 pages centred on the given URI
}.unsafeRunSync()
```
