"""Escape user text for ReportLab without flattening its authored layout."""
from xml.sax.saxutils import escape


def escaped_pdf_text(value):
    def line_text(line):
        line = line.expandtabs(4)
        leading = len(line) - len(line.lstrip(" "))
        return "&#160;" * leading + escape(line[leading:], {"'": "&apos;", '"': "&quot;"})
    return "<br/>".join(line_text(line) for line in str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n"))
