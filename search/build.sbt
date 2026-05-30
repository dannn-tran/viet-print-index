ThisBuild / scalaVersion := "3.3.4"
ThisBuild / organization := "vpi"

val catsEffectVersion      = "3.5.7"
val doobieVersion          = "1.0.0-RC5"
val circeVersion           = "0.14.10"
val sqliteJdbcVersion      = "3.47.1.0"
val munitVersion           = "1.0.3"
val munitCatsEffectVersion = "2.0.0"

val testDeps = Seq(
  "org.scalameta" %% "munit"              % munitVersion           % Test,
  "org.typelevel" %% "munit-cats-effect"  % munitCatsEffectVersion % Test,
)

lazy val db = project
  .in(file("modules/db"))
  .settings(
    name := "vpi-db",
    libraryDependencies ++= Seq(
      "org.tpolecat" %% "doobie-core"  % doobieVersion,
      "org.typelevel" %% "cats-effect" % catsEffectVersion,
      "org.xerial"    %  "sqlite-jdbc" % sqliteJdbcVersion,
    ) ++ testDeps,
  )

lazy val ingest = project
  .in(file("modules/ingest"))
  .dependsOn(db)
  .settings(
    name := "vpi-ingest",
    libraryDependencies ++= Seq(
      "io.circe" %% "circe-core"    % circeVersion,
      "io.circe" %% "circe-generic" % circeVersion,
      "io.circe" %% "circe-parser"  % circeVersion,
    ) ++ testDeps,
  )

lazy val search = project
  .in(file("modules/search"))
  .dependsOn(db)
  .settings(
    name := "vpi-search",
    libraryDependencies ++= testDeps,
  )

lazy val root = project
  .in(file("."))
  .aggregate(db, ingest, search)
  .settings(
    name         := "viet-print-index-search",
    publish / skip := true,
  )
