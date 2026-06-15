#!/usr/bin/env python3
"""
Validate receipt JSON files for correct structure and hashes.
"""

import json
import hashlib
import sys
from pathlib import Path

RECEIPTS_DIR = Path("space/receipts")

def validate_receipt_file(filepath):
    """Validate a single receipt file."""
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        required_keys = ['chat_id', 'answer', 'sha256_hash', 'timestamp']
        for key in required_keys:
            if key not in data:
                print(f"✗ {filepath.name}: Missing required key: {key}")
                return False
        
        # Verify hash
        computed_hash = hashlib.sha256(data['answer'].encode()).hexdigest()
        if computed_hash != data['sha256_hash']:
            print(f"✗ {filepath.name}: Hash mismatch")
            return False
        
        print(f"✓ {filepath.name}: Valid receipt")
        return True
    except json.JSONDecodeError as e:
        print(f"✗ {filepath.name}: Invalid JSON - {e}")
        return False
    except Exception as e:
        print(f"✗ {filepath.name}: Error - {e}")
        return False

def main():
    """Validate all receipt files."""
    if not RECEIPTS_DIR.exists():
        print(f"✗ Receipts directory not found: {RECEIPTS_DIR}")
        print("  (This is normal for initial setup)")
        sys.exit(0)

    receipt_files = list(RECEIPTS_DIR.glob("*.json"))
    
    if not receipt_files:
        print("✓ No receipt files to validate")
        sys.exit(0)

    all_valid = True
    for filepath in receipt_files:
        if not validate_receipt_file(filepath):
            all_valid = False

    if all_valid:
        print("\n✓ All receipt files validated successfully")
        sys.exit(0)
    else:
        print("\n✗ Some receipt files failed validation")
        sys.exit(1)

if __name__ == "__main__":
    main()
