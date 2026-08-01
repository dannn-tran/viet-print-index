# Vietnamese Print Publication Index

Full-text search and browse over historical Vietnamese periodicals, powered by Google Cloud Vision OCR and SQLite FTS5.

---

## Architecture

```
[sources/]          [vie-pipeline CLI]               [GCS bucket]
  *.toml  ──────►  ingest   ──────► PDFs      ─────► <pub>/pdf/
  (per-pub          explode  ──────► images    ─────► <pub>/images/
  config)           run-ocr  ──────► OCR JSON  ─────► <pub>/ocr/
                                                           │
                                            [vpi CLI]      │
                                            index gcs ◄────┘
                                                 │
                                            SQLite FTS5
                                            (data/index.db)
                                                 │
                                            vpi search
                                            vpi get
                                            vpi context
                                            vpi view ──► local cache ──► open image
```

Two toolchains, one contract. GCS is the durable store and the handoff point between them.

| Toolchain | Responsibilities |
|-----------|-----------------|
| **Python** (`vie-pipeline`) | Discover PDF URLs, download/upload PDFs, explode PDFs→images, submit GCV OCR |
| **Scala** (`vpi`) | Stream OCR JSON → SQLite FTS5, keyword search, full-text retrieval, browse |

---

## Quick Start

### Prerequisites

