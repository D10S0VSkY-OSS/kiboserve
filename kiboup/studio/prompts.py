"""Prompt management for KiboStudio."""

from typing import Dict, List, Optional

from kiboup.studio.db import SQLiteStore
from kiboup.studio.entities import PromptTemplate, PromptVersion, _new_id, _utc_now


class PromptStore:
    """CRUD operations for prompt templates and versions."""

    def __init__(self, store: SQLiteStore):
        self._store = store

    def create_prompt(
        self,
        name: str,
        description: str = "",
        tags: Optional[List[str]] = None,
        content: str = "",
        model_config: Optional[Dict] = None,
        variables: Optional[List[str]] = None,
    ) -> PromptTemplate:
        """Create a new prompt template with an initial version."""
        prompt = PromptTemplate(
            prompt_id=_new_id(),
            name=name,
            description=description,
            tags=tags or [],
            active_version=1,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        self._store.save_prompt(prompt)

        version = PromptVersion(
            version_id=_new_id(),
            prompt_id=prompt.prompt_id,
            version=1,
            content=content,
            model_config=model_config or {},
            variables=variables or [],
            is_active=True,
            created_at=_utc_now(),
        )
        self._store.save_prompt_version(version)

        return prompt

    def get_prompt(self, prompt_id: str) -> Optional[PromptTemplate]:
        return self._store.get_prompt(prompt_id)

    def get_prompt_by_name(self, name: str) -> Optional[PromptTemplate]:
        return self._store.get_prompt_by_name(name)

    def list_prompts(self) -> List[PromptTemplate]:
        return self._store.list_prompts()

    def update_prompt(
        self,
        prompt_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[PromptTemplate]:
        """Update prompt metadata (not content - use create_version for that)."""
        prompt = self._store.get_prompt(prompt_id)
        if not prompt:
            return None
        if name is not None:
            prompt.name = name
        if description is not None:
            prompt.description = description
        if tags is not None:
            prompt.tags = tags
        prompt.updated_at = _utc_now()
        self._store.save_prompt(prompt)
        return prompt

    def delete_prompt(self, prompt_id: str) -> bool:
        return self._store.delete_prompt(prompt_id)

    def create_version(
        self,
        prompt_id: str,
        content: str,
        model_config: Optional[Dict] = None,
        variables: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        activate: bool = False,
    ) -> Optional[PromptVersion]:
        """Create a new version for an existing prompt."""
        prompt = self._store.get_prompt(prompt_id)
        if not prompt:
            return None

        versions = self._store.list_prompt_versions(prompt_id)
        next_version = max((v.version for v in versions), default=0) + 1

        version = PromptVersion(
            version_id=_new_id(),
            prompt_id=prompt_id,
            version=next_version,
            content=content,
            model_config=model_config or {},
            variables=variables or [],
            metadata=metadata or {},
            is_active=activate,
            created_at=_utc_now(),
        )

        if activate:
            self._deactivate_all(prompt_id)
            version.is_active = True
            prompt.active_version = next_version
            prompt.updated_at = _utc_now()
            self._store.save_prompt(prompt)

        self._store.save_prompt_version(version)
        return version

    def list_versions(self, prompt_id: str) -> List[PromptVersion]:
        return self._store.list_prompt_versions(prompt_id)

    def activate_version(self, prompt_id: str, version_number: int) -> bool:
        """Activate a specific version (deactivates all others)."""
        versions = self._store.list_prompt_versions(prompt_id)
        target = None
        for v in versions:
            if v.version == version_number:
                target = v
                break
        if not target:
            return False

        self._deactivate_all(prompt_id)
        target.is_active = True
        self._store.save_prompt_version(target)

        prompt = self._store.get_prompt(prompt_id)
        if prompt:
            prompt.active_version = version_number
            prompt.updated_at = _utc_now()
            self._store.save_prompt(prompt)

        return True

    def get_active_content(self, prompt_name: str) -> Optional[Dict]:
        """Get the active version content for a prompt by name.

        Returns dict with 'content', 'model_config', 'variables', 'version'.
        """
        prompt = self._store.get_prompt_by_name(prompt_name)
        if not prompt:
            return None
        version = self._store.get_active_version(prompt.prompt_id)
        if not version:
            return None
        return {
            "prompt_id": prompt.prompt_id,
            "name": prompt.name,
            "content": version.content,
            "model_config": version.model_config,
            "variables": version.variables,
            "version": version.version,
        }

    def _deactivate_all(self, prompt_id: str):
        """Deactivate all versions of a prompt."""
        versions = self._store.list_prompt_versions(prompt_id)
        for v in versions:
            if v.is_active:
                v.is_active = False
                self._store.save_prompt_version(v)
