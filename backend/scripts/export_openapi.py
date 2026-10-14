"""Write the API's OpenAPI schema to stdout (used to generate frontend types)."""

import json
import sys

from app.main import app

json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
