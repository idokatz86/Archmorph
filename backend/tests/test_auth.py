"""
Tests for Authentication Module
"""


from auth import (
    User, AuthProvider, UserTier, UsageQuota,
    get_anonymous_user, generate_session_token, get_user_from_session,
    capture_lead, get_leads_summary, is_auth_enabled, get_auth_config,
    LEAD_STORE,
)


class TestUsageQuota:
    """Tests for UsageQuota class."""
    
    def test_free_tier_limits(self):
        quota = UsageQuota.for_tier(UserTier.FREE)
        assert quota.analyses_per_month == 5
        assert quota.iac_downloads_per_month == 3
        assert quota.hld_generations_per_month == 2
        assert quota.share_links_per_month == 3
    
    def test_team_tier_limits(self):
        quota = UsageQuota.for_tier(UserTier.TEAM)
        assert quota.analyses_per_month == 50
        assert quota.iac_downloads_per_month == 30
    
    def test_enterprise_tier_limits(self):
        quota = UsageQuota.for_tier(UserTier.ENTERPRISE)
        assert quota.analyses_per_month == 10000


class TestUser:
    """Tests for User class."""
    
    def test_user_creation(self):
        user = User(id="test-123", email="test@example.com", name="Test User")
        assert user.id == "test-123"
        assert user.email == "test@example.com"
        assert user.tier == UserTier.FREE
        assert user.analyses_used == 0
    
    def test_check_quota_allowed(self):
        user = User(id="test-123")
        result = user.check_quota("analyze")
        assert result["allowed"] is True
        assert result["remaining"] == 5
    
    def test_check_quota_exhausted(self):
        user = User(id="test-123", analyses_used=5)
        result = user.check_quota("analyze")
        assert result["allowed"] is False
        assert result["remaining"] == 0
    
    def test_increment_usage(self):
        user = User(id="test-123")
        assert user.analyses_used == 0
        
        result = user.increment_usage("analyze")
        assert result is True
        assert user.analyses_used == 1
    
    def test_increment_usage_exceeded(self):
        user = User(id="test-123", analyses_used=5)
        result = user.increment_usage("analyze")
        assert result is False
        assert user.analyses_used == 5
    
    def test_reset_monthly_usage(self):
        user = User(
            id="test-123",
            analyses_used=5,
            iac_downloads_used=3,
        )
        user.reset_monthly_usage()
        assert user.analyses_used == 0
        assert user.iac_downloads_used == 0
    
    def test_to_dict(self):
        user = User(id="test-123", email="test@example.com")
        data = user.to_dict()
        assert data["id"] == "test-123"
        assert data["email"] == "test@example.com"
        assert "usage" in data
        assert "analyses" in data["usage"]


class TestAnonymousUser:
    """Tests for anonymous user handling."""
    
    def test_get_anonymous_user(self):
        user = get_anonymous_user("192.168.1.1")
        assert user.provider == AuthProvider.ANONYMOUS
        assert user.id.startswith("anon_")
    
    def test_anonymous_user_consistent(self):
        user1 = get_anonymous_user("192.168.1.1")
        user2 = get_anonymous_user("192.168.1.1")
        assert user1.id == user2.id
    
    def test_different_ips_different_users(self):
        user1 = get_anonymous_user("192.168.1.1")
        user2 = get_anonymous_user("192.168.1.2")
        assert user1.id != user2.id


class TestSessionManagement:
    """Tests for session token management."""
    
    def test_generate_session_token(self):
        user = User(id="test-123")
        token = generate_session_token(user)
        assert len(token) > 20
    
    def test_get_user_from_session(self):
        user = User(id="test-123", email="test@example.com")
        token = generate_session_token(user)
        
        retrieved = get_user_from_session(token)
        assert retrieved is not None
        assert retrieved.id == user.id
    
    def test_invalid_session_token(self):
        result = get_user_from_session("invalid-token")
        assert result is None


class TestLeadCapture:
    """Tests for lead capture functionality."""
    
    def setup_method(self):
        LEAD_STORE.clear()
    
    def test_capture_lead(self):
        lead = capture_lead(
            email="lead@example.com",
            diagram_id="diag-123",
            action="iac_download",
        )
        assert lead.email == "lead@example.com"
        assert lead.action == "iac_download"
    
    def test_capture_lead_with_details(self):
        lead = capture_lead(
            email="lead@example.com",
            diagram_id="diag-123",
            action="hld_download",
            company="ACME Corp",
            role="Cloud Architect",
            marketing_consent=True,
        )
        assert lead.company == "ACME Corp"
        assert lead.marketing_consent is True
    
    def test_get_leads_summary(self):
        capture_lead("a@example.com", "d1", "iac_download")
        capture_lead("b@example.com", "d2", "hld_download", marketing_consent=True)
        
        summary = get_leads_summary()
        assert summary["total_leads"] == 2
        assert summary["with_marketing_consent"] == 1


class TestAuthConfig:
    """Tests for authentication configuration."""
    
    def test_is_auth_enabled_default(self):
        # By default, auth is disabled (no env vars)
        result = is_auth_enabled()
        assert isinstance(result, bool)
    
    def test_get_auth_config(self):
        config = get_auth_config()
        assert "auth_enabled" in config
        assert "providers" in config
        assert "azure_ad_b2c" in config["providers"]
        assert "github" in config["providers"]
        assert "free_tier_limits" in config
