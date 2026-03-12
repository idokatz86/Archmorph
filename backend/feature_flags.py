"""
Archmorph Feature Flags — Lightweight feature flag management.

Supports:
  - Boolean on/off flags
  - Percentage-based rollout
  - User targeting (allowlist)
  - Environment targeting
  - JSON override via FEATURE_FLAGS_JSON env var
  - In-memory flag store with runtime updates
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from threading import Lock
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ENVIRONMENT = os.getenv("ENVIRONMENT", "production")


@dataclass
class Flag:
    """A single feature flag with rollout configuration."""

    name: str
    enabled: bool = False
    description: str = ""
    rollout_percentage: int = 100  # 0-100; applies only when enabled=True
    target_users: List[str] = field(default_factory=list)
    target_environments: List[str] = field(default_factory=list)  # empty = all envs

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Default flags ────────────────────────────────────────────
DEFAULT_FLAGS: Dict[str, Flag] = {
    "new_ai_model": Flag(
        name="new_ai_model",
        enabled=False,
        description="Use next-gen AI model for architecture translation",
    ),
    "roadmap_v2": Flag(
        name="roadmap_v2",
        enabled=False,
        description="Enable redesigned roadmap generation (v2)",
    ),
    "export_pptx": Flag(
        name="export_pptx",
        enabled=True,
        description="Enable PowerPoint export for architecture diagrams",
    ),
    "dark_mode": Flag(
        name="dark_mode",
        enabled=True,
        description="Enable dark mode toggle in the frontend",
    ),
}


class FeatureFlags:
    """Thread-safe in-memory feature flag store."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._flags: Dict[str, Flag] = {}
        self._load_defaults()
        self._apply_env_overrides()

    # ── Loading ──────────────────────────────────────────────

    def _load_defaults(self) -> None:
        """Seed the store with default flags."""
        for name, flag in DEFAULT_FLAGS.items():
            self._flags[name] = Flag(**asdict(flag))

    def _apply_env_overrides(self) -> None:
        """
        Apply overrides from individual env vars and the JSON blob.

        Individual: FEATURE_FLAG_<NAME>=true|false  (e.g. FEATURE_FLAG_DARK_MODE=false)
        JSON blob:  FEATURE_FLAGS_JSON='{"new_ai_model": {"enabled": true, "rollout_percentage": 50}}'
        """
        self._apply_individual_env_overrides()
        self._apply_json_override()

    def _apply_individual_env_overrides(self) -> None:
        """Apply FEATURE_FLAG_<NAME>=true|false overrides from the environment."""
        for name in list(self._flags.keys()):
            env_key = f"FEATURE_FLAG_{name.upper()}"
            env_val = os.getenv(env_key)
            if env_val is None:
                continue
            self._flags[name].enabled = env_val.lower() in ("true", "1", "yes")
            logger.info("Flag '%s' overridden by env %s=%s", name, env_key, env_val)

    def _apply_json_override(self) -> None:
        """Apply FEATURE_FLAGS_JSON overrides (higher priority than individual vars)."""
        json_str = os.getenv("FEATURE_FLAGS_JSON")
        if not json_str:
            return

        try:
            overrides = json.loads(json_str)
            for name, cfg in overrides.items():
                self._apply_single_json_override(name, cfg)
            logger.info("Applied JSON overrides for %d flags", len(overrides))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Invalid FEATURE_FLAGS_JSON: %s", exc)

    def _apply_single_json_override(self, name: str, cfg: Any) -> None:
        """Apply JSON override for a single flag definition."""
        if name in self._flags:
            self._update_existing_flag_from_json(name, cfg)
            return

        self._create_flag_from_json(name, cfg)

    def _update_existing_flag_from_json(self, name: str, cfg: Any) -> None:
        """Update an existing flag using parsed JSON data."""
        if isinstance(cfg, dict):
            for key, value in cfg.items():
                if hasattr(self._flags[name], key):
                    setattr(self._flags[name], key, value)
            return

        if isinstance(cfg, bool):
            self._flags[name].enabled = cfg

    def _create_flag_from_json(self, name: str, cfg: Any) -> None:
        """Create a new flag using parsed JSON data."""
        if isinstance(cfg, dict):
            self._flags[name] = Flag(
                name=name,
                **{k: v for k, v in cfg.items() if k in Flag.__dataclass_fields__}
            )
            return

        self._flags[name] = Flag(name=name, enabled=bool(cfg))

    # ── Query ────────────────────────────────────────────────

    def is_enabled(self, flag_name: str, user: Optional[str] = None) -> bool:
        """
        Check if a feature flag is enabled for the given context.

        Resolution order:
          1. Flag must exist and be globally enabled
          2. Environment targeting (if specified, current env must match)
          3. User targeting (if user in allowlist, always enabled)
          4. Percentage rollout (deterministic hash of user+flag)
        """
        # Snapshot all flag fields under lock to avoid TOCTOU race (#132)
        with self._lock:
            flag = self._flags.get(flag_name)
            if flag is None:
                return False
            enabled = flag.enabled
            target_envs = list(flag.target_environments)
            target_users = list(flag.target_users)
            rollout_pct = flag.rollout_percentage

        if not enabled:
            return False

        # Environment targeting
        if target_envs and ENVIRONMENT not in target_envs:
            return False

        # User allowlist — always enabled for targeted users
        if user and user in target_users:
            return True

        # Percentage rollout
        if rollout_pct < 100:
            if user is None:
                # No user context: use flag-level probability (deterministic per flag)
                bucket = int(hashlib.sha256(flag_name.encode()).hexdigest()[:8], 16) % 100  # nosec B324  # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
                return bucket < rollout_pct
            # Deterministic bucket from user+flag
            key = f"{user}:{flag_name}"
            bucket = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 100  # nosec B324  # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
            return bucket < rollout_pct

        return True

    # ── Management ───────────────────────────────────────────

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Return all flags as serialisable dicts."""
        with self._lock:
            return {name: flag.to_dict() for name, flag in self._flags.items()}

    def get_flag(self, name: str) -> Optional[Dict[str, Any]]:
        """Return a single flag or None."""
        with self._lock:
            flag = self._flags.get(name)
            return flag.to_dict() if flag else None

    def update_flag(self, name: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Update an existing flag.  Returns updated flag dict, or None if not found.
        Only whitelisted fields can be updated.
        """
        allowed = {"enabled", "description", "rollout_percentage", "target_users", "target_environments"}
        with self._lock:
            flag = self._flags.get(name)
            if flag is None:
                return None
            for k, v in updates.items():
                if k in allowed and hasattr(flag, k):
                    setattr(flag, k, v)
            logger.info("Flag '%s' updated: %s", name, {k: v for k, v in updates.items() if k in allowed})
            return flag.to_dict()

    def create_flag(self, name: str, **kwargs: Any) -> Dict[str, Any]:
        """Create a new flag (or overwrite existing)."""
        filtered = {k: v for k, v in kwargs.items() if k in Flag.__dataclass_fields__}
        with self._lock:
            self._flags[name] = Flag(name=name, **filtered)
            return self._flags[name].to_dict()


# ── Module-level singleton ───────────────────────────────────
_flags_instance: Optional[FeatureFlags] = None
_init_lock = Lock()


def get_feature_flags() -> FeatureFlags:
    """Return the global FeatureFlags singleton (lazy init)."""
    global _flags_instance
    if _flags_instance is None:
        with _init_lock:
            if _flags_instance is None:
                _flags_instance = FeatureFlags()
    return _flags_instance


def is_enabled(flag_name: str, user: Optional[str] = None) -> bool:
    """Convenience shortcut for FeatureFlags.is_enabled()."""
    return get_feature_flags().is_enabled(flag_name, user)
