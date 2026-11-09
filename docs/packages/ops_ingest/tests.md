# ops_ingest tests

Status: current.

One test per failure mode. The list comes first; each row names the test that guards it. Fixtures in
`fixtures/` are built by `fixtures/build_fixtures.py` (a two-page PDF with a ruled table, an image-only
PDF, a DOCX with nested headings and a table, an XLSX fee schedule, an HTML help page with navigation,
cookie banner, sidebar and footer).

```bash
uv sync --extra ocr     # OCR tests need the tesseract binary on PATH as well
uv run pytest
```

## Parsing

| # | Failure mode | Test |
|---|---|---|
| P3 | OCR is requested but not installed, and the page is indexed as empty | `test_parsers.py::test_ocr_requested_but_missing_fails_loudly` |
| P4 | A PDF table loses its header row | `test_parsers.py::test_pdf_table_keeps_headers_and_caption` |
| P5 | A PDF table's cells are also read as prose, so they are indexed twice | `test_parsers.py::test_pdf_table_cells_not_repeated_as_prose` |
| P6 | Page numbers are lost, so citations cannot name a page | `test_parsers.py::test_pdf_sections_carry_page_numbers` |
| P7 | A DOCX table leaves its section, or nested headings lose their path | `test_parsers.py::test_docx_heading_path_and_table_placement` |
| P8 | XLSX headers are lost or numbers change form (`5.0` for `5`) | `test_parsers.py::test_xlsx_headers_and_cell_values` |
| P9 | `clean` leaves navigation, cookie banner, sidebar, footer or script text | `test_parsers.py::test_html_clean_removes_page_furniture` |
| P10 | `clean` removes real content whose class contains a boilerplate substring (`lead` contains `ad`) | `test_parsers.py::test_html_clean_keeps_content_with_lookalike_classes` |
| P11 | A file over 50 MB is parsed instead of failing with `too_large` | `test_parsers.py::test_oversized_file_is_refused` |

## Reading

Fixtures added for reading: a page half text and half picture, a text page with a small picture, a fillable form, a
PNG scan and a two-page TIFF scan, all of a made-up enrolment form.

| # | Failure mode | Test |
|---|---|---|
| R1 | A scanned PDF reads empty, or its OCR words carry no confidence | `test_reading.py::test_scanned_pdf_is_read_by_ocr_with_word_confidence` |
| R2 | The picture half of a mixed page is never read, because the page has some text | `test_reading.py::test_picture_half_of_a_mixed_page_is_read` |
| R3 | A logo-sized picture starts OCR, or a file needing no OCR fails without Tesseract | `test_reading.py::test_small_picture_does_not_start_ocr` |
| R4 | A scan with OCR off reads as an empty page instead of an unread one with its reason | `test_reading.py::test_scan_with_ocr_off_is_listed_unread` |
| R5 | `always` keeps a bad text layer, or a page's low-confidence share is wrong | `test_reading.py::test_always_ocrs_a_text_page_and_reports_low_confidence` |
| R6 | A scan carrying its own OCR text layer is read twice | `test_reading.py::test_text_layer_over_a_scan_is_not_read_twice` |
| R7 | Values typed into a fillable form are missed, since they are not in the text layer | `test_reading.py::test_form_values_are_read_from_the_form_dictionary` |
| R8 | Form values do not reach search | `test_reading.py::test_form_fields_are_searchable_after_splitting` |
| R9 | A PNG or TIFF scan is refused, or a TIFF's later frames are lost | `test_reading.py::test_image_files_are_read_one_page_per_frame` |
| R10 | A file over 2,000 pages is read part way instead of failing with `too_many_pages` | `test_reading.py::test_file_over_the_page_limit_is_refused` |
| R11 | OCR needed but not installed reads the page as empty | `test_reading.py::test_ocr_needed_but_missing_fails_loudly` |
| R12 | A format with no reader, or a broken file, fails without a reason code | `test_reading.py::test_file_without_a_reader_fails_with_a_reason` |
| R13 | Splitting a DOCX, XLSX or HTML reading loses section paths, paragraph breaks or tables, or invents page numbers | `test_reading.py::test_reading_splits_the_same_as_the_parser` |
| R15 | A PDF splits into other section paths, paragraph breaks, tables or pages than the parser gave before PDFs moved onto the reader | `test_reading.py::test_pdf_splits_into_the_sections_the_parser_gave` |
| R16 | A huge image, a decompression bomb or a poster-sized page exhausts memory | `test_reading.py::test_decompression_bomb_image_is_refused_before_decoding`, `test_reading.py::test_huge_pdf_page_is_drawn_at_a_bounded_size` |
| R17 | A form whose fields loop never finishes reading | `test_reading.py::test_form_field_tree_with_a_cycle_is_read_once` |
| R18 | A truncated image raises out of the read instead of failing its page | `test_reading.py::test_corrupt_image_fails_its_page_with_a_reason` |
| R14 | A page read on its own after a restart gets other heading levels than in a whole read | `test_reading.py::test_page_read_on_its_own_matches_a_whole_read` |

