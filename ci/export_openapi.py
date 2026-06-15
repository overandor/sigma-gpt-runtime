#!/usr/bin/env python3
"""
Export OpenAPI schema from FastAPI app for GPT Actions.
"""

import sys
import json
from pathlib import Path

# Import the app
sys.path.insert(0, str(Path(__file__).parent.parent / "space"))
from app import app

def export_openapi():
    """Export OpenAPI schema to JSON file."""
    openapi_schema = app.openapi()
    
    output_dir = Path("openapi")
    output_dir.mkdir(exist_ok=True)
    
    output_file = output_dir / "action_schema.generated.json"
    with open(output_file, 'w') as f:
        json.dump(openapi_schema, f, indent=2)
    
    print(f"✓ OpenAPI schema exported to {output_file}")
    return True

if __name__ == "__main__":
    export_openapi()
