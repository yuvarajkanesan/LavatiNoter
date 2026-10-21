"""A template for your own plugin: copy it, rename it, change it. Plugins are turned on with Plugins > Enable My Plugins.

Every command appears in the Plugins menu and in the Command Palette (Ctrl+Shift+P). What a plugin can use (the `api` object):
  api.text()                     the whole document            api.selection()      the selected text
  api.transform(fn)              replace the selection (or the whole text if nothing is selected) with fn(text)
  api.insert(text)               insert at the caret           api.set_text(text)   replace everything
  api.ask("Question", "default") a small input box (None if cancelled)               api.show("Title", text)  a window with text
  api.copy(text)                 put text on the clipboard     api.flash("message") a message in the status bar
  api.path() / api.language() / api.line()                     api.new_document(text, title) / api.open_file(path)
  api.add_command(title, function, shortcut="Ctrl+Alt+K")      api.on("save", lambda path: ...)   events: open, save, close
"""
NAME = "My first plugin"
VERSION = "1.0"
DESCRIPTION = "Shows how a plugin is written."


def register(api):
    api.add_command("Shout the selection", lambda: api.transform(lambda s: s.upper() + "!"))

    def greet():
        name = api.ask("What is your name?", "friend")
        if name:
            api.insert(f"Hello, {name}!")
    api.add_command("Say hello...", greet)
