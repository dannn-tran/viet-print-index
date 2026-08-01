"""Create or designate image assets for presentation and OCR."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import replace
from itertools import islice
from pathlib import Path
from pathlib import PurePosixPath

from google.api_core import exceptions as google_exceptions
import fitz

from vie_doc_pipeline.images.pdf import explode_pdf_bytes
from vie_doc_pipeline.ledger.events import failed, image_normalized
from vie_doc_pipeline.ledger.configuration import ensure_config_compatible
from vie_doc_pipeline.ledger.projection import AppState, CurrentState, assets_at
from vie_doc_pipeline.ledger.store import EventStore
from vie_doc_pipeline.assets import ImageAsset, PdfAsset, SourceAsset
from vie_doc_pipeline.config import PipelineConfig
from vie_doc_pipeline.images.processing import check_inversion, invert_image
from vie_doc_pipeline.storage import TargetStore, open_target_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NormalizationSummary:
    created: int = 0
    native_registered: int = 0
    failed: int = 0


@dataclass(frozen=True)
class InversionOverrides:
    source_ids: frozenset[str]
    image_keys: frozenset[str]


@dataclass(frozen=True)
class AllNormalizationCandidates:
    """Select every source asset not yet normalized."""


@dataclass(frozen=True)
class SourceNormalizationCandidates:
    source_id: str


@dataclass(frozen=True)
class ImageNormalizationCandidates:
    image_key: str


NormalizationSelection = (
    AllNormalizationCandidates | SourceNormalizationCandidates | ImageNormalizationCandidates
)


@dataclass(frozen=True)
class NormalizationContext:
    """External capabilities and fixed inputs for one normalisation-stage run."""

    config: PipelineConfig
    state: AppState
    store: TargetStore
    overrides: InversionOverrides


def normalize_images(
    config: PipelineConfig,
    ledger_path: Path,
    limit: int | None = None,
    selection: NormalizationSelection = AllNormalizationCandidates(),
) -> NormalizationSummary:
    """Create image assets from PDFs or designate native images without copying."""
    event_store = EventStore.open(ledger_path)
    ensure_config_compatible(event_store, config.config_snapshot)
    with open_target_store(config.target) as store:
        state = AppState.replay(event_store)
        current = state.current
        overrides = load_inversion_overrides(state.event_store)
        assets = iter_normalization_candidates(current, selection, limit)
        context = NormalizationContext(config, state, store, overrides)
        results = (normalize_asset(context, asset) for asset in assets)
        return summarize_normalization(results)


def iter_normalization_candidates(
    current: CurrentState,
    selection: NormalizationSelection,
    limit: int | None,
) -> Iterator[SourceAsset]:
    """Yield source assets selected for normalisation or explicit reprocessing."""
    match selection:
        case AllNormalizationCandidates():
            candidates = (state.asset for state in assets_at(current, "source_downloaded") if state.asset is not None)
        case SourceNormalizationCandidates():
            candidates = (asset for _, asset in iter_reprocessable_assets(current) if _source_id(asset) == selection.source_id)
        case ImageNormalizationCandidates():
            candidates = (asset for key, asset in iter_reprocessable_assets(current) if key == selection.image_key)
    yield from islice(candidates, limit)


def iter_reprocessable_assets(current: CurrentState) -> Iterator[tuple[str, SourceAsset]]:
    """Yield explicitly selected assets without repeatedly decoding ledger data."""
    for key, state in tuple(current.items()):
        if state.asset is None or state.event not in {"source_downloaded", "image_normalized"}:
            continue
        yield key, state.asset


def normalize_asset(
    context: NormalizationContext,
    asset: SourceAsset,
) -> NormalizationSummary:
    """Normalise one source asset and persist either its images or failure."""
    try:
        match asset:
            case ImageAsset():
                return NormalizationSummary(native_registered=normalize_native_image(context, asset))
            case PdfAsset():
                return NormalizationSummary(created=normalize_pdf_asset(context, asset))
    except (google_exceptions.GoogleAPIError, OSError, ValueError, fitz.FitzError) as error:
        context.state.record(failed(asset.key, stage="normalize", error=str(error)))
        logger.warning("Failed to normalize %s: %s", asset.key, error)
    return NormalizationSummary(failed=1)


def normalize_native_image(
    context: NormalizationContext,
    asset: ImageAsset,
) -> int:
    """Designate a native image, writing a new object only when it is inverted."""
    raw_bytes = context.store.read_bytes(asset.target_path)
    image = _normalize_bytes(asset, raw_bytes, asset.target_path, is_forced_inverted(asset, context.overrides))
    if image.target_path != asset.target_path:
        context.store.write_bytes(
            image.target_path,
            invert_image(raw_bytes, asset.target_path),
            content_type=_image_content_type(image.target_path),
        )
    context.state.record(image_normalized(image))
    return 1


def normalize_pdf_asset(
    context: NormalizationContext,
    asset: PdfAsset,
) -> int:
    """Render one PDF and store its presentation/OCR image assets."""
    pdf_bytes = context.store.read_bytes(asset.target_path)
    created = 0
    for image, image_bytes in iter_pdf_image_assets(context.config, asset, pdf_bytes, context.overrides):
        store_pdf_image(context.store, image, image_bytes)
        context.state.record(image_normalized(image))
        created += 1
    context.state.record(image_normalized(asset))
    return created


def iter_pdf_image_assets(
    config: PipelineConfig,
    asset: PdfAsset,
    pdf_bytes: bytes,
    overrides: InversionOverrides,
) -> Iterator[tuple[ImageAsset, bytes]]:
    """Yield normalised image records and bytes rendered from one PDF."""
    for filename, image_bytes in explode_pdf_bytes(pdf_bytes, config.explode):
        image = pdf_image_asset(config, asset, filename)
        yield _normalize_bytes(image, image_bytes, filename, is_forced_inverted(image, overrides)), image_bytes


def pdf_image_asset(config: PipelineConfig, asset: PdfAsset, filename: str) -> ImageAsset:
    """Build the canonical image-asset record for one rendered PDF image."""
    return ImageAsset(
        publication_id=asset.publication_id,
        issue_id=asset.document_id,
        page_id=PurePosixPath(filename).stem,
        source_url=asset.source_url,
        target_path=f"{config.target.images_prefix}/{asset.document_id}/{filename}",
        issue_label=asset.document_id,
    )


def store_pdf_image(store: TargetStore, image: ImageAsset, image_bytes: bytes) -> None:
    """Upload a rendered image exactly once, applying inversion when required."""
    if store.inspect(image.target_path) is not None:
        return
    output = invert_image(image_bytes, image.target_path) if image.inverted else image_bytes
    store.write_bytes(image.target_path, output, content_type=_image_content_type(image.target_path))


def summarize_normalization(results: Iterator[NormalizationSummary]) -> NormalizationSummary:
    """Reduce individual normalisation outcomes into a typed stage summary."""
    created = 0
    native_registered = 0
    failed = 0
    for result in results:
        created += result.created
        native_registered += result.native_registered
        failed += result.failed
    return NormalizationSummary(created, native_registered, failed)


def _image_content_type(filename: str) -> str:
    return "image/png" if filename.endswith(".png") else "image/jpeg"


def _source_id(asset: SourceAsset) -> str:
    return asset.document_id if isinstance(asset, PdfAsset) else asset.issue_id


def load_inversion_overrides(event_store: EventStore) -> InversionOverrides:
    """Read explicit review decisions once before normalising a batch."""
    events = tuple(event_store.read_events())
    return InversionOverrides(
        source_ids=frozenset(event.asset_key for event in events if event.event == "source_inverted"),
        image_keys=frozenset(event.asset_key for event in events if event.event == "image_inverted"),
    )


def is_forced_inverted(asset: ImageAsset, overrides: InversionOverrides) -> bool:
    """Return whether review explicitly requested inversion for this image."""
    return asset.key in overrides.image_keys or _source_id(asset) in overrides.source_ids


def _normalize_bytes(asset: ImageAsset, data: bytes, filename: str, forced_inverted: bool) -> ImageAsset:
    check = check_inversion(data)
    inverted = forced_inverted or check.inverted
    if not inverted:
        return replace(asset, needs_review=check.needs_review)
    suffix = PurePosixPath(filename).suffix
    stem = PurePosixPath(filename).stem
    return ImageAsset(
        publication_id=asset.publication_id,
        issue_id=asset.issue_id,
        page_id=f"{asset.page_id}-inverted",
        source_url=asset.source_url,
        target_path=str(PurePosixPath(asset.target_path).with_name(f"{stem}-inverted{suffix}")),
        width=asset.width,
        height=asset.height,
        issue_label=asset.issue_label,
        inverted=True,
    )
