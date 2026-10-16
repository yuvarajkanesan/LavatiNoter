"""Printing and export (PDF, HTML) with syntax colours, always on a white page whatever the editor theme is."""
from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QTextCharFormat, QTextCursor, QTextDocument

from . import theme
from .highlighter import Highlighter


def styled_document(text, lang, font_pt=10):
    """A QTextDocument holding `text` with the language's colours baked in as real character formats (light palette)."""
    previous = theme.THEME_NAME
    theme.apply("Light")
    try:
        doc = QTextDocument()
        f = QFont(theme.mono_family(), font_pt)
        f.setStyleHint(QFont.Monospace)
        doc.setDefaultFont(f)
        doc.setPlainText(text)
        h = Highlighter(doc)
        h.set_lang(lang)
        h.rehighlight()
        block = doc.firstBlock()
        while block.isValid():
            for fr in block.layout().formats():
                cur = QTextCursor(doc)
                cur.setPosition(block.position() + fr.start)
                cur.setPosition(block.position() + fr.start + fr.length, QTextCursor.KeepAnchor)
                cur.mergeCharFormat(fr.format)
            block = block.next()
        h.setDocument(None)
        return doc
    finally:
        theme.apply(previous)


def make_printer(path=None):
    from PySide6.QtPrintSupport import QPrinter
    pr = QPrinter(QPrinter.HighResolution)
    pr.setPageSize(QPageSize(QPageSize.A4))
    pr.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
    if path:
        pr.setOutputFormat(QPrinter.PdfFormat)
        pr.setOutputFileName(path)
    return pr


def export_pdf(path, text, lang, title="", font_pt=10):
    doc = styled_document(text, lang, font_pt)
    pr = make_printer(path)
    pr.setDocName(title or "document")
    doc.print_(pr)
    return path


def export_html(path, text, lang, title=""):
    doc = styled_document(text, lang)
    body = doc.toHtml()
    if title:
        body = body.replace("<head>", f"<head><title>{title}</title>", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path
