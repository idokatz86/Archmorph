import re

file_path = "/Users/idokatz/VSCode/Archmorph/docs/PRD.md"
with open(file_path, "r") as f:
    text = f.read()

text = re.sub(r'\*\*Version:\*\* 3\.\d+\.\d+', '**Version:** 3.8.0', text)
text = re.sub(r'\*\*Date:\*\* [A-Za-z]+ \d+, \d{4}', '**Date:** March 9, 2026', text)

# Add vibe coding & community roadmap to Executive Summary Solution
if "GitHub issues natively integrated into the roadmap" not in text:
    text = text.replace(
        "sample diagram onboarding,",
        "sample diagram onboarding, dynamic GitHub issues natively integrated into the roadmap, transparent vibe-coding project status,"
    )
    
if "3.16 Community-Driven Roadmap" not in text:
    roadmap_addition = """### 3.16 Community-Driven Roadmap
- Real-time synchronization with GitHub issues for feature tracking.
- Markdown link parsing natively inside the frontend Roadmap UI to connect directly back to GitHub.
- Intelligent separation of Bugs vs. Features synced automatically to the community "Ideas" section.
- "Vibe-Coding" transparent user disclaimer implemented universally across the application.
- Fully transparent Legal ToS recognizing the free-of-charge experimental "As-Is" nature of the tool.

"""
    text = text.replace("## 4. Technical Architecture", roadmap_addition + "## 4. Technical Architecture")

with open(file_path, "w") as f:
    f.write(text)

print("Updated PRD.md")
