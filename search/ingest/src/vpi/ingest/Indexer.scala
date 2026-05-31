package vpi.ingest

import cats.effect.{IO, Ref}
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
    downloadConcurrency: Int = 1,
    onProgress: (Int, Int, String, Int) => IO[Unit] = (_, _, _, _) => IO.unit,
  ): IO[Unit] =
    Db.transactor(dbPath).use { xa =>
      Schema.createTables.transact(xa) >>
        source.list.flatMap { allItems =>
          source.filterPending(allItems, xa).flatMap { items =>
            val total   = items.length
            val skipped = allItems.length - total
            (if skipped > 0 then IO.println(s"$total items pending, $skipped already done") else IO.unit) >>
              Ref.of[IO, Int](0).flatMap { counter =>
                Stream.emits(items)
                  .covary[IO]
                  .parEvalMapUnordered(downloadConcurrency) { item =>
                    source.read(item).flatMap { content =>
                      IO.blocking {
                        format.parse(content).map { case (uri, text) => (uri, text, Normalize.normalize(text)) }
                      }.map(pages => (item, pages))
                    }
                  }
                  .evalMap { case (item, pages) =>
                    val tx = pages.traverse_ { case (uri, text, textNorm) =>
                               insertPage(uri, text, textNorm)
                             } >> source.onCommit(item)
                    tx.transact(xa) >>
                      counter.updateAndGet(_ + 1).flatMap { n =>
                        onProgress(n, total, source.itemName(item), pages.length)
                      }
                  }
                  .compile.drain
              }
          }
        }
    }
