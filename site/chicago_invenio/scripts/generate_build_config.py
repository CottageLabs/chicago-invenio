#!/usr/bin/env python3
"""Generate build-time configuration for webpack.

This script reads environment variables and generates a JSON config file
that can be imported by JavaScript during the webpack build process.

Run this before `invenio webpack build`:
    pipenv run python site/chicago_invenio/scripts/generate_build_config.py
"""

import os
import json
from pathlib import Path

# Build config from environment variables
config = {
    "enableCurations": os.getenv("CHI_ENABLE_CURATIONS", "").lower() in ['1', 'true', 'yes']
}

# Output path relative to this script
script_dir = Path(__file__).parent
output_path = script_dir.parent.parent.parent / 'assets' / 'js' / 'chicago_invenio' / 'build_config.json'

# Ensure directory exists
output_path.parent.mkdir(parents=True, exist_ok=True)

# Write config
with open(output_path, 'w') as f:
    json.dump(config, f, indent=2)

print(f"Generated build config at {output_path}:")
print(f"  {json.dumps(config)}")
