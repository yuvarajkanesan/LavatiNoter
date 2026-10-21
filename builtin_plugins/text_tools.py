import re

NAME = "Text tools"
VERSION = "1.0"
DESCRIPTION = "Change the case style of text and tidy whitespace. Works on the selection, or the whole document when nothing is selected."


def words(s):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    return [w for w in re.split(r"[^A-Za-z0-9]+", s) if w]


def per_line(fn):
    return lambda text: "\n".join(fn(line) for line in text.split("\n"))


def camel(line):
    w = words(line)
    return (w[0].lower() + "".join(x.capitalize() for x in w[1:])) if w else line


def register(api):
    t = api.transform
    api.add_command("Case: Title Case", lambda: t(lambda s: re.sub(r"[A-Za-z][A-Za-z']*", lambda m: m.group().capitalize(), s)))
    api.add_command("Case: Sentence case", lambda: t(per_line(lambda l: l[:1].upper() + l[1:].lower())))
    api.add_command("Case: Swap case", lambda: t(lambda s: s.swapcase()))
    api.add_command("Case: camelCase", lambda: t(per_line(camel)))
    api.add_command("Case: PascalCase", lambda: t(per_line(lambda l: "".join(x.capitalize() for x in words(l)))))
    api.add_command("Case: snake_case", lambda: t(per_line(lambda l: "_".join(x.lower() for x in words(l)))))
    api.add_command("Case: kebab-case", lambda: t(per_line(lambda l: "-".join(x.lower() for x in words(l)))))
    api.add_command("Case: CONSTANT_CASE", lambda: t(per_line(lambda l: "_".join(x.upper() for x in words(l)))))
    api.add_command("Whitespace: collapse runs of spaces", lambda: t(per_line(lambda l: re.sub(r"[ \t]+", " ", l).strip())))
    api.add_command("Whitespace: tabs to 4 spaces", lambda: t(lambda s: s.replace("\t", "    ")))
    api.add_command("Whitespace: leading 4 spaces to tabs",
                    lambda: t(per_line(lambda l: re.sub(r"^((?: {4})+)", lambda m: "\t" * (len(m.group(1)) // 4), l))))
    api.add_command("Whitespace: remove all blank lines", lambda: t(lambda s: "\n".join(l for l in s.split("\n") if l.strip())))
    api.add_command("Whitespace: squeeze repeated blank lines", lambda: t(lambda s: re.sub(r"\n{3,}", "\n\n", s)))

    def count():
        s = api.selection() or api.text()
        which = "selection" if api.selection() else "document"
        api.flash(f"{which}: {len(s.split()):,} words, {len(s):,} characters, {s.count(chr(10)) + 1:,} lines")
    api.add_command("Count words, characters and lines", count, shortcut="Ctrl+Alt+W")
