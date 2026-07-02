#!/usr/bin/env python3
"""Validation script for EcoFlow integrācijas tulkojumiem"""

import json
from pathlib import Path

def validate_translations():
    root = Path(__file__).parent
    translations_dir = root / "translations"
    
    print("🔍 Tulkojumu validācija:\n")
    
    # Pārbaudīt strings.json
    strings_file = root / "strings.json"
    try:
        strings = json.loads(strings_file.read_text(encoding='utf-8'))
        print(f"✓ strings.json ir derīgs")
    except Exception as e:
        print(f"✗ strings.json kļūda: {e}")
        return False
    
    # Pārbaudīt translations/
    files = sorted(translations_dir.glob("*.json"))
    valid_count = 0
    
    for f in files:
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            
            # Validācija
            required = {"config", "options", "abort"}
            if not required.issubset(data.keys()):
                print(f"✗ {f.stem}: pietrūkst sekcijas {required - set(data.keys())}")
                continue
            
            valid_count += 1
        except Exception as e:
            print(f"✗ {f.stem}: {e}")
    
    print(f"✓ {valid_count}/{len(files)} tulkojumi ir derīgi")
    
    if valid_count == len(files):
        print("\n✅ Visi tulkojumi ir pareizi!")
        return True
    else:
        print(f"\n⚠️  {len(files) - valid_count} problēmas atrasta!")
        return False

if __name__ == "__main__":
    validate_translations()
