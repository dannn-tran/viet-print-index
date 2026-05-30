package vpi.db

import cats.effect.IO
import doobie.*

object Db:
  def transactor(dbPath: String): Transactor[IO] =
    Transactor.fromDriverManager[IO](
      driver = "org.sqlite.JDBC",
      url    = s"jdbc:sqlite:$dbPath",
      logHandler = None,
    )
