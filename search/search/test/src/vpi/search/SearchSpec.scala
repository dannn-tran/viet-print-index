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

  private def setup(dbPath: String, pages: (String, String)*): Resource[IO, Transactor[IO]] =
    Db.transactor(dbPath).evalTap { xa =>
      Schema.createTables.transact(xa) >>
        pages.toList.traverse_(p => insertPage(p._1, p._2).transact(xa))
    }

  tempDb.test("finds page containing query term") { dbPath =>
    val uri = "gs://vie-doc/thanh-nghi/images/105/000.png"
    setup(dbPath.toString, uri -> "Hội nghị Yalta bàn về tình hình").use { xa =>
      Search.search("hội nghị").transact(xa).map { results =>
        assertEquals(results.length, 1)
        assertEquals(results.head.imageUri, uri)
      }
    }
  }

  tempDb.test("diacritic normalization: search without tones finds original") { dbPath =>
    setup(dbPath.toString, "gs://vie-doc/images/105/000.png" -> "Hội nghị Yalta").use { xa =>
      Search.search("hoi nghi").transact(xa).map(results => assertEquals(results.length, 1))
    }
  }

  tempDb.test("trigram substring match") { dbPath =>
    setup(dbPath.toString, "gs://vie-doc/images/105/000.png" -> "Hội nghị Yalta").use { xa =>
      Search.search("nghi").transact(xa).map(results => assertEquals(results.length, 1))
    }
  }

  tempDb.test("absent term returns empty list") { dbPath =>
    setup(dbPath.toString, "gs://vie-doc/images/105/000.png" -> "Hội nghị Yalta").use { xa =>
      Search.search("xyznotfound").transact(xa).map(results => assertEquals(results, Nil))
    }
  }

  tempDb.test("returns only pages containing query, not all pages") { dbPath =>
    setup(
      dbPath.toString,
      "gs://vie-doc/images/105/000.png" -> "Hội nghị Yalta",
      "gs://vie-doc/images/105/001.png" -> "Tình hình kinh tế",
      "gs://vie-doc/images/105/002.png" -> "Hội nghị Paris",
    ).use { xa =>
      Search.search("hội nghị").transact(xa).map { results =>
        assertEquals(results.length, 2)
        assert(results.map(_.imageUri).contains("gs://vie-doc/images/105/000.png"))
        assert(results.map(_.imageUri).contains("gs://vie-doc/images/105/002.png"))
      }
    }
  }

  tempDb.test("contextPages: returns windowed pages around target") { dbPath =>
    val pages = List(
      "ngay-nay/images/001/000.png" -> "page zero",
      "ngay-nay/images/001/001.png" -> "page one",
      "ngay-nay/images/001/002.png" -> "page two",
      "ngay-nay/images/001/003.png" -> "page three",
      "ngay-nay/images/001/004.png" -> "page four",
    )
    setup(dbPath.toString, pages*).use { xa =>
      Search.contextPages("ngay-nay/images/001/002.png", 1).transact(xa).map { results =>
        assertEquals(results.map(_.imageUri), List(
          "ngay-nay/images/001/001.png",
          "ngay-nay/images/001/002.png",
          "ngay-nay/images/001/003.png",
        ))
      }
    }
  }

  tempDb.test("contextPages: URL-encoded percent signs don't break LIKE pattern") { dbPath =>
    val pages = List(
      "ngay-nay/images/Ngay%20Nay%20091_91/000.png" -> "first",
      "ngay-nay/images/Ngay%20Nay%20091_91/001.png" -> "second",
      "ngay-nay/images/Ngay%20Nay%20091_91/002.png" -> "third",
      "ngay-nay/images/other_issue/000.png"          -> "other",
    )
    setup(dbPath.toString, pages*).use { xa =>
      Search.contextPages("ngay-nay/images/Ngay%20Nay%20091_91/001.png", 2).transact(xa).map { results =>
        assertEquals(results.map(_.imageUri), List(
          "ngay-nay/images/Ngay%20Nay%20091_91/000.png",
          "ngay-nay/images/Ngay%20Nay%20091_91/001.png",
          "ngay-nay/images/Ngay%20Nay%20091_91/002.png",
        ))
      }
    }
  }
