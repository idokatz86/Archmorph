import re

file_path = "/Users/idokatz/VSCode/Archmorph/frontend/src/components/Roadmap.jsx"
with open(file_path, "r") as f:
    text = f.read()

# Replace:
# <span>{feature}</span>
# With a function that parses markdown links!
new_span = """<span dangerouslySetInnerHTML={{ __html: feature.replace(/\\[([^\]]+)\\]\\(([^)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-cta hover:underline">$1</a>') }} />"""

text = re.sub(r'<span>\{feature\}</span>', new_span, text)

with open(file_path, "w") as f:
    f.write(text)

print("Updated Roadmap.jsx")
