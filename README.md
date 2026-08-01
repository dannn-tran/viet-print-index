# Vietnamese Print Publication Index

Full-text search and browse over historical Vietnamese periodicals, powered by Google Cloud Vision OCR and SQLite FTS5.

---

## Architecture

```
[sources/]          [vie-pipeline]                   [target storage]
  *.toml  ──────►  source discover/fetch     ─────► original assets
  (per-pub config) images normalize          ─────► image assets
                    OCR submit/check          ─────► OCR JSON
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

Two toolchains, one contract. The configured target is the durable store and the
handoff point between them; production runs normally use GCS.

The Python package keeps the workflow boundaries visible: `config.py` decodes
TOML into typed values, `assets.py` owns the cross-stage asset contract,
`sources/` owns source discovery contracts, factories, and HTTP adapters,
`images/` owns PDF/image transformations and calibration contracts,
`ledger/` owns event contracts, JSONL persistence, and projection, and
`workflow/` owns the staged orchestration and its result contracts. External
clients are created and closed by the stage or provider that owns their lifetime.

| Toolchain | Responsibilities |
|-----------|-----------------|
| **Python** (`vie-pipeline`) | Acquire source assets, normalize durable presentation/OCR images, manage GCV OCR jobs |
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
2. Calibrate PDF extraction: `vie-pipeline images calibrate <id> --pdf <sample.pdf>`
3. Review `calibrate/<id>/` variants, update `[explode]` section in TOML
4. Run the pipeline (see below)

---

## Pipeline

All commands run from the repo root. Replace `<pub-id>` with a publication ID from the table above.

### Preferred staged workflow

All source types use the same resumable workflow, backed by an append-only
JSONL ledger at `.pipeline-state/v2/<pub>.jsonl`:

```sh
vie-pipeline source discover <pub-id>  # enumerate original source records
vie-pipeline source fetch <pub-id>     # fetch originals into target storage
vie-pipeline images normalize <pub-id> # create presentation/OCR image assets
vie-pipeline ocr submit-jobs <pub-id>  # start asynchronous OCR jobs
vie-pipeline ocr check-status <pub-id> # report completed/pending OCR output
```

### Workflow contracts

- Source adapters only enumerate source items. They do not apply CLI batch
  limits, write the ledger, or create target objects.
- Each workflow stage applies `--limit` once, immediately after selecting its
  candidate assets and before performing external work.
- TOML is decoded into a validated source variant before discovery. A Veridian
  source, a PDF index page, a URL sequence, a URL list, and a local directory
  therefore cannot be confused at runtime.
- JSONL is the durable, human-inspectable event format; Python projects it into
  typed in-memory asset state for workflow decisions.
- The first JSONL record stores the SHA-256 of the exact TOML bytes used for the
  run. Loading a ledger with a different TOML fails before work begins, so
  configuration changes cannot silently mix states.
- The ledger stores this fingerprint, not a copy of the full TOML; retain the
  versioned source config when you need to reconstruct historical settings.
- Workflows return typed summaries. The CLI alone prints human-facing output.

### Source request policy

HTTP requests are generic across source adapters. Configure bounded
concurrency, source-wide pacing, and bounded retries per publication:

```toml
[source_requests]
max_concurrent_requests = 2
min_interval_seconds = 1.0
max_attempts = 5
backoff_factor = 1.0
backoff_max_seconds = 30.0
backoff_jitter_seconds = 0.5
```

The interval applies to every initial request and retry across worker
threads. Temporary network failures and HTTP `429`, `500`, `502`, `503`, and
`504` retry with backoff and respect `Retry-After`; other HTTP 4xx responses
are recorded as permanent failures. Each completed fetch is immediately
written to the ledger. Re-running `source fetch` resumes eligible work,
skips target objects already present, and leaves permanent failures untouched.
Only one source-fetch command may run for a publication at once.

### Target storage

The `[target]` section selects where source, image, and OCR objects live. GCS
is the production target; a local target is useful for previews and offline
development:

```toml
[target]
type = "local"
root = "out/cuu-quoc"
pdf_prefix = "pdf"
images_prefix = "images"
ocr_output_prefix = "ocr"
```

For GCS, use `type = "gcs"` with `project`, `bucket`, and the three prefixes.
OCR submission requires a GCS target because Google Vision batch OCR reads and
writes GCS objects.

An `ImageAsset` may be a page, spread, cover, or other scanned unit. Native
images that need no correction remain at their original GCS object; PDF sources
produce derived images. These image assets are the shared coordinate canvas for
presentation and OCR overlays.

`images normalize` checks every image for likely inverted colours. Ambiguous
images are retained unchanged and listed by `images review`; use `--inverted`
for an issue/PDF or a specific image when correction is needed:

```sh
vie-pipeline images review <pub-id>
vie-pipeline images normalize <pub-id> --source-id <issue-or-pdf-id> --inverted
vie-pipeline images normalize <pub-id> --image-id <ledger-image-key> --inverted
```

### Index OCR → SQLite

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
workflow as every other source. A native full-page JPEG that does not need
normalization is registered in place, without a duplicate target object.

```sh
# Discover full-page source assets into an inspectable v2 ledger
vie-pipeline source discover nlv-cuu-quoc --limit 10

# Fetch only discovered-but-not-yet-fetched originals.
vie-pipeline source fetch nlv-cuu-quoc --limit 10

# Inspect and register native images for presentation and OCR.
vie-pipeline images normalize nlv-cuu-quoc

# Submit quickly, then check later. Neither command waits for long OCR work.
vie-pipeline ocr submit-jobs nlv-cuu-quoc
vie-pipeline ocr check-status nlv-cuu-quoc

# Inspect projected lifecycle and image-review state.
vie-pipeline status nlv-cuu-quoc
```

The source config must provide `type = "veridian"`, `catalogue_url`,
`image_server_url`, the NLV `title_id`, and an inclusive `from_date`/`to_date`.
`source discover` requests Veridian's complete issue catalogue (`ai=1`), filters
the direct issue links to the configured date range, records each source image in
`.pipeline-state/v2/<pub>.jsonl`, and
`source fetch` requests each complete page as one JPEG. Review collection terms and
retain a conservative request delay before widening a run.

### Calibrate extraction params

Before normalizing a PDF collection, inspect image derivation variants:

```sh
vie-pipeline images calibrate <pub-id> --pdf <path/to/sample.pdf>
```

Outputs 5 image variants to `calibrate/<pub-id>/<stem>/`:

| Variant | Description |
|---------|-------------|
| `raw/` | Extract embedded images as-is |
| `render/` | Rasterise pages at configured DPI |
| `render+negate/` | Rasterise + invert colours |
| `render+no-text/` | Rasterise with digital text layer removed |
| `render+no-text+negate/` | Both of the above |

Also prints heuristic suggestions for PDF rendering options (detected text layers and rotated pages). Update `[explode]` in the publication TOML based on what looks best; per-image inversion is handled by `images normalize`.

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

[target]
type              = "gcs"
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

[source_requests]
max_concurrent_requests = 2
min_interval_seconds = 1.0
max_attempts = 5
backoff_factor = 1.0
backoff_max_seconds = 30.0
backoff_jitter_seconds = 0.5
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
