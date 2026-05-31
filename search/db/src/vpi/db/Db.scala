package vpi.db

import cats.effect.{IO, Resource}
import doobie.*
import java.sql.DriverManager

object Db:
  def transactor(dbPath: String): Resource[IO, Transactor[IO]] =
    Resource
      .make(IO.blocking(DriverManager.getConnection(s"jdbc:sqlite:$dbPath")))(c =>
        IO.blocking(c.close())
      )
      .map(conn => Transactor.fromConnection[IO](conn, logHandler = None))
