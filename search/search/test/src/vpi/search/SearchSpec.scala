package vpi.search

import cats.effect.IO
import cats.effect.Resource
import cats.syntax.all.*
import doobie.*
import doobie.implicits.*
import java.nio.file.Files
import vpi.db.{Db, Normalize, Schema}

class SearchSpec extends munit.CatsEffectSuite:

  val tempDb = ResourceFunFixture(
    Resource.make(IO.blocking(Files.createTempFile("vpi-search-test", ".db")))(p =>
      IO.blocking(Files.deleteIfExists(p)).void
    )
  )

  private def insertPage(imageUri: String, text: String): ConnectionIO[Unit] =
    val textNorm = Normalize.normalize(text)
    for
      _ <- sql"INSERT OR IGNORE INTO pages(image_uri, text, text_norm) VALUES($imageUri, $text, $textNorm)".update.run
      _ <- sql"INSERT OR IGNORE INTO pages_fts(image_uri, text_norm) VALUES($imageUri, $textNorm)".update.run
    yield ()

  private def setup(dbPath: String, pages: (String, String)*): IO[Transactor[IO]] =
    val xa = Db.transactor(dbPath)
    for
      _ <- Schema.createTables.transact(xa)
      _ <- pages.toList.foldLeft(IO.unit)((acc, p) => acc >> insertPage(p._1, p._2).transact(xa))
    yield xa

  tempDb.test("finds page containing query term") { dbPath =>
    val uri = "gs://vie-doc/thanh-nghi/images/105/000.png"
    for
      xa      <- setup(dbPath.toString, uri -> "Hội nghị Yalta bàn về tình hình")
      results <- Search.search("hội nghị").transact(xa)
    yield
      assertEquals(results.length, 1)
      assertEquals(results.head.imageUri, uri)
  }

  tempDb.test("diacritic normalization: search without tones finds original") { dbPath =>
    for
      xa      <- setup(dbPath.toString, "gs://vie-doc/images/105/000.png" -> "Hội nghị Yalta")
      results <- Search.search("hoi nghi").transact(xa)
    yield assertEquals(results.length, 1)
  }

  tempDb.test("trigram substring match") { dbPath =>
    for
      xa      <- setup(dbPath.toString, "gs://vie-doc/images/105/000.png" -> "Hội nghị Yalta")
      results <- Search.search("nghi").transact(xa)
    yield assertEquals(results.length, 1)
  }

  tempDb.test("absent term returns empty list") { dbPath =>
    for
      xa      <- setup(dbPath.toString, "gs://vie-doc/images/105/000.png" -> "Hội nghị Yalta")
      results <- Search.search("xyznotfound").transact(xa)
    yield assertEquals(results, Nil)
  }

  tempDb.test("returns only pages containing query, not all pages") { dbPath =>
    for
      xa <- setup(
        dbPath.toString,
        "gs://vie-doc/images/105/000.png" -> "Hội nghị Yalta",
        "gs://vie-doc/images/105/001.png" -> "Tình hình kinh tế",
        "gs://vie-doc/images/105/002.png" -> "Hội nghị Paris",
      )
      results <- Search.search("hội nghị").transact(xa)
    yield
      assertEquals(results.length, 2)
      assert(results.map(_.imageUri).contains("gs://vie-doc/images/105/000.png"))
      assert(results.map(_.imageUri).contains("gs://vie-doc/images/105/002.png"))
  }
