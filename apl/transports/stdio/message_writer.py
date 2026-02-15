import json
import sys
from typing import Any


def write_json_line(message: dict[str, Any]) -> None:
    line = json.dumps(message) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()
