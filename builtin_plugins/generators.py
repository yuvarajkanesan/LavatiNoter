import datetime
import random
import secrets
import string
import uuid

NAME = "Generators"
VERSION = "1.0"
DESCRIPTION = "Insert dates and times, UUIDs, passwords, number sequences and placeholder text."

LOREM = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua ut enim ad minim "
         "veniam quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat duis aute irure dolor in reprehenderit in voluptate "
         "velit esse cillum dolore eu fugiat nulla pariatur excepteur sint occaecat cupidatat non proident sunt in culpa qui officia deserunt mollit anim").split()


def register(api):
    now = datetime.datetime.now
    api.add_command("Insert date (2026-10-21)", lambda: api.insert(datetime.date.today().isoformat()))
    api.add_command("Insert time (14:05:09)", lambda: api.insert(now().strftime("%H:%M:%S")))
    api.add_command("Insert date and time", lambda: api.insert(now().strftime("%Y-%m-%d %H:%M")), shortcut="Ctrl+Alt+T")
    api.add_command("Insert long date (Wednesday, 21 October 2026)", lambda: api.insert(now().strftime("%A, %d %B %Y")))
    api.add_command("Insert Unix timestamp", lambda: api.insert(str(int(now().timestamp()))))
    api.add_command("Insert UUID", lambda: api.insert(str(uuid.uuid4())))

    def password():
        n = api.ask("Password length:", "20")
        if n and n.isdigit():
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
            api.insert("".join(secrets.choice(alphabet) for _ in range(max(4, min(256, int(n))))))
    api.add_command("Insert random password...", password)

    def sequence():
        spec = api.ask("Start, count, step (for example 1, 10, 1):", "1, 10, 1")
        if not spec:
            return
        try:
            start, count, step = (int(x) for x in (spec.replace(" ", "").split(",") + ["1"])[:3])
        except ValueError:
            api.flash("Type three whole numbers, like 1, 10, 1")
            return
        api.insert("\n".join(str(start + i * step) for i in range(max(0, min(count, 100000)))))
    api.add_command("Insert number sequence...", sequence)

    def lorem():
        n = api.ask("Paragraphs:", "2")
        if n and n.isdigit():
            rnd = random.Random(7)
            paras = []
            for _ in range(max(1, min(50, int(n)))):
                sentences = []
                for _s in range(rnd.randint(3, 6)):
                    sentences.append(" ".join(rnd.choice(LOREM) for _ in range(rnd.randint(7, 15))).capitalize() + ".")
                paras.append(" ".join(sentences))
            api.insert("\n\n".join(paras))
    api.add_command("Insert placeholder text (Lorem ipsum)...", lorem)
