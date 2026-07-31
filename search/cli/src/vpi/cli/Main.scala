package vpi.cli

import cats.effect.{ExitCode, IO}
import cats.syntax.all.*
import com.monovore.decline.*
import com.monovore.decline.effect.*
import doobie.implicits.*
import java.nio.file.Paths
import vpi.db.Db
import vpi.ingest.{BatchedFormat, GcsSource, Indexer, LocalSource, OcrFormat, SingleFormat}
import vpi.search.{PageResult, Search, SearchResult}

object Main extends CommandIOApp(
  name    = "vpi",
  header  = "Viet Print Index tools",
  version = "0.1.0",
):
  override def main: Opts[IO[ExitCode]] =
    indexCmd orElse searchCmd orElse getCmd orElse contextCmd orElse viewCmd

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

  private val jsonOpt = Opts.flag("json", help = "Output results as JSON").orFalse

  // ---- index ---------------------------------------------------------------

  private val indexLocalCmd = Opts.subcommand("local", "Index from local filesystem") {
    val ocrDirOpt = Opts.option[String]("ocr-dir", help = "OCR base directory", metavar = "dir")
    (dbOpt, ocrDirOpt, formatOpt(SingleFormat)).mapN { (db, ocrDir, format) =>
      def onProgress(c: Int, t: Int, name: String, pages: Int): IO[Unit] =
        IO.println(f"[$c%5d/$t] $name")
      Indexer.indexAll(db, LocalSource(ocrDir), format, onProgress = onProgress) >>
        IO.println("Done.").as(ExitCode.Success)
    }
  }

  private val indexGcsCmd = Opts.subcommand("gcs", "Index from GCS bucket (resumable)") {
    val bucketOpt = Opts.option[String]("bucket", help = "GCS bucket name", metavar = "bucket")
    val prefixOpt = Opts.option[String]("prefix", help = "Blob prefix", metavar = "prefix")
    val concurrencyOpt =
      Opts.option[Int]("download-concurrency", help = "Number of blobs to download concurrently", metavar = "N")
        .orNone.map(_.getOrElse(1))
    (dbOpt, bucketOpt, prefixOpt, formatOpt(BatchedFormat), concurrencyOpt).mapN { (db, bucket, prefix, format, concurrency) =>
      def onProgress(c: Int, t: Int, name: String, pages: Int): IO[Unit] =
        IO.println(f"[$c%5d/$t] $name ($pages pages)")
      Indexer.indexAll(db, GcsSource(bucket, prefix), format, concurrency, onProgress) >>
        IO.println("Done.").as(ExitCode.Success)
    }
  }

  private val indexCmd = Opts.subcommand("index", "Index OCR files into SQLite") {
    indexLocalCmd orElse indexGcsCmd
  }

  // ---- search --------------------------------------------------------------

  private val searchCmd = Opts.subcommand("search", "Search the index") {
    val pubOpt        = Opts.option[String]("pub", help = "Filter by publication id", metavar = "id").orNone
    val excludePubOpt = Opts.option[String]("exclude-pub", help = "Exclude publication id from results", metavar = "id").orNone
    val limitOpt      = Opts.option[Int]("limit", help = "Max results (default 20)", metavar = "N").orNone.map(_.getOrElse(20))
    val offsetOpt     = Opts.option[Int]("offset", help = "Result offset", metavar = "N").orNone.map(_.getOrElse(0))
    val snippetLenOpt = Opts.option[Int]("snippet-len", help = "Snippet token length (default 64)", metavar = "N").orNone.map(_.getOrElse(64))
    val queryArg      = Opts.argument[String]("query").orNone
    (dbOpt, pubOpt, excludePubOpt, limitOpt, offsetOpt, snippetLenOpt, jsonOpt, queryArg).mapN {
      (db, pub, excludePub, limit, offset, snippetLen, asJson, query) =>
      Db.transactor(db).use { xa =>
        query match
          case Some(q) =>
            Search.search(q, pub, excludePub, limit, offset, snippetLen).transact(xa).flatMap { results =>
              if asJson then IO.println(resultsToJson(results))
              else results.traverse_(r => IO.println(s"${r.imageUri}\t${r.snippet}")) >>
                   IO.println(s"(${results.size} results)")
            }.as(ExitCode.Success)
          case None =>
            IO.println("Enter query (Ctrl-D to exit)") >> repl(xa, pub, excludePub, limit, snippetLen).as(ExitCode.Success)
      }
    }
  }

  private def repl(xa: doobie.Transactor[IO], pub: Option[String], excludePub: Option[String], limit: Int, snippetLen: Int): IO[Unit] =
    IO.print("> ") >> IO.readLine.flatMap {
      case null     => IO.println("")
      case ""       => repl(xa, pub, excludePub, limit, snippetLen)
      case "/clear" => IO.print("[H[2J") >> repl(xa, pub, excludePub, limit, snippetLen)
      case input    =>
        Search.search(input.trim, pub, excludePub, limit, 0, snippetLen).transact(xa).flatMap { results =>
          val indexed = results.zipWithIndex
          indexed.traverse_ { case (r, i) => IO.println(s"  ${i + 1}  ${r.imageUri}\t${r.snippet}") } >>
          IO.println(s"(${results.size} results)") >>
          replWithResults(xa, pub, excludePub, limit, snippetLen, results)
        }
    }

  private def replWithResults(xa: doobie.Transactor[IO], pub: Option[String], excludePub: Option[String], limit: Int, snippetLen: Int, last: List[SearchResult]): IO[Unit] =
    IO.print("> ") >> IO.readLine.flatMap {
      case null            => IO.println("")
      case ""              => replWithResults(xa, pub, excludePub, limit, snippetLen, last)
      case s"/clear"       => IO.print("[H[2J") >> repl(xa, pub, excludePub, limit, snippetLen)
      case s":${n}"        =>
        n.toIntOption.flatMap(i => last.lift(i - 1)) match
          case Some(r) =>
            val cacheDir = Paths.get(System.getProperty("user.home")).resolve(".vpi").resolve("cache")
            Browse.fetch(r.imageUri, cacheDir).flatMap(Browse.open) >>
              replWithResults(xa, pub, excludePub, limit, snippetLen, last)
          case None =>
            IO.println(s"No result $n") >> replWithResults(xa, pub, excludePub, limit, snippetLen, last)
      case input           =>
        Search.search(input.trim, pub, excludePub, limit, 0, snippetLen).transact(xa).flatMap { results =>
          val indexed = results.zipWithIndex
          indexed.traverse_ { case (r, i) => IO.println(s"  ${i + 1}  ${r.imageUri}\t${r.snippet}") } >>
          IO.println(s"(${results.size} results)") >>
          replWithResults(xa, pub, excludePub, limit, snippetLen, results)
        }
    }

  // ---- get -----------------------------------------------------------------

  private val getCmd = Opts.subcommand("get", "Retrieve full text for a page by image URI") {
    val uriOpt = Opts.option[String]("uri", help = "Image URI (gs://...)", metavar = "uri")
    (dbOpt, uriOpt, jsonOpt).mapN { (db, uri, asJson) =>
      Db.transactor(db).use { xa =>
        Search.getPage(uri).transact(xa).flatMap {
          case None    => IO.println(s"Not found: $uri").as(ExitCode.Error)
          case Some(p) =>
            if asJson then IO.println(pageToJson(p)).as(ExitCode.Success)
            else IO.println(p.text).as(ExitCode.Success)
        }
      }
    }
  }

  // ---- context -------------------------------------------------------------

  private val contextCmd = Opts.subcommand("context", "Retrieve surrounding pages for a given image URI") {
    val uriOpt    = Opts.option[String]("uri", help = "Image URI (gs://...)", metavar = "uri")
    val windowOpt = Opts.option[Int]("window", help = "Pages before/after (default 2)", metavar = "N")
      .orNone.map(_.getOrElse(2))
    (dbOpt, uriOpt, windowOpt, jsonOpt).mapN { (db, uri, window, asJson) =>
      Db.transactor(db).use { xa =>
        Search.contextPages(uri, window).transact(xa).flatMap { pages =>
          if asJson then IO.println(pagesToJson(pages)).as(ExitCode.Success)
          else pages.traverse_(p => IO.println(s"--- ${p.imageUri} ---\n${p.text}")).as(ExitCode.Success)
        }
      }
    }
  }

  // ---- view ----------------------------------------------------------------

  private val viewCmd = Opts.subcommand("view", "Fetch a page image from GCS and open it") {
    val uriOpt      = Opts.option[String]("uri", help = "Image URI (gs://...)", metavar = "uri")
    val cacheDirOpt =
      Opts.option[String]("cache-dir", help = "Local cache directory", metavar = "dir")
        .orNone.map(d => Paths.get(d.getOrElse(System.getProperty("user.home") + "/.vpi/cache")))
    (uriOpt, cacheDirOpt).mapN { (uri, cacheDir) =>
      Browse.fetch(uri, cacheDir).flatMap(Browse.open).as(ExitCode.Success)
    }
  }

  // ---- JSON helpers --------------------------------------------------------

  private def escape(s: String) = s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")

  private def resultsToJson(rs: List[SearchResult]): String =
    rs.map(r =>
      s"""{"imageUri":"${escape(r.imageUri)}","snippet":"${escape(r.snippet)}","publicationId":${r.publicationId.fold("null")(p => s"\"${escape(p)}\"")}"""
       + "}"
    ).mkString("[", ",", "]")

  private def pageToJson(p: PageResult): String =
    s"""{"imageUri":"${escape(p.imageUri)}","text":"${escape(p.text)}","publicationId":${p.publicationId.fold("null")(id => s"\"${escape(id)}\"")}"""
     + "}"

  private def pagesToJson(ps: List[PageResult]): String =
    ps.map(pageToJson).mkString("[", ",", "]")
