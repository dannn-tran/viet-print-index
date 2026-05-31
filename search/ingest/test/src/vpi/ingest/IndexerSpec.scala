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

  tempDb.test("SingleFormat.parse extracts image URI and text") { _ =>
    val json = scala.io.Source.fromResource("sample-gcv.json").mkString
    IO {
      SingleFormat.parse(json) match
        case (uri, text) :: Nil =>
          assert(uri.contains("105/000.png"))
          assert(text.contains("Hội nghị Yalta"))
        case other => fail(s"Expected exactly one result, got: $other")
    }
  }

  tempDb.test("insertPage round-trips to pages table") { dbPath =>
    val xa  = Db.transactor(dbPath.toString)
    val uri = "gs://vie-doc/thanh-nghi/images/105/000.png"
    for
      _ <- Schema.createTables.transact(xa)
      _ <- Indexer.insertPage(uri, "Hội nghị Yalta", "hoi nghi yalta").transact(xa)
      rows <- sql"SELECT image_uri, text_norm FROM pages"
                .query[(String, String)]
                .to[List]
                .transact(xa)
    yield
      assertEquals(rows.length, 1)
      assertEquals(rows.head._1, uri)
      assertEquals(rows.head._2, "hoi nghi yalta")
  }

  tempDb.test("insertPage is idempotent") { dbPath =>
    val xa  = Db.transactor(dbPath.toString)
    val uri = "gs://vie-doc/thanh-nghi/images/105/000.png"
    for
      _ <- Schema.createTables.transact(xa)
      _ <- Indexer.insertPage(uri, "text", "text").transact(xa)
      _ <- Indexer.insertPage(uri, "text", "text").transact(xa)
      count <- sql"SELECT COUNT(*) FROM pages".query[Int].unique.transact(xa)
    yield assertEquals(count, 1)
  }
