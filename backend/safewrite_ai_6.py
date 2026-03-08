import re

with open("tests/test_ai_suggestion.py", "r") as f:
    text = f.read()

# Add import json if missing
if "import json" not in text:
    text = "import json\n" + text

text = text.replace('target_service', 'azure_service')

with open("tests/test_ai_suggestion.py", "w") as f:
    f.write(text)
