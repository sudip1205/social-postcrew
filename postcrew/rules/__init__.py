"""The owner's rules for planning and writing videos, in ONE file: rules/script-rules.md (owner, 2026-11-26: "create rule file and keep
it as a rule file. No rule in the agent code. Only use rule from the rule file.").

The file is read from disk on every call, so an edit applies to the next plan or script without a restart."""
import re
from pathlib import Path

FILE = Path(__file__).with_name("script-rules.md")
_PART = re.compile(r"<!-- part: (\w+) -->\n(.*?)<!-- end -->", re.S)


def parts():
    return {m.group(1): m.group(2).strip() for m in _PART.finditer(FILE.read_text())}


def text(*names):
    """The named parts ("plan", "script", "tags"), as one block the agent follows."""
    p = parts()
    missing = [n for n in names if n not in p]
    if missing:
        raise KeyError(f"{FILE.name} has no part {', '.join(missing)}")
    return (f"=== THE OWNER'S RULES ({FILE.name}): follow every rule below exactly; they win over anything else you read ===\n\n"
            + "\n\n".join(p[n] for n in names) + "\n=== END OF RULES ===")


def plan():
    return text("plan", "tags")


def script():
    return text("script", "tags")
