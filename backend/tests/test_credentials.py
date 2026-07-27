import pytest
from services.credential_manager import (
    clear_credentials,
    get_credentials,
    purge_scope_credentials,
    scope_credentials_absent,
    store_credentials,
)
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


def test_credential_purge_is_owner_tenant_scoped():
    first = f"test-sess-{uuid.uuid4()}"
    second = f"test-sess-{uuid.uuid4()}"
    store_credentials(
        first,
        provider="aws",
        creds={"access_key_id": "first"},
        owner_user_id="owner-a",
        tenant_id="tenant-a",
    )
    store_credentials(
        second,
        provider="aws",
        creds={"access_key_id": "second"},
        owner_user_id="owner-b",
        tenant_id="tenant-b",
    )

    assert purge_scope_credentials("owner-a", "tenant-a") == 1
    assert scope_credentials_absent("owner-a", "tenant-a") is True
    assert get_credentials(second)["access_key_id"] == "second"
    clear_credentials(second)
