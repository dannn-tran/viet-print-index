package vpi.ingest

import cats.effect.IO
import cats.syntax.all.*
import com.google.cloud.storage.{Storage, StorageOptions}
import doobie.*
import doobie.implicits.*
import fs2.Stream
import io.circe.parser.decode
import scala.jdk.CollectionConverters.*
import vpi.db.{Db, Normalize, Schema}

object GcsIndexer:

  def indexAll(
    dbPath: String,
    bucket: String,
    prefix: String,
    onProgress: (Int, Int, String, Int) => IO[Unit] = (_, _, _, _) => IO.unit,
  ): IO[Unit] =
    val xa      = Db.transactor(dbPath)
    val storage = StorageOptions.getDefaultInstance.getService
    Schema.createTables.transact(xa) >>
      IO.blocking(listBlobs(storage, bucket, prefix)).flatMap { allBlobs =>
        sql"SELECT blob_name FROM gcs_blobs"
          .query[String].to[Set].transact(xa).flatMap { done =>
            val pending = allBlobs.filterNot(b => done.contains(b.getName))
            val total   = pending.length
            val skipped = allBlobs.length - total
            IO.println(s"$total blobs pending, $skipped already done") >>
              Stream.emits(pending.zipWithIndex)
                .covary[IO]
                .evalMap { case (blob, idx) =>
                  IO.blocking(blob.getContent()).flatMap { bytes =>
                    val pages = parseBatch(new String(bytes, "UTF-8"))
                    val tx    = pages.traverse_ { case (uri, text) =>
                                  Indexer.insertPage(uri, text, Normalize.normalize(text))
                                } >> checkpointBlob(blob.getName)
                    tx.transact(xa) >> onProgress(idx + 1, total, blob.getName, pages.length)
                  }
                }
                .compile.drain
          }
      }

  private def checkpointBlob(blobName: String): ConnectionIO[Unit] =
    sql"""INSERT OR IGNORE INTO gcs_blobs(blob_name, indexed_at)
          VALUES($blobName, datetime('now'))""".update.run.void

  private def listBlobs(storage: Storage, bucket: String, prefix: String): List[com.google.cloud.storage.Blob] =
    storage.list(bucket, Storage.BlobListOption.prefix(prefix))
      .iterateAll.asScala
      .filter(_.getName.endsWith(".json"))
      .toList
      .sortBy(_.getName)

  private def parseBatch(content: String): List[(String, String)] =
    decode[GcvBatch](content) match
      case Left(_)      => Nil
      case Right(batch) => batch.responses.flatMap(extractPage)
