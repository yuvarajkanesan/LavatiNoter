import re

NAME = "Markdown table of contents"
VERSION = "1.0"
DESCRIPTION = "Inserts a linked table of contents built from the headings of a Markdown document."


def register(api):
    def toc():
        lines = []
        for line in api.text().split("\n"):
            m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
            if m:
                slug = re.sub(r"[^\w\- ]", "", m.group(2).lower()).replace(" ", "-")
                lines.append("  " * (len(m.group(1)) - 1) + f"- [{m.group(2)}](#{slug})")
        if not lines:
            api.flash("No headings found")
            return
        api.insert("\n".join(lines) + "\n")
    api.add_command("Insert table of contents", toc)
