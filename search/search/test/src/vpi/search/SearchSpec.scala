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

  private def insertPage(filePath: String, text: String): ConnectionIO[Unit] =
    val textNorm = Normalize.normalize(text)
    for
      _ <- sql"INSERT OR IGNORE INTO pages(file_path, text, text_norm) VALUES($filePath, $text, $textNorm)".update.run
      _ <- sql"INSERT OR IGNORE INTO pages_fts(file_path, text_norm) VALUES($filePath, $textNorm)".update.run
    yield ()

  private def setup(dbPath: String, pages: (String, String)*): IO[Transactor[IO]] =
    val xa = Db.transactor(dbPath)
    for
      _ <- Schema.createTables.transact(xa)
      _ <- pages.toList.foldLeft(IO.unit)((acc, p) => acc >> insertPage(p._1, p._2).transact(xa))
    yield xa

  tempDb.test("finds page containing query term") { dbPath =>
    for
      xa      <- setup(dbPath.toString, "105/000.json" -> "Hội nghị Yalta bàn về tình hình")
      results <- Search.search("hội nghị").transact(xa)
    yield
      assertEquals(results.length, 1)
      assertEquals(results.head.filePath, "105/000.json")
  }

  tempDb.test("diacritic normalization: search without tones finds original") { dbPath =>
    for
      xa      <- setup(dbPath.toString, "105/000.json" -> "Hội nghị Yalta")
      results <- Search.search("hoi nghi").transact(xa)
    yield assertEquals(results.length, 1)
  }

  tempDb.test("trigram substring match") { dbPath =>
    for
      xa      <- setup(dbPath.toString, "105/000.json" -> "Hội nghị Yalta")
      results <- Search.search("nghi").transact(xa)
    yield assertEquals(results.length, 1)
  }

  tempDb.test("absent term returns empty list") { dbPath =>
    for
      xa      <- setup(dbPath.toString, "105/000.json" -> "Hội nghị Yalta")
      results <- Search.search("xyznotfound").transact(xa)
    yield assertEquals(results, Nil)
  }

  tempDb.test("returns only pages containing query, not all pages") { dbPath =>
    for
      xa <- setup(
        dbPath.toString,
        "105/000.json" -> "Hội nghị Yalta",
        "105/001.json" -> "Tình hình kinh tế",
        "105/002.json" -> "Hội nghị Paris",
      )
      results <- Search.search("hội nghị").transact(xa)
    yield
      assertEquals(results.length, 2)
      assert(results.map(_.filePath).contains("105/000.json"))
      assert(results.map(_.filePath).contains("105/002.json"))
  }
