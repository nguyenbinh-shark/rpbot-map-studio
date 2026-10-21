from pathlib import Path
import json
import sys
from verify_output import verify

result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert result["state"] == "complete", result.get("message")
assert result["visible"]
print(json.dumps(verify(result["output"]), indent=2))
