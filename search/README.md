# viet-print-index / search

Scala 3 library for indexing and searching Google Cloud Vision OCR data from the Thanh Nghi newspaper archive into a SQLite FTS5 database.

## Modules

| Module | Purpose |
|--------|---------|
| `db` | Shared schema, transactor, Vietnamese text normalisation |
| `ingest` | Parse GCV JSON → insert into SQLite |
| `search` | FTS5 keyword search → file paths + snippets |
| `cli` | Command-line tool wrapping `ingest` |

## Prerequisites

- JDK 11+
- [Mill](https://mill-build.org) 1.1.6+ (`brew install mill`)

## Build

```sh
mill __.compile       # compile all modules
mill __.test          # run all tests
```

## CLI — index OCR files

The `cli` module wraps `Indexer.indexAll`. It walks an OCR directory tree of the form `{ocrDir}/{issue}/{page}.json` and inserts every page into a SQLite FTS5 database.

### Run directly with Mill

```sh
mill cli.run --db /path/to/index.db --ocr-dir /path/to/ocr/root
```

Example (from the `search/` directory):

```sh
mill cli.run index \
  --db ../data/index.db \
  --ocr-dir ../data/thanh-nghi/ocr/20260405_gc_vision
```

Progress is printed per file:

```
[    1/3322] 105/000.json
[    2/3322] 105/001.json
...
[3322/3322] 227/016.json
Done.
```

### Run as a standalone fat jar

Build the assembly jar once (from the `search/` directory):

```sh
mill cli.assembly
# jar written to: out/cli/assembly.dest/out.jar
```

Then run anywhere with plain `java`:

```sh
java -jar /path/to/search/out/cli/assembly.dest/out.jar \
  --db /path/to/index.db \
  --ocr-dir /path/to/ocr/root
```

### Options

| Flag | Required | Description |
|------|----------|-------------|
| `--db` | yes | Path to the output SQLite database file (created if absent) |
| `--ocr-dir` | yes | Path to the OCR base directory containing `{issue}/{page}.json` files |
| `--help` | — | Print usage |

### Notes

- Re-running against the same database is safe — inserts use `INSERT OR IGNORE`, so existing rows are skipped.
- `file_path` values stored in the database are relative to `--ocr-dir` (e.g. `105/000.json`).
- Search queries can use original Vietnamese (with diacritics) or the stripped form; both normalise to the same indexed text.

## Search (library usage)

```scala
import cats.effect.unsafe.implicits.global
import doobie.implicits._
import vpi.db.Db
import vpi.search.Search

val xa = Db.transactor("data/index.db")
val results = Search.search("hội nghị").transact(xa).unsafeRunSync()
// List[SearchResult(filePath, snippet)]
```
