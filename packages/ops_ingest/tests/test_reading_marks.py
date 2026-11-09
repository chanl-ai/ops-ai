"""HTML furniture kept in the reading and dropped by cleaning, by failure mode: furniture lost from the reading (so a
cleaning change reads the page again), furniture left in after cleaning, and a page with no main element emptied by
"main content only"."""

from __future__ import annotations

from ops_ingest.reading import ReadingSettings, read, to_parsed_document

PAGE = b"""<html><head><title>Late claims</title></head><body>
<nav class="site-nav"><a href="/">Home</a> <a href="/claims">Claims</a></nav>
<div class="cookie-banner"><p>We use cookies to improve this site.</p></div>
<main><h1>Telling us late</h1><p>You can still claim after 30 days if the delay did not harm our assessment.</p></main>
<aside><p>Related: motor claims time limits</p></aside>
<footer><p>Copyright 2026 Harbour Insurance</p></footer>
</body></html>"""

NO_MAIN = b"""<html><body><h1>Rates</h1><p>The standard variable rate is 6.1 percent.</p>
<footer><p>Terms apply</p></footer></body></html>"""


def _text(furniture: bool, main_content: bool, page: bytes = PAGE) -> str:
    reading = read(page, filename="page.html", mime_type="text/html", settings=ReadingSettings(ocr="off"))
    return to_parsed_document(reading, furniture=furniture, main_content=main_content).plain_text()


def test_the_reading_keeps_furniture_marked_so_cleaning_needs_no_second_read() -> None:
    reading = read(PAGE, filename="page.html", mime_type="text/html", settings=ReadingSettings(ocr="off"))
    blocks = [b for p in reading.pages for b in p.blocks]
    marked = {b.text for b in blocks if b.furniture}
    assert {"We use cookies to improve this site.", "Copyright 2026 Harbour Insurance"} <= marked, marked
    assert any(b.main and "30 days" in b.text for b in blocks)
    assert "We use cookies" in _text(furniture=False, main_content=False)


def test_cleaning_drops_furniture_and_keeps_the_main_content() -> None:
    cleaned = _text(furniture=True, main_content=False)
    assert "cookies" not in cleaned and "Copyright" not in cleaned and "Home" not in cleaned, cleaned
    assert "Related: motor claims" not in cleaned
    main = _text(furniture=False, main_content=True)
    assert "30 days" in main and "Related" not in main and "cookies" not in main, main


def test_main_content_only_keeps_a_page_with_no_main_element_whole() -> None:
    assert "6.1 percent" in _text(furniture=True, main_content=True, page=NO_MAIN)
