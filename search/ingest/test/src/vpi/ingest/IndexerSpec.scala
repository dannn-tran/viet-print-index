package vpi.ingest

import cats.effect.IO
import cats.effect.Resource
import doobie.*
import doobie.implicits.*
import java.nio.file.Files
import vpi.db.{Db, Schema}

class IndexerSpec extends munit.CatsEffectSuite:

  val tempDb = ResourceFunFixture(
    Resource.make(IO.blocking(Files.createTempFile("vpi-ingest-test", ".db")))(p =>
      IO.blocking(Files.deleteIfExists(p)).void
    )
  )

  tempDb.test("parseGcv extracts fullTextAnnotation.text") { _ =>
    val json = scala.io.Source.fromResource("sample-gcv.json").mkString
    IO {
      Indexer.parseGcv(json) match
        case Right(text) => assert(text.contains("Hội nghị Yalta"))
        case Left(err)   => fail(s"Decode failed: $err")
    }
  }

  tempDb.test("insertPage round-trips to pages table") { dbPath =>
    val xa = Db.transactor(dbPath.toString)
    for
      _ <- Schema.createTables.transact(xa)
      _ <- Indexer.insertPage("105/000.json", "Hội nghị Yalta", "hoi nghi yalta").transact(xa)
      rows <- sql"SELECT file_path, text_norm FROM pages"
                .query[(String, String)]
                .to[List]
                .transact(xa)
    yield
      assertEquals(rows.length, 1)
      assertEquals(rows.head._1, "105/000.json")
      assertEquals(rows.head._2, "hoi nghi yalta")
  }

  tempDb.test("insertPage is idempotent") { dbPath =>
    val xa = Db.transactor(dbPath.toString)
    for
      _ <- Schema.createTables.transact(xa)
      _ <- Indexer.insertPage("105/000.json", "text", "text").transact(xa)
      _ <- Indexer.insertPage("105/000.json", "text", "text").transact(xa)
      count <- sql"SELECT COUNT(*) FROM pages".query[Int].unique.transact(xa)
    yield assertEquals(count, 1)
  }
