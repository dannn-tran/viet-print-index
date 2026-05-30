package vpi.ingest

import io.circe.Decoder

case class FullTextAnnotation(text: String) derives Decoder
case class GcvResponse(fullTextAnnotation: FullTextAnnotation) derives Decoder
