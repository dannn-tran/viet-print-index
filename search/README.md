# viet-print-index / search

Scala 3 library for indexing and searching Google Cloud Vision OCR data from the Thanh Nghi newspaper archive into a SQLite FTS5 database.

## Modules

| Module | Purpose |
|--------|---------|
| `db` | Shared schema, transactor, Vietnamese text normalisation |
| `ingest` | Parse GCV JSON → insert into SQLite (`OcrSource` × `OcrFormat`) |
| `search` | FTS5 keyword search → image URIs + snippets |
| `cli` | Command-line tool: `index local`, `index gcs`, `search` subcommands |

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
  [--format single|batched]   # default: batched
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

### `search` — interactive keyword search

```sh
mill cli.run search --db ../data/index.db
```

```
Enter query (Ctrl-D to exit)
> hội nghị
gs://vie-doc/thanh-nghi/images/001/001.png  ...>>>hoi nghi<<<...
(12 results)

> trien lam
...
> /clear      ← clears the screen
> ^D
```

- Queries accept original Vietnamese or diacritic-stripped form.
- Trigram tokenizer matches substrings (`nghi` is a superset of `hoi nghi`).
- FTS5 syntax works: `"exact phrase"`, `term1 OR term2`, `term NOT excluded`.

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
pages     (image_uri TEXT PRIMARY KEY, text TEXT, text_norm TEXT)
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

val xa = Db.transactor("data/index.db")
val results = Search.search("hội nghị").transact(xa).unsafeRunSync()
// List[SearchResult(imageUri, snippet)]
```
