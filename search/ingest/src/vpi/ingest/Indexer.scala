package vpi.ingest

import cats.effect.IO
import cats.syntax.all.*
import doobie.*
import doobie.implicits.*
import fs2.Stream
import vpi.db.{Db, Normalize, Schema}

object Indexer:

  def insertPage(imageUri: String, text: String, textNorm: String): ConnectionIO[Unit] =
    for
      _ <- sql"""INSERT OR IGNORE INTO pages(image_uri, text, text_norm) VALUES($imageUri, $text, $textNorm)""".update.run
      _ <- sql"""INSERT OR IGNORE INTO pages_fts(image_uri, text_norm) VALUES($imageUri, $textNorm)""".update.run
    yield ()

  def indexAll[Item](
    dbPath: String,
    source: OcrSource[Item],
    format: OcrFormat,
    onProgress: (Int, Int, String, Int) => IO[Unit] = (_, _, _, _) => IO.unit,
  ): IO[Unit] =
    val xa = Db.transactor(dbPath)
    Schema.createTables.transact(xa) >>
      source.list.flatMap { allItems =>
        source.filterPending(allItems, xa).flatMap { items =>
          val total   = items.length
          val skipped = allItems.length - total
          (if skipped > 0 then IO.println(s"$total items pending, $skipped already done") else IO.unit) >>
            Stream.emits(items.zipWithIndex)
              .covary[IO]
              .evalMap { case (item, idx) =>
                source.read(item).flatMap { content =>
                  val pages = format.parse(content)
                  val tx    = pages.traverse_ { case (uri, text) =>
                                insertPage(uri, text, Normalize.normalize(text))
                              } >> source.onCommit(item)
                  tx.transact(xa) >> onProgress(idx + 1, total, source.itemName(item), pages.length)
                }
              }
              .compile.drain
        }
      }
