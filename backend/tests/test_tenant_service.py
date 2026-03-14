from unittest.mock import MagicMock
from services.tenant_service import _slugify, create_organization

def test_slugify():
    assert _slugify("Hello World!") == "hello-world"
    assert _slugify("  Acme  Corp  ") == "acme-corp"
    assert _slugify("Hello_World") == "hello-world"

def test_create_organization():
    db_mock = MagicMock()
    # Mocking that slug doesn't exist yet
    db_mock.query().filter().first.return_value = None
    
    # We will just verify it calls add and commit
    org = create_organization(db_mock, name="Test Org", owner_id="user1")
    assert org["name"] == "Test Org"
    assert org["slug"] == "test-org"
    assert org["plan"] == "free"
    
    # Verify commit
    assert db_mock.commit.called
