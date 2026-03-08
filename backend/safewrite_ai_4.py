import re
with open("tests/test_ai_suggestion.py", "r") as f:
    text = f.read()

# remove old test_suggest_mapping_*
text = re.sub(r'@patch\("ai_suggestion\.cached_chat_completion"\)\s*def test_suggest_mapping_fast_path.*?(?=@patch|def test_)', '', text, flags=re.DOTALL)
text = re.sub(r'def test_suggest_mapping_fast_path.*?(?=@patch|def test_)', '', text, flags=re.DOTALL)

with open("tests/test_ai_suggestion.py", "w") as f:
    f.write(text)
