package vpi.cli

import cats.effect.{ExitCode, IO}
import cats.syntax.all.*
import com.monovore.decline.*
import com.monovore.decline.effect.*
import vpi.ingest.Indexer

object Main extends CommandIOApp(
  name    = "vpi-ingest",
  header  = "Index Thanh Nghi OCR JSON files into a SQLite FTS5 database",
  version = "0.1.0",
):
  override def main: Opts[IO[ExitCode]] =
    val dbOpt =
      Opts.option[String]("db", help = "Path to the output SQLite database file", metavar = "file")
    val ocrDirOpt =
      Opts.option[String]("ocr-dir", help = "Path to the OCR base directory (contains {issue}/{page}.json)", metavar = "dir")

    (dbOpt, ocrDirOpt).mapN { (db, ocrDir) =>
      def onProgress(current: Int, total: Int, filePath: String): IO[Unit] =
        IO.println(f"[$current%5d/$total] $filePath")

      Indexer.indexAll(db, ocrDir, onProgress).flatMap { _ =>
        IO.println("Done.").as(ExitCode.Success)
      }
    }
