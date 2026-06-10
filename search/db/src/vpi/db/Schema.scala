package vpi.db

import cats.syntax.all.*
import doobie.*
import doobie.implicits.*

object Schema:
  val createTables: ConnectionIO[Unit] =
    for
      _ <- sql"""
        CREATE TABLE IF NOT EXISTS pages (
          image_uri      TEXT NOT NULL PRIMARY KEY,
          text           TEXT NOT NULL,
          text_norm      TEXT NOT NULL,
          publication_id TEXT
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
      _ <- _addColumnIfMissing("pages", "publication_id", "TEXT")
    yield ()

  // SQLite has no ADD COLUMN IF NOT EXISTS; probe via PRAGMA instead
  private def _addColumnIfMissing(table: String, col: String, colType: String): ConnectionIO[Unit] =
    Fragment.const(s"PRAGMA table_info($table)")
      .query[(Int, String, String, Int, Option[String], Int)]
      .to[List]
      .flatMap { cols =>
        if cols.exists(_._2 == col) then ().pure[ConnectionIO]
        else Fragment.const(s"ALTER TABLE $table ADD COLUMN $col $colType").update.run.void
      }
