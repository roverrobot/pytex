import datetime
import hashlib
import os
from pytex import pdftex


def test_pdfmdfivesum_hashes_expanded_general_text(collector):
    collector.parse("\\def\\a{ab}\\pdfmdfivesum{\\a}")
    assert collector.getString().strip() == hashlib.md5(b"ab").hexdigest().upper()


def test_pdfmdfivesum_file_hashes_general_text_filename(collector, example_tex):
    collector.parse("\\pdfmdfivesum file {example.tex}")
    expected = hashlib.md5(b"Hello, world!\n").hexdigest().upper()
    assert collector.getString().strip() == expected


def test_mdfivesum_alias_matches_pdftex_primitive(collector):
    collector.parse("\\mdfivesum{abc}")
    assert collector.getString().strip() == hashlib.md5(b"abc").hexdigest().upper()


def _pdf_date_string(timestamp: float) -> str:
    dt = datetime.datetime.fromtimestamp(timestamp).astimezone()
    s = dt.strftime("D:%Y%m%d%H%M%S")
    offset = dt.utcoffset()
    if offset is None:
        return s
    seconds = int(offset.total_seconds())
    if seconds == 0:
        return s + "Z"
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    return f"{s}{sign}{hours:02d}'{minutes:02d}'"


def test_pdffilemoddate_reports_timestamp_for_cwd_file(collector, tmp_path):
    path = tmp_path / "tt.log"
    path.write_text("log\n")
    collector.parse("\\pdffilemoddate{tt.log}")
    assert collector.getString().strip() == _pdf_date_string(os.path.getmtime(path))


def test_pdffilemoddate_missing_file_expands_to_nothing(collector):
    collector.parse("A\\pdffilemoddate{missing.log}B")
    assert collector.getString().strip() == "AB"
