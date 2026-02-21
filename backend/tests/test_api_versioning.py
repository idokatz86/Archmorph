"""
Tests for Archmorph API Versioning Module
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api_versioning import (
    get_api_versions, create_versioned_router,
    API_V1, CURRENT_VERSION, SUPPORTED_VERSIONS,
)


class TestAPIVersioning:
    """Tests for API versioning functionality."""
    
    def test_get_api_versions_structure(self):
        """get_api_versions returns expected structure."""
        result = get_api_versions()
        
        assert "current_version" in result
        assert "supported_versions" in result
        assert "deprecated_versions" in result
        assert "versions" in result
        assert "migration_guide" in result
    
    def test_current_version_is_v1(self):
        """Current API version should be v1."""
        assert CURRENT_VERSION == API_V1
        assert CURRENT_VERSION == "v1"
    
    def test_v1_is_supported(self):
        """V1 should be in supported versions."""
        assert API_V1 in SUPPORTED_VERSIONS
    
    def test_version_info_contains_v1(self):
        """Version info should contain v1 details."""
        result = get_api_versions()
        
        assert API_V1 in result["versions"]
        v1_info = result["versions"][API_V1]
        
        assert "version" in v1_info
        assert "status" in v1_info
        assert "released" in v1_info
        assert "changes" in v1_info
        assert v1_info["status"] == "stable"
    
    def test_create_versioned_router(self):
        """create_versioned_router creates router with correct prefix."""
        router = create_versioned_router("v1")
        
        assert router.prefix == "/api/v1"
        assert "API V1" in router.tags
    
    def test_create_versioned_router_with_prefix(self):
        """create_versioned_router handles additional prefix."""
        router = create_versioned_router("v2", prefix="/admin")
        
        assert router.prefix == "/api/v2/admin"
        assert "API V2" in router.tags


class TestAPIVersionConstants:
    """Tests for API version constants."""
    
    def test_api_v1_constant(self):
        """API_V1 constant is correct."""
        assert API_V1 == "v1"
    
    def test_supported_versions_is_list(self):
        """SUPPORTED_VERSIONS is a list."""
        assert isinstance(SUPPORTED_VERSIONS, list)
        assert len(SUPPORTED_VERSIONS) >= 1
