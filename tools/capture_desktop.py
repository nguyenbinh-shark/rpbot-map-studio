"""Capture a specified result tab in the real desktop app."""

from argparse import ArgumentParser, Namespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui import Application

parser = ArgumentParser()
parser.add_argument("--result", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--tab", choices=["overview", "charts"], default="overview")
args = parser.parse_args()
app = Application(
    Namespace(
        output=None,
        mode="full",
        file=None,
        database=None,
        open_result=args.result,
        smoke=False,
        smoke_report=args.output,
        quit_on_complete=True,
    )
)


def select():
    if args.tab == "charts":
        app.tabs.select(1)
        keys = list(app.chart_rows)
        key = next((k for k in keys if "Trajectory" in app.chart_rows[k]["title"]), keys[0])
        app.tree.selection_set(key)
        app.chart_selected()


app.root.after(1800, select)
app.root.after(3500, lambda: app.smoke_result("complete"))
app.run()
