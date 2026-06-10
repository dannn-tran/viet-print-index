package vpi.cli

import cats.effect.IO
import com.google.cloud.storage.StorageOptions
import java.nio.file.{Files, Path, Paths}

object Browse:
  private lazy val storage = StorageOptions.getDefaultInstance.getService

  def fetch(imageUri: String, cacheDir: Path): IO[Path] =
    IO.blocking {
      val stripped = imageUri.stripPrefix("gs://")
      val slashIdx = stripped.indexOf('/')
      val bucket   = stripped.substring(0, slashIdx)
      val blobPath = stripped.substring(slashIdx + 1)
      val local    = cacheDir.resolve(bucket).resolve(blobPath)
      if !Files.exists(local) then
        Files.createDirectories(local.getParent)
        val blob = storage.get(bucket, blobPath)
        if blob == null then throw new NoSuchElementException(s"Not found in GCS: $imageUri")
        Files.write(local, blob.getContent())
      local
    }

  def open(path: Path): IO[Unit] =
    IO.blocking {
      val os  = System.getProperty("os.name").toLowerCase
      val cmd = if os.contains("mac") then "open" else "xdg-open"
      ProcessBuilder(cmd, path.toString).start()
    }.void
