package vpi.db

import doobie.*
import doobie.implicits.*

object Schema:
  val createTables: ConnectionIO[Unit] =
    for
      _ <- sql"""
        CREATE TABLE IF NOT EXISTS pages (
          file_path TEXT NOT NULL PRIMARY KEY,
          text      TEXT NOT NULL,
          text_norm TEXT NOT NULL
        )
      """.update.run
      _ <- sql"""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
          file_path UNINDEXED,
          text_norm,
          tokenize='trigram'
        )
      """.update.run
    yield ()
