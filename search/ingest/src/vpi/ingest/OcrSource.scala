package vpi.ingest

import cats.effect.IO
import cats.syntax.all.*
import com.google.cloud.storage.{Blob, Storage, StorageOptions}
import doobie.*
import doobie.implicits.*
import java.nio.file.{Files, Path, Paths}
import scala.jdk.CollectionConverters.*

trait OcrSource[Item]:
  def list: IO[List[Item]]
  def filterPending(items: List[Item], xa: Transactor[IO]): IO[List[Item]] = IO.pure(items)
  def read(item: Item): IO[String]
  def itemName(item: Item): String
  def onCommit(item: Item): ConnectionIO[Unit]

class LocalSource(basePath: Path) extends OcrSource[Path]:
  def list: IO[List[Path]] =
    IO.blocking(
      Files.walk(basePath)
        .filter(p => Files.isRegularFile(p) && p.toString.endsWith(".json"))
        .iterator.asScala.toList.sorted
    )
  def read(item: Path): IO[String] =
    IO.blocking(new String(Files.readAllBytes(item), "UTF-8"))
  def itemName(item: Path): String =
    basePath.relativize(item).toString
  def onCommit(item: Path): ConnectionIO[Unit] = ().pure[ConnectionIO]

object LocalSource:
  def apply(basePath: String): LocalSource = new LocalSource(Paths.get(basePath))

class GcsSource(bucket: String, prefix: String) extends OcrSource[Blob]:
  private val storage: Storage = StorageOptions.getDefaultInstance.getService

  def list: IO[List[Blob]] =
    IO.interruptible(
      storage.list(bucket, Storage.BlobListOption.prefix(prefix))
        .iterateAll.asScala
        .filter(_.getName.endsWith(".json"))
        .toList.sortBy(_.getName)
    )

  override def filterPending(items: List[Blob], xa: Transactor[IO]): IO[List[Blob]] =
    sql"SELECT blob_name FROM gcs_blobs".query[String].to[Set].transact(xa).map { done =>
      items.filterNot(b => done.contains(b.getName))
    }

  def read(item: Blob): IO[String] =
    IO.interruptible(new String(item.getContent(), "UTF-8"))

  def itemName(item: Blob): String = item.getName

  def onCommit(item: Blob): ConnectionIO[Unit] =
    sql"""INSERT OR IGNORE INTO gcs_blobs(blob_name, indexed_at)
          VALUES(${item.getName}, datetime('now'))""".update.run.void

object GcsSource:
  def apply(bucket: String, prefix: String): GcsSource = new GcsSource(bucket, prefix)
