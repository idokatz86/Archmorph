import re
import fileinput

files = [
    "/Users/idokatz/VSCode/Archmorph/docs/architecture.excalidraw",
    "/Users/idokatz/VSCode/Archmorph/docs/application-flow.excalidraw"
]

for file_path in files:
    with open(file_path, "r") as f:
        text = f.read()

    text = re.sub(r'v3\.\d+\.\d+', 'v3.8.0', text)
    text = re.sub(r'Beta Disclaimer Banner', 'Vibe-Coding Disclaimer', text)
    
    # Update Chatbot text to include dynamic roadmap
    text = text.replace('Chatbot + GitHub Issue Creator', 'Roadmap Live Sync + GitHub Issues')

    with open(file_path, "w") as f:
        f.write(text)

print("Updated excalidraw files")