## Splitting

| # | Failure mode | Test |
|---|---|---|
| S1 | A chunk exceeds `size` when one sentence is longer than `size` | `test_split.py::test_no_chunk_exceeds_size_with_overlong_sentence` |
| S2 | `fixed` windows exceed `size` or do not overlap by `overlap` | `test_split.py::test_fixed_windows_respect_size_and_overlap` |
| S3 | Overlap duplicates headings, or the context header lands in the returned text | `test_split.py::test_context_header_once_per_chunk_with_overlap` |
| S4 | `parent_child` returns the child instead of the parent | `test_split.py::test_parent_child_returns_parent` |
| S5 | Invalid settings are accepted (two splitters, `parent_child` with `fixed`, size bounds, two key columns) | `test_split.py::test_invalid_settings_refused` |
| S6 | `table_rows` drops the key column, indexes metadata columns or keeps ignored ones | `test_split.py::test_table_rows_column_roles_and_key` |
| S7 | A band column is not parsed into a numeric range | `test_split.py::test_table_rows_parses_bands` |
| S8 | `table_rows` on a document with no tables produces nothing | `test_split.py::test_table_rows_without_tables_falls_back` |
| S9 | `faq` calls a model directly instead of the `ModelClient` protocol | `test_split.py::test_faq_goes_through_model_client_only` |
| S10 | An AI step runs in a sync before the knowledge owner approves it | `test_split.py::test_ai_step_waits_for_approval` |
| S11 | A topic reply that drops or reorders sections loses content | `test_split.py::test_topic_reply_cannot_drop_sections` |
| S12 | A change to page furniture alone changes the content digest and creates a version | `test_split.py::test_furniture_change_keeps_digest` |
| S13 | A PDF table does not reach `table_rows` with its headers (parser and splitter unwired) | `test_split.py::test_pdf_to_row_chunks_end_to_end` |

## Metadata, dedupe, versions, rules

| # | Failure mode | Test |
|---|---|---|
| M1 | A held item (required key missing or blank) still emits chunks | `test_metadata.py::test_held_item_emits_no_chunks` |
| M2 | A key only one knowledge base requires holds the item in every knowledge base | `test_metadata.py::test_kb_only_key_holds_that_kb_only` |
| M3 | `ai:` is accepted for department, sensitivity or owner | `test_metadata.py::test_ai_mapping_refused_for_trust_keys` |
| M4 | A mapping lowers the item's sensitivity | `test_metadata.py::test_mapping_cannot_lower_sensitivity` |
| D1 | Identical content across sources is indexed twice | `test_dedupe.py::test_identical_content_shares_units` |
| D2 | Duplicates in different permission scopes are merged, hiding content from people entitled to one | `test_dedupe.py::test_permission_scopes_not_merged` |
| D3 | Whitespace or invisible characters change the digest, or a real edit does not | `test_dedupe.py::test_digest_normalisation` |
| D4 | A later effective date does not supersede when versions arrive out of order | `test_dedupe.py::test_later_effective_date_supersedes` |
| D5 | A future-dated version is served as current | `test_dedupe.py::test_future_version_is_scheduled` |
| D6 | An unresolved `supersedes` is accepted | `test_dedupe.py::test_unresolved_supersedes_raises` |
| R1 | An exclude rule is not applied, or the decision does not name it | `test_rules.py::test_exclude_rule_applied_and_named` |
| R2 | With include rules, an item matching none is still included | `test_rules.py::test_include_rules_require_a_match` |
| R3 | An include rule overrides an exclude rule | `test_rules.py::test_exclude_wins_over_include` |
| R4 | `*` in a path glob crosses folders | `test_rules.py::test_single_star_stays_in_folder` |
| R5 | Title, MIME, modified-after or size-under rules are ignored or mis-parsed | `test_rules.py::test_rule_fields` |

## Seen failing

Each test below was run against a deliberately broken implementation, seen failing for the stated
reason, and the code restored. S1 and P10 were broken by restoring the earlier implementation's
behaviour.

| Test | Broken by | Failure seen |
|---|---|---|
| S1 | Packing whole sentences without cutting an over-long one | `assert 257 <= 100` (chunk tokens against `size`) |
| P10 | Matching boilerplate classes by substring | the `lead` paragraph was missing from the cleaned text |
| S3 | Adding the context header to the returned text | `'Fees' is contained here: Card policy > Fees` |
| S4 | Returning the first child as the chunk text | parent text differed from the full section |
| S9 | A provider import in `strategies/faq.py` | `assert ['…/strategies/faq.py'] == []` |
| S10 | Running AI steps without approval | `assert [ModelCall(…)] == []` |
| R5 | (found by the test, not seeded) the console's `modifiedAfter` and `sizeUnder` values were rejected | pydantic `literal_error`; the model now accepts both spellings |
