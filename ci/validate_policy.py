#!/usr/bin/env python3
"""
Validate policy YAML files for correct structure and content.
"""

import yaml
import sys
from pathlib import Path

POLICY_DIR = Path("policy")

def validate_yaml_file(filepath):
    """Validate a single YAML file."""
    try:
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
        print(f"✓ {filepath.name}: Valid YAML")
        return True, data
    except yaml.YAMLError as e:
        print(f"✗ {filepath.name}: Invalid YAML - {e}")
        return False, None

def validate_policy_state(data):
    """Validate policy_state.yaml structure."""
    required_keys = ['version', 'core_principles', 'boundaries', 'output_preferences']
    for key in required_keys:
        if key not in data:
            print(f"✗ Missing required key: {key}")
            return False
    print("✓ policy_state.yaml: Valid structure")
    return True

def main():
    """Validate all policy files."""
    if not POLICY_DIR.exists():
        print(f"✗ Policy directory not found: {POLICY_DIR}")
        sys.exit(1)

    yaml_files = list(POLICY_DIR.glob("*.yaml")) + list(POLICY_DIR.glob("*.yml"))
    
    if not yaml_files:
        print("✗ No YAML files found in policy directory")
        sys.exit(1)

    all_valid = True
    for filepath in yaml_files:
        valid, data = validate_yaml_file(filepath)
        if valid and data:
            if filepath.name == "policy_state.yaml":
                if not validate_policy_state(data):
                    all_valid = False
        else:
            all_valid = False

    if all_valid:
        print("\n✓ All policy files validated successfully")
        sys.exit(0)
    else:
        print("\n✗ Some policy files failed validation")
        sys.exit(1)

if __name__ == "__main__":
    main()
