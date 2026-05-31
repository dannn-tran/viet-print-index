package vpi.cli

import cats.effect.{ExitCode, IO}
import cats.syntax.all.*
import com.monovore.decline.*
import com.monovore.decline.effect.*
import doobie.implicits.*
import vpi.db.Db
import vpi.ingest.{BatchedFormat, GcsSource, Indexer, LocalSource, OcrFormat, SingleFormat}
import vpi.search.Search

object Main extends CommandIOApp(
  name    = "vpi",
  header  = "Viet Print Index tools",
  version = "0.1.0",
):
  override def main: Opts[IO[ExitCode]] =
    indexCmd orElse searchCmd

  private val dbOpt =
    Opts.option[String]("db", help = "Path to SQLite database file", metavar = "file")

  private def formatOpt(default: OcrFormat): Opts[OcrFormat] =
    Opts.option[String]("format", help = "OCR output format: single or batched", metavar = "format")
      .orNone
      .map {
        case Some("batched") => BatchedFormat
        case Some("single")  => SingleFormat
        case _               => default
      }

  private val indexLocalCmd = Opts.subcommand("local", "Index from local filesystem") {
    val ocrDirOpt = Opts.option[String]("ocr-dir", help = "OCR base directory", metavar = "dir")
    (dbOpt, ocrDirOpt, formatOpt(SingleFormat)).mapN { (db, ocrDir, format) =>
      def onProgress(c: Int, t: Int, name: String, pages: Int): IO[Unit] =
        IO.println(f"[$c%5d/$t] $name")
      Indexer.indexAll(db, LocalSource(ocrDir), format, onProgress) >>
        IO.println("Done.").as(ExitCode.Success)
    }
  }

  private val indexGcsCmd = Opts.subcommand("gcs", "Index from GCS bucket (resumable)") {
    val bucketOpt = Opts.option[String]("bucket", help = "GCS bucket name", metavar = "bucket")
    val prefixOpt = Opts.option[String]("prefix", help = "Blob prefix", metavar = "prefix")
    (dbOpt, bucketOpt, prefixOpt, formatOpt(BatchedFormat)).mapN { (db, bucket, prefix, format) =>
      def onProgress(c: Int, t: Int, name: String, pages: Int): IO[Unit] =
        IO.println(f"[$c%5d/$t] $name ($pages pages)")
      Indexer.indexAll(db, GcsSource(bucket, prefix), format, onProgress) >>
        IO.println("Done.").as(ExitCode.Success)
    }
  }

  private val indexCmd = Opts.subcommand("index", "Index OCR files into SQLite") {
    indexLocalCmd orElse indexGcsCmd
  }

  private val searchCmd = Opts.subcommand("search", "Interactively search the index") {
    dbOpt.map { db =>
      val xa = Db.transactor(db)
      IO.println("Enter query (Ctrl-D to exit)") >> repl(xa).as(ExitCode.Success)
    }
  }

  private def repl(xa: doobie.Transactor[IO]): IO[Unit] =
    IO.print("> ") >> IO.readLine.flatMap {
      case null     => IO.println("")
      case ""       => repl(xa)
      case "/clear" => IO.print("[H[2J") >> repl(xa)
      case input    =>
        Search.search(input.trim).transact(xa).flatMap { results =>
          results.traverse_(r => IO.println(s"${r.imageUri}\t${r.snippet}")) >>
          IO.println(s"(${results.size} results)") >>
          repl(xa)
        }
    }
