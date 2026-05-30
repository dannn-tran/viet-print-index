package vpi.db

import java.text.Normalizer

object Normalize:
  def normalize(s: String): String =
    Normalizer.normalize(s, Normalizer.Form.NFD)
      .filter(c => Character.getType(c) != Character.NON_SPACING_MARK)
      .toLowerCase
