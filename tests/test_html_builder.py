from pytex.html_builder import element, render


def test_html_builder_escapes_text_and_attributes():
    node = element(
        "div",
        element("span", "A&B"),
        class_=["lead", "wide"],
        title='"x" & y',
    )
    assert (
        render(node)
        == '<div class="lead wide" title="&quot;x&quot; &amp; y"><span>A&amp;B</span></div>'
    )


def test_html_builder_renders_void_elements_without_closing_tag():
    assert render(element("meta", charset="utf-8")) == '<meta charset="utf-8">'
