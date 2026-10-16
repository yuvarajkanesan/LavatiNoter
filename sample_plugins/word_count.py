NAME = "Word count"
VERSION = "1.0"
DESCRIPTION = "Counts the words, characters and lines of the document or the selection."


def register(api):
    def count():
        text = api.selection() or api.text()
        scope = "selection" if api.selection() else "document"
        api.flash(f"{scope}: {len(text.split()):,} words, {len(text):,} characters, {text.count(chr(10)) + 1:,} lines")
    api.add_command("Count words", count, shortcut="Ctrl+Alt+W")
