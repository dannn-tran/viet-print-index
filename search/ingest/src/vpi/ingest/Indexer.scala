package vpi.ingest

import cats.effect.IO
import cats.syntax.all.*
import doobie.*
import doobie.implicits.*
import fs2.Stream
import io.circe.parser.decode
import java.nio.file.{Files, Path, Paths}
import scala.jdk.CollectionConverters.*
import vpi.db.{Db, Normalize, Schema}

object Indexer:

  def insertPage(imageUri: String, text: String, textNorm: String): ConnectionIO[Unit] =
    for
      _ <- sql"""INSERT OR IGNORE INTO pages(image_uri, text, text_norm) VALUES($imageUri, $text, $textNorm)""".update.run
      _ <- sql"""INSERT OR IGNORE INTO pages_fts(image_uri, text_norm) VALUES($imageUri, $textNorm)""".update.run
    yield ()

  def parseGcv(content: String): Option[(String, String)] =
    decode[GcvResponse](content).toOption.flatMap(extractPage)

  def indexAll(
    dbPath: String,
    ocrBaseDir: String,
    onProgress: (Int, Int, String) => IO[Unit] = (_, _, _) => IO.unit,
  ): IO[Unit] =
    val xa       = Db.transactor(dbPath)
    val basePath = Paths.get(ocrBaseDir)
    Schema.createTables.transact(xa) >>
      IO.blocking(listJsonFiles(basePath)).flatMap { files =>
        val total = files.length
        Stream.emits(files.zipWithIndex)
          .covary[IO]
          .evalMap { case (file, idx) =>
            val filePath = basePath.relativize(file).toString
            IO.blocking(Files.readAllBytes(file)).flatMap { bytes =>
              val insert = parseGcv(new String(bytes, "UTF-8")) match
                case Some((uri, text)) => Some(insertPage(uri, text, Normalize.normalize(text)))
                case None              => None
              onProgress(idx + 1, total, filePath).as(insert)
            }
          }
          .collect { case Some(op) => op }
          .chunkN(500)
          .evalMap(chunk => chunk.toList.sequence_.transact(xa))
          .compile
          .drain
      }

  private def listJsonFiles(base: Path): List[Path] =
    Files.walk(base)
      .filter(p => Files.isRegularFile(p) && p.toString.endsWith(".json"))
      .iterator()
      .asScala
      .toList
      .sorted
