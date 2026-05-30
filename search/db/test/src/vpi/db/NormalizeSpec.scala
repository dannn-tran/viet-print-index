package vpi.db

class NormalizeSpec extends munit.FunSuite:

  test("ASCII passthrough unchanged") {
    assertEquals(Normalize.normalize("hello world"), "hello world")
  }

  test("lowercases ASCII") {
    assertEquals(Normalize.normalize("Yalta"), "yalta")
  }

  test("strips Vietnamese tones from individual chars") {
    assertEquals(Normalize.normalize("ộ"), "o")
    assertEquals(Normalize.normalize("ị"), "i")
    assertEquals(Normalize.normalize("ề"), "e")
    assertEquals(Normalize.normalize("ả"), "a")
    assertEquals(Normalize.normalize("ũ"), "u")
  }

  test("full sentence round-trip") {
    assertEquals(Normalize.normalize("Hội nghị Yalta"), "hoi nghi yalta")
  }
