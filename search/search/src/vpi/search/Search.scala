package vpi.search

import doobie.*
import doobie.implicits.*
import vpi.db.Normalize

case class SearchResult(imageUri: String, snippet: String)

object Search:
  def search(query: String): ConnectionIO[List[SearchResult]] =
    val q = Normalize.normalize(query)
    sql"""
      SELECT image_uri,
             snippet(pages_fts, 1, '>>>', '<<<', '...', 64)
      FROM pages_fts
      WHERE pages_fts MATCH $q
      ORDER BY rank
    """.query[SearchResult].to[List]
