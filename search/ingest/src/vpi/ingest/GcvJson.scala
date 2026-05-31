package vpi.ingest

import io.circe.Decoder

case class FullTextAnnotation(text: String) derives Decoder
case class GcvContext(uri: String) derives Decoder
case class GcvResponse(
  fullTextAnnotation: Option[FullTextAnnotation],
  context: Option[GcvContext],
) derives Decoder
case class GcvBatch(responses: List[GcvResponse]) derives Decoder

def extractPage(r: GcvResponse): Option[(String, String)] =
  for fta <- r.fullTextAnnotation; ctx <- r.context yield (ctx.uri, fta.text)
