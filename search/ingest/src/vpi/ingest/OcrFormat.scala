package vpi.ingest

import io.circe.parser.decode

trait OcrFormat:
  def parse(content: String): List[(String, String)]

object SingleFormat extends OcrFormat:
  def parse(content: String): List[(String, String)] =
    decode[GcvResponse](content).toOption.flatMap(extractPage).toList

object BatchedFormat extends OcrFormat:
  def parse(content: String): List[(String, String)] =
    decode[GcvBatch](content).toOption.toList.flatMap(_.responses.flatMap(extractPage))
