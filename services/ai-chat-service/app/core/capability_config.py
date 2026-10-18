"""Capability integration settings; explicit legacy mode never activates on failure."""
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class CapabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    capability_service_name: str = "capability-service"
    capability_catalog_mode: Literal["internal", "market"] = "internal"


capability_settings = CapabilitySettings()
