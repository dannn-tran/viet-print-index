package vpi.db

import doobie.*
import doobie.implicits.*

object Schema:
  val createTables: ConnectionIO[Unit] =
    for
      _ <- sql"""
        CREATE TABLE IF NOT EXISTS pages (
          image_uri TEXT NOT NULL PRIMARY KEY,
          text      TEXT NOT NULL,
          text_norm TEXT NOT NULL
        )
      """.update.run
      _ <- sql"""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
          image_uri UNINDEXED,
          text_norm,
          tokenize='trigram'
        )
      """.update.run
      _ <- sql"""
        CREATE TABLE IF NOT EXISTS gcs_blobs (
          blob_name  TEXT NOT NULL PRIMARY KEY,
          indexed_at TEXT NOT NULL
        )
      """.update.run
    yield ()
