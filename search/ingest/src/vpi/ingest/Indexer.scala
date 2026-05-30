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

  def insertPage(filePath: String, text: String, textNorm: String): ConnectionIO[Unit] =
    for
      _ <- sql"""
        INSERT OR IGNORE INTO pages(file_path, text, text_norm)
        VALUES($filePath, $text, $textNorm)
      """.update.run
      _ <- sql"""
        INSERT OR IGNORE INTO pages_fts(file_path, text_norm)
        VALUES($filePath, $textNorm)
      """.update.run
    yield ()

  def parseGcv(content: String): Either[io.circe.Error, String] =
    decode[GcvResponse](content).map(_.fullTextAnnotation.text)

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
                case Right(text) => Some(insertPage(filePath, text, Normalize.normalize(text)))
                case Left(_)     => None
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
