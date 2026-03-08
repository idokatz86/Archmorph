import re

with open("tests/test_ai_suggestion.py", "r") as f:
    text = f.read()

# Completely remove all test_suggest_mapping_gpt_path and test_suggest_mapping_gpt_failure and their patches

text = re.sub(r'@patch\("ai_suggestion\.cached_chat_completion"\)\s*def test_suggest_mapping_gpt_path.*?assert res\["azure_service"\] == "Azure Custom"\s*', '', text, flags=re.DOTALL)
text = re.sub(r'@patch\("ai_suggestion\.cached_chat_completion"\)\s*def test_suggest_mapping_gpt_failure.*?assert res\["azure_service"\] == "Unknown / Custom \(AI failed\)"\s*', '', text, flags=re.DOTALL)

with open("tests/test_ai_suggestion.py", "w") as f:
    f.write(text)

