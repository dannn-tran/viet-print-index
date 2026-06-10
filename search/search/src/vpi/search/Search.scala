package vpi.search

import doobie.*
import doobie.implicits.*
import vpi.db.Normalize

case class SearchResult(imageUri: String, snippet: String, publicationId: Option[String])
case class PageResult(imageUri: String, text: String, publicationId: Option[String])

object Search:
  def search(
    query: String,
    pub: Option[String] = None,
    limit: Int = 20,
    offset: Int = 0,
  ): ConnectionIO[List[SearchResult]] =
    val q         = Normalize.normalize(query)
    val pubFilter = pub.fold(Fragment.empty)(p => fr"AND pages.publication_id = $p")
    (fr"""
      SELECT pages_fts.image_uri,
             snippet(pages_fts, 1, '>>>', '<<<', '...', 64),
             pages.publication_id
      FROM pages_fts
      JOIN pages USING (image_uri)
      WHERE pages_fts MATCH $q
    """ ++ pubFilter ++ fr"ORDER BY rank LIMIT $limit OFFSET $offset")
      .query[SearchResult].to[List]

  def getPage(imageUri: String): ConnectionIO[Option[PageResult]] =
    sql"SELECT image_uri, text, publication_id FROM pages WHERE image_uri = $imageUri"
      .query[PageResult].option

  def contextPages(imageUri: String, window: Int): ConnectionIO[List[PageResult]] =
    val issueDir = imageUri.substring(0, imageUri.lastIndexOf('/') + 1)
    val pattern  = issueDir + "%"
    sql"""
      SELECT image_uri, text, publication_id FROM pages
      WHERE image_uri LIKE $pattern
      ORDER BY image_uri
    """.query[PageResult].to[List].map { pages =>
      val idx = pages.indexWhere(_.imageUri == imageUri)
      if idx < 0 then pages
      else pages.slice(Math.max(0, idx - window), idx + window + 1)
    }
