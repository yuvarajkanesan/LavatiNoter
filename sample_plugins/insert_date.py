import datetime

NAME = "Insert date and time"
VERSION = "1.0"
DESCRIPTION = "Inserts today's date or the current time at the caret."


def register(api):
    api.add_command("Insert date (2026-10-16)", lambda: api.insert(datetime.date.today().isoformat()))
    api.add_command("Insert date and time", lambda: api.insert(datetime.datetime.now().strftime("%Y-%m-%d %H:%M")), shortcut="F5")
