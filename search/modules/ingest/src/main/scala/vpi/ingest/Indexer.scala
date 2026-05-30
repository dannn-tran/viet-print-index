package vpi.ingest

import cats.effect.IO
import cats.syntax.all.*
import doobie.*
import doobie.implicits.*
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

  def indexAll(dbPath: String, ocrBaseDir: String): IO[Unit] =
    val xa       = Db.transactor(dbPath)
    val basePath = Paths.get(ocrBaseDir)
    for
      _     <- Schema.createTables.transact(xa)
      files <- IO.blocking(listJsonFiles(basePath))
      inserts <- files.traverse { file =>
        IO.blocking(Files.readAllBytes(file)).map { bytes =>
          parseGcv(new String(bytes, "UTF-8")) match
            case Right(text) =>
              val filePath = basePath.relativize(file).toString
              Some(insertPage(filePath, text, Normalize.normalize(text)))
            case Left(_) => None
        }
      }
      _ <- inserts.flatten.sequence_.transact(xa)
    yield ()

  private def listJsonFiles(base: Path): List[Path] =
    Files.walk(base)
      .filter(p => Files.isRegularFile(p) && p.toString.endsWith(".json"))
      .iterator()
      .asScala
      .toList
      .sorted
