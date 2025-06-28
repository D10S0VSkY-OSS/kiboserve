"""Feature flags and parameter store for KiboStudio."""

from typing import Any, Dict, List, Optional

from kiboup.studio.db import SQLiteStore
from kiboup.studio.entities import FeatureFlag, Parameter, _new_id, _utc_now


class FeatureFlagService:
    """Manages feature flags and configuration parameters per agent."""

    def __init__(self, store: SQLiteStore):
        self._store = store

    # -- Feature flags --

    def set_flag(
        self,
        agent_id: str,
        name: str,
        enabled: bool,
        value: Any = None,
        description: str = "",
    ) -> FeatureFlag:
        """Create or update a feature flag."""
        existing = self._find_flag(agent_id, name)
        if existing:
            existing.enabled = enabled
            existing.value = value
            if description:
                existing.description = description
            existing.updated_at = _utc_now()
            self._store.save_flag(existing)
            return existing

        flag = FeatureFlag(
            flag_id=_new_id(),
            agent_id=agent_id,
            name=name,
            enabled=enabled,
            value=value,
            description=description,
            updated_at=_utc_now(),
        )
        self._store.save_flag(flag)
        return flag

    def get_flags(self, agent_id: str, include_global: bool = True) -> Dict[str, Any]:
        """Get all flags for an agent, optionally merged with global flags.

        Returns dict of {flag_name: {"enabled": bool, "value": any}}.
        """
        result: Dict[str, Any] = {}

        if include_global and agent_id != "_global":
            global_flags = self._store.get_flags("_global")
            for f in global_flags:
                result[f.name] = {"enabled": f.enabled, "value": f.value}

        agent_flags = self._store.get_flags(agent_id)
        for f in agent_flags:
            result[f.name] = {"enabled": f.enabled, "value": f.value}

        return result

    def get_flags_list(self, agent_id: str) -> List[FeatureFlag]:
        """Get raw flag objects for an agent."""
        return self._store.get_flags(agent_id)

    def delete_flag(self, flag_id: str) -> bool:
        return self._store.delete_flag(flag_id)

    def is_enabled(self, agent_id: str, flag_name: str, default: bool = False) -> bool:
        """Check if a specific flag is enabled (checks agent then global)."""
        agent_flags = self._store.get_flags(agent_id)
        for f in agent_flags:
            if f.name == flag_name:
                return f.enabled

        global_flags = self._store.get_flags("_global")
        for f in global_flags:
            if f.name == flag_name:
                return f.enabled

        return default

    # -- Parameters --

    def set_param(
        self,
        agent_id: str,
        name: str,
        value: Any,
        description: str = "",
    ) -> Parameter:
        """Create or update a parameter."""
        existing = self._find_param(agent_id, name)
        if existing:
            existing.value = value
            if description:
                existing.description = description
            existing.updated_at = _utc_now()
            self._store.save_param(existing)
            return existing

        param = Parameter(
            param_id=_new_id(),
            agent_id=agent_id,
            name=name,
            value=value,
            description=description,
            updated_at=_utc_now(),
        )
        self._store.save_param(param)
        return param

    def get_params(self, agent_id: str, include_global: bool = True) -> Dict[str, Any]:
        """Get all parameters for an agent, optionally merged with global.

        Returns dict of {param_name: value}.
        """
        result: Dict[str, Any] = {}

        if include_global and agent_id != "_global":
            global_params = self._store.get_params("_global")
            for p in global_params:
                result[p.name] = p.value

        agent_params = self._store.get_params(agent_id)
        for p in agent_params:
            result[p.name] = p.value

        return result

    def get_params_list(self, agent_id: str) -> List[Parameter]:
        """Get raw parameter objects for an agent."""
        return self._store.get_params(agent_id)

    def get_param_value(self, agent_id: str, param_name: str, default: Any = None) -> Any:
        """Get a single parameter value (checks agent then global)."""
        agent_params = self._store.get_params(agent_id)
        for p in agent_params:
            if p.name == param_name:
                return p.value

        global_params = self._store.get_params("_global")
        for p in global_params:
            if p.name == param_name:
                return p.value

        return default

    def delete_param(self, param_id: str) -> bool:
        return self._store.delete_param(param_id)

    # -- Internals --

    def _find_flag(self, agent_id: str, name: str) -> Optional[FeatureFlag]:
        flags = self._store.get_flags(agent_id)
        for f in flags:
            if f.name == name:
                return f
        return None

    def _find_param(self, agent_id: str, name: str) -> Optional[Parameter]:
        params = self._store.get_params(agent_id)
        for p in params:
            if p.name == name:
                return p
        return None
