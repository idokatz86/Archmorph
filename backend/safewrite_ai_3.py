import re

with open("tests/test_ai_suggestion.py", "r") as f:
    content = f.read()

# Replace mock setup
new_test_suggest_mapping_gpt_path = """
@patch("ai_suggestion.get_openai_client")
def test_suggest_mapping_gpt_path(mock_get_client):
    # Setup mock for get_openai_client().chat.completions.create()
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_message = MagicMock()
    
    mock_message.content = json.dumps({
        "target_service": "Azure App Service",
        "confidence_score": 88,
        "reasoning": "Standard app hosting.",
        "common_gaps": ["None"],
        "cost_implications": "Minimal",
        "doc_links": ["https://learn.microsoft.com/app-service"]
    })
    mock_response.choices = [MagicMock(message=mock_message)]
    mock_client.chat.completions.create.return_value = mock_response
    mock_get_client.return_value = mock_client
    
    res = suggest_mapping("AWS", "UnknownService", ["S3", "EC2"])
    
    assert res["target_service"] == "Azure App Service"
    assert res["confidence_score"] == 88
    mock_get_client.assert_called_once()
    mock_client.chat.completions.create.assert_called_once()
"""

new_test_suggest_mapping_gpt_failure = """
@patch("ai_suggestion.get_openai_client")
def test_suggest_mapping_gpt_failure(mock_get_client):
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API Error")
    mock_get_client.return_value = mock_client
    
    res = suggest_mapping("AWS", "UnknownService", [])
    assert res["target_service"] == "Unknown Resource/No Match"
    assert res["confidence_score"] == 0
"""

content = re.sub(r'@patch\("ai_suggestion\.get_openai_client"\)\ndef test_suggest_mapping_gpt_path.*?(?=@patch\("ai_suggestion\.get_openai_client"\)\ndef test_suggest_mapping_gpt_failure)', new_test_suggest_mapping_gpt_path + "\n", content, flags=re.DOTALL)

content = re.sub(r'@patch\("ai_suggestion\.get_openai_client"\)\ndef test_suggest_mapping_gpt_failure.*', new_test_suggest_mapping_gpt_failure + "\n", content, flags=re.DOTALL)

with open("tests/test_ai_suggestion.py", "w") as f:
    f.write(content)
