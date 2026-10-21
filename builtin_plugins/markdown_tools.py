import re

NAME = "Markdown tools"
VERSION = "1.0"
DESCRIPTION = "Table of contents, table alignment, lists, code fences and links for Markdown notes."


def align_table(s):
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in s.split("\n") if l.strip()]
    if not rows:
        return s
    w = max(len(r) for r in rows)
    rows = [r + [""] * (w - len(r)) for r in rows]
    rule = lambda c: re.fullmatch(r":?-+:?", c) is not None
    widths = [max([3] + [len(r[i]) for r in rows if not rule(r[i])]) for i in range(w)]
    out = []
    for r in rows:
        cells = [("-" * widths[i]) if rule(c) else c.ljust(widths[i]) for i, c in enumerate(r)]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def register(api):
    t = api.transform

    def toc():
        out = []
        for line in api.text().split("\n"):
            m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
            if m:
                slug = re.sub(r"[^\w\- ]", "", m.group(2).lower()).replace(" ", "-")
                out.append("  " * (len(m.group(1)) - 1) + f"- [{m.group(2)}](#{slug})")
        if out:
            api.insert("\n".join(out) + "\n")
        else:
            api.flash("No headings found")

    def link():
        url = api.ask("Link address:", "https://")
        if url:
            t(lambda s: f"[{s}]({url})")

    def nonblank(s):
        return [x for x in s.split("\n") if x.strip()]

    api.add_command("Insert table of contents", toc)
    api.add_command("Align table columns", lambda: t(align_table))
    api.add_command("Lines to bullet list", lambda: t(lambda s: "\n".join("- " + l for l in nonblank(s))))
    api.add_command("Lines to numbered list", lambda: t(lambda s: "\n".join(f"{i}. {l}" for i, l in enumerate(nonblank(s), 1))))
    api.add_command("Lines to checklist", lambda: t(lambda s: "\n".join("- [ ] " + l for l in nonblank(s))))
    api.add_command("Wrap in a code fence", lambda: t(lambda s: "```\n" + s.strip("\n") + "\n```"))
    api.add_command("Make the selection a link", link)
    api.add_command("Quote every line with >", lambda: t(lambda s: "\n".join("> " + l for l in s.split("\n"))))
