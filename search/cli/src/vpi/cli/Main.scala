package vpi.cli

import cats.effect.{ExitCode, IO}
import cats.syntax.all.*
import com.monovore.decline.*
import com.monovore.decline.effect.*
import doobie.implicits.*
import vpi.db.Db
import vpi.ingest.{GcsIndexer, Indexer}
import vpi.search.Search

object Main extends CommandIOApp(
  name    = "vpi",
  header  = "Viet Print Index tools",
  version = "0.1.0",
):
  override def main: Opts[IO[ExitCode]] =
    val dbOpt =
      Opts.option[String]("db", help = "Path to SQLite database file", metavar = "file")

    val indexCmd = Opts.subcommand("index", "Index OCR JSON files into SQLite") {
      val ocrDirOpt =
        Opts.option[String]("ocr-dir", help = "OCR base directory ({issue}/{page}.json)", metavar = "dir")
      (dbOpt, ocrDirOpt).mapN { (db, ocrDir) =>
        def onProgress(current: Int, total: Int, filePath: String): IO[Unit] =
          IO.println(f"[$current%5d/$total] $filePath")
        Indexer.indexAll(db, ocrDir, onProgress) >> IO.println("Done.").as(ExitCode.Success)
      }
    }

    val searchCmd = Opts.subcommand("search", "Interactively search the index") {
      dbOpt.map { db =>
        val xa = Db.transactor(db)
        IO.println("Enter query (Ctrl-D to exit)") >> repl(xa).as(ExitCode.Success)
      }
    }

    val indexGcsCmd = Opts.subcommand("index-gcs", "Index OCR from GCS bucket into SQLite (resumable)") {
      val bucketOpt = Opts.option[String]("bucket", help = "GCS bucket name", metavar = "bucket")
      val prefixOpt = Opts.option[String]("prefix", help = "Blob prefix", metavar = "prefix")
      (dbOpt, bucketOpt, prefixOpt).mapN { (db, bucket, prefix) =>
        def onProgress(current: Int, total: Int, blobName: String, pages: Int): IO[Unit] =
          IO.println(f"[$current%5d/$total] $blobName ($pages pages)")
        GcsIndexer.indexAll(db, bucket, prefix, onProgress) >> IO.println("Done.").as(ExitCode.Success)
      }
    }

    indexCmd orElse indexGcsCmd orElse searchCmd

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
