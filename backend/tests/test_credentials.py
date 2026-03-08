import pytest
from services.credential_manager import store_credentials, get_credentials, clear_credentials
from error_envelope import ArchmorphException
import uuid

def test_credential_store_lifecycle():
    session_token = f"test-sess-{uuid.uuid4()}"
    creds = {"access_key_id": "AKIA123", "secret_access_key": "SEC1"}
    
    # store
    store_credentials(session_token, provider="aws", creds=creds)
    
    # get
    retrieved = get_credentials(session_token, expected_provider="aws")
    assert retrieved["access_key_id"] == "AKIA123"
    assert retrieved["secret_access_key"] == "SEC1"
    
    # Mismatched provider
    with pytest.raises(ArchmorphException) as exc:
        get_credentials(session_token, expected_provider="azure")
    assert exc.value.status_code == 400
    
    # clear
    clear_credentials(session_token)
    
    # gone
    with pytest.raises(ArchmorphException) as exc:
        get_credentials(session_token)
    assert exc.value.status_code == 401
