"""Set up the lab indexes without replacing existing resources."""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


if __name__ == "__main__":
    load_dotenv(override=True)
    endpoint = os.environ["AZURE_SEARCH_SERVICE_ENDPOINT"]
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("restore-graph-indexes.py")),
            "--endpoint",
            endpoint,
            "--ensure",
        ],
        check=True,
    )
