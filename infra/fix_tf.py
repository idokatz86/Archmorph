import re

files_to_fix = [
    "/Users/idokatz/VSCode/Archmorph/infra/main.tf",
    "/Users/idokatz/VSCode/Archmorph/infra/staging/main.tf",
    "/Users/idokatz/VSCode/Archmorph/infra/dr/main.tf"
]

for filepath in files_to_fix:
    try:
        with open(filepath, 'r') as f:
            content = f.read()

        # Replace cors_policy { ... } -> cors { ... }
        content = re.sub(r'cors_policy\s*\{', 'cors {', content)
        # Replace expose_headers -> exposed_headers
        content = re.sub(r'expose_headers\s*=', 'exposed_headers =', content)
        # Replace max_age -> max_age_in_seconds
        content = re.sub(r'max_age\s*=', 'max_age_in_seconds =', content)

        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Fixed {filepath}")
    except FileNotFoundError:
        print(f"File not found: {filepath}")

