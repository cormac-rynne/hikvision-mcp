from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .adapter import CameraAdapter, GenericHikvisionAdapter
from .isapi import IsapiClient
from .models import CameraIdentity

type AdapterFactory = Callable[[IsapiClient], CameraAdapter]
type IdentityMatcher = Callable[[CameraIdentity], bool]


@dataclass(frozen=True)
class AdapterRegistration:
    name: str
    matches: IdentityMatcher
    factory: AdapterFactory


class AdapterRegistry:
    """Select model/firmware adapters without branching in service or MCP layers."""

    def __init__(self, default_factory: AdapterFactory = GenericHikvisionAdapter) -> None:
        self._default_factory = default_factory
        self._registrations: list[AdapterRegistration] = []

    def register(self, registration: AdapterRegistration) -> None:
        if any(item.name == registration.name for item in self._registrations):
            raise ValueError(f"Adapter registration '{registration.name}' already exists")
        self._registrations.append(registration)

    async def create(self, client: IsapiClient, alias: str) -> CameraAdapter:
        if not self._registrations:
            return self._default_factory(client)
        identity = await GenericHikvisionAdapter(client).identity(alias)
        for registration in self._registrations:
            if registration.matches(identity):
                return registration.factory(client)
        return self._default_factory(client)


DEFAULT_ADAPTER_REGISTRY = AdapterRegistry()
