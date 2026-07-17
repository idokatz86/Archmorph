import re
from pathlib import Path

infra_dir = Path(__file__).resolve().parent
files_to_fix = [
    infra_dir / "main.tf",
    infra_dir / "staging/main.tf",
    infra_dir / "dr/main.tf",
]

for filepath in files_to_fix:
    try:
        with filepath.open('r') as f:
            content = f.read()

        # Replace cors_policy { ... } -> cors { ... }
        content = re.sub(r'cors_policy\s*\{', 'cors {', content)
        # Replace expose_headers -> exposed_headers
        content = re.sub(r'expose_headers\s*=', 'exposed_headers =', content)
        # Replace max_age -> max_age_in_seconds
        content = re.sub(r'max_age\s*=', 'max_age_in_seconds =', content)

        with filepath.open('w') as f:
            f.write(content)
        print(f"Fixed {filepath}")
    except FileNotFoundError:
        print(f"File not found: {filepath}")