- Python 3.13+ with [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- JDK 11+ and [Mill](https://mill-build.org) (`brew install mill`)
- Google Cloud project with Vision API and GCS enabled
- Application Default Credentials: `gcloud auth application-default login`

### Setup

```sh
cd pipeline && uv sync   # install Python deps
cd ../search && mill __.compile   # compile Scala
```

---

## Publications

Each publication has a config file in `sources/<id>.toml`. Current publications:

| ID | Name |
|----|------|
| `thanh-nghi` | Thanh Nghi |
| `doi-moi` | Doi Moi |
| `tbtvcn` | Trung Bac Tan Van Chu Nhat |
| `ngay-nay` | Tuan Bao Ngay Nay |
| `bachkhoa` | Bach Khoa |
| `van-hoa-nguet-san` | Van Hoa Nguet San |
| `nam-phong-tap-chi` | Nam Phong Tap Chi |
| `nlv-cuu-quoc` | Cứu Quốc (National Library of Vietnam) |

### Adding a new publication

1. Create `sources/<id>.toml` (copy an existing one as template)
2. Calibrate extraction params: `vie-pipeline calibrate <id> --pdf <sample.pdf>`
3. Review `calibrate/<id>/` variants, update `[explode]` section in TOML
4. Run the pipeline (see below)

---

## Pipeline

All commands run from the repo root. Replace `<pub-id>` with a publication ID from the table above.

### Preferred staged workflow

All source types use the same resumable workflow, backed by an append-only
JSONL ledger at `.pipeline-state/<pub>.jsonl`:

```sh
vie-pipeline discover <pub-id>      # find source PDFs or native page images
vie-pipeline fetch <pub-id>         # store source assets in GCS
vie-pipeline materialize <pub-id>   # explode PDFs; record native images in place
vie-pipeline ocr submit <pub-id>    # submit only materialized page images
vie-pipeline ocr reconcile <pub-id> # check asynchronous OCR outputs
```

`materialize` never copies image-native sources: their fetched GCS object is
recorded directly as the OCR-ready page. PDF sources create page images under
`<pub>/images/` at this step. Index OCR after reconciliation with `vpi index gcs`.

`ingest`, `explode`, and `run-ocr` remain as legacy commands for existing
collections; use the staged workflow for all new work.

### 1. Ingest PDFs → GCS

Fetches PDFs from the configured source (web page, URL list, or local directory) and uploads them to GCS. Skips already-uploaded files.

```sh
vie-pipeline ingest <pub-id> [--limit N]   # --limit for test runs
```

### 2. Explode PDFs → images → GCS

Downloads each PDF from GCS, renders pages to images in memory, uploads images back to GCS. Skips already-exploded PDFs.

```sh
vie-pipeline explode <pub-id> [--limit N] [--workers 4]
```

### 3. Run OCR

Submits GCS images to Google Cloud Vision batch OCR. Output JSON blobs land under `<pub>/ocr/` in GCS.

```sh
vie-pipeline run-ocr <pub-id>
```

### 4. Index OCR → SQLite

Streams OCR JSON blobs from GCS into a local SQLite FTS5 database. Resumable: interrupted runs pick up from the last committed blob.

```sh
# Run from search/
mill cli.run index gcs \
  --db ../data/index.db \
  --bucket vie-doc \
  --prefix <pub-id>/ocr/
```

### Check status at any stage

```sh
vie-pipeline status <pub-id>
```

### National Library of Vietnam / Veridian sources

Some sources use the National Library of Vietnam's Veridian viewer rather
than PDFs. It is an image-native source and therefore follows the same staged
workflow as every other source. Its `materialize` stage records each fetched
full-page JPEG in place, without creating a second image object.

```sh
# Discover full-page assets into an inspectable state ledger
vie-pipeline discover nlv-cuu-quoc --limit 10

# Fetch only discovered-but-unfetched assets.
vie-pipeline fetch nlv-cuu-quoc --limit 10

# Native images are marked OCR-ready without copying them.
vie-pipeline materialize nlv-cuu-quoc

# Submit quickly, then reconcile later. Neither command blocks on long OCR work.
vie-pipeline ocr submit nlv-cuu-quoc
vie-pipeline ocr reconcile nlv-cuu-quoc

# Inspect the append-only JSONL ledger and its reconstructed current state.
vie-pipeline state nlv-cuu-quoc
```

The source config must provide `type = "veridian"`, `catalogue_url`,
`image_server_url`, the NLV `title_id`, and an inclusive `from_date`/`to_date`.
`discover` follows the title calendar and
month listings, records each source page in `.pipeline-state/<pub>.jsonl`, and
`fetch` requests each complete page as one JPEG. Review collection terms and
retain a conservative request delay before widening a run.

```
Publication : Thanh Nghi (thanh-nghi)
GCS bucket  : gs://vie-doc
  PDFs      :    120  (thanh-nghi/pdf/)
  Exploded  :    120  (thanh-nghi/images/)
  OCR blobs :   1500  (thanh-nghi/ocr-outputs/)
```

### Calibrate extraction params

Before running `explode` on a new publication, calibrate the extraction params:

```sh
vie-pipeline calibrate <pub-id> --pdf <path/to/sample.pdf>
```

Outputs 5 image variants to `calibrate/<pub-id>/<stem>/`:

| Variant | Description |
|---------|-------------|
| `raw/` | Extract embedded images as-is |
| `render/` | Rasterise pages at configured DPI |
| `render+negate/` | Rasterise + invert colours |
| `render+no-text/` | Rasterise with digital text layer removed |
| `render+no-text+negate/` | Both of the above |

Also prints heuristic suggestions (detected text layers, dark backgrounds, rotated pages). Update `[explode]` in the publication TOML based on what looks best.

---

## Search & Browse

All commands run from `search/`.

### Interactive search (REPL)

```sh
mill cli.run search --db ../data/index.db
```

```
Enter query (Ctrl-D to exit)
> hội nghị
  1  gs://vie-doc/thanh-nghi/images/001/003.png   ...>>>hoi nghi<<< Yalta...
  2  gs://vie-doc/thanh-nghi/images/042/011.png   ...Paris >>>hoi nghi<<<...
(2 results)
> :1          ← type :N to open that image (fetched from GCS, cached locally)
> /clear      ← clear screen
> ^D
```

Queries accept full Vietnamese or diacritic-stripped form. Trigram tokenizer matches substrings.

### One-shot search (for scripts / agents)

```sh
mill cli.run search --db ../data/index.db [--pub <id>] [--limit N] [--offset N] [--json] <query>
```

```sh
# JSON output for agent consumption
mill cli.run search --db ../data/index.db --json "hội nghị"
# → [{"imageUri":"gs://...","snippet":"...","publicationId":"thanh-nghi"}, ...]
```

### Retrieve full page text

```sh
mill cli.run get --db ../data/index.db --uri <image_uri> [--json]
```

### Retrieve surrounding pages (context window)

```sh
mill cli.run context --db ../data/index.db --uri <image_uri> --window 2 [--json]
```

Returns up to `2×window + 1` pages centred on the given URI, in page order.

### Open a page image

```sh
mill cli.run view --uri <image_uri>
```

Fetches the image from GCS to `~/.vpi/cache/`, then opens it with the system viewer.

---

## Schema

```sql
pages (
  image_uri      TEXT PRIMARY KEY,   -- gs://bucket/pub/images/issue/NNN.png
  text           TEXT,               -- raw OCR text
  text_norm      TEXT,               -- diacritic-stripped lowercase (FTS target)
  publication_id TEXT                -- e.g. "thanh-nghi"
)
pages_fts  -- FTS5 virtual table over text_norm, trigram tokenizer
gcs_blobs  -- GCS ingestion checkpoint (blob_name, indexed_at)
```

`image_uri` encodes publication, issue, and page. Page order within an issue is lexicographic on the filename (`001.png < 002.png < ...`), which the `context` command exploits.

---

## Source config format

```toml
[publication]
id   = "thanh-nghi"
name = "Thanh Nghi"

[gcs]
project           = "vie-ocr"
bucket            = "vie-doc"
pdf_prefix        = "thanh-nghi/pdf"
images_prefix     = "thanh-nghi/images"
ocr_output_prefix = "thanh-nghi/ocr"

[source]
# type options: web_page | url_sequence | url_list | local_dir | veridian
type     = "url_sequence"
base_url = "https://www.namkyluctinh.org/eBooks/Tap%20Chi/Thanh%20Nghi"
pattern  = "{:03d}.pdf"
range    = [1, 120]

# web_page:    page_url = "http://..."   (scrape PDF hrefs from HTML page)
# url_list:    urls = ["http://...", ...]
# url_sequence can also include urls = [...] for combined/irregular issues
# local_dir:   path = "data/mypub/pdf"

[explode]
preserve_crop        = true
negate_png           = false
preserve_orientation = true
no_text              = false
dpi                  = 300

[ocr]
language_hints = ["vi"]
```

---

## For AI agents

The `vpi` CLI is designed for programmatic use. Recommended tool set for a research agent:

| Tool | Command | Use |
|------|---------|-----|
| Search | `vpi search --db <db> --json <query>` | Find pages matching a keyword |
| Filter by pub | `vpi search --db <db> --pub <id> --json <query>` | Narrow to one publication |
| Paginate | `--limit N --offset N` | Walk through large result sets |
| Full text | `vpi get --db <db> --uri <uri> --json` | Read complete OCR text for a page |
| Context | `vpi context --db <db> --uri <uri> --window 2 --json` | Read surrounding pages for context |
| Browse | `vpi view --uri <uri>` | Open the source image (human step) |

All `--json` outputs use the structure:

```json
// search
[{"imageUri": "gs://...", "snippet": "...match...", "publicationId": "thanh-nghi"}]

// get / context
[{"imageUri": "gs://...", "text": "full page text...", "publicationId": "thanh-nghi"}]
```

Typical agent flow:
1. `search` → get a list of `imageUri` candidates
2. `get` each URI to read the full page text
3. `context` on interesting pages to read surrounding pages
4. Synthesise answer from retrieved text

Run the fat jar for a self-contained binary (no Mill required):

```sh
# from search/
mill cli.assembly
java -jar out/cli/assembly.dest/out.jar search --db ../data/index.db --json "hội nghị"
```
