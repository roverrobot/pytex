import hashlib
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
