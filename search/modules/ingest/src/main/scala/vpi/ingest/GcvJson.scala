package vpi.ingest

import io.circe.Decoder
import io.circe.generic.semiauto.deriveDecoder

case class FullTextAnnotation(text: String)

object FullTextAnnotation:
  given Decoder[FullTextAnnotation] = deriveDecoder

case class GcvResponse(fullTextAnnotation: FullTextAnnotation)

object GcvResponse:
  given Decoder[GcvResponse] = deriveDecoder
