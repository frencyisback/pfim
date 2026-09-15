"""Application configuration for PFIM Backend. Reads environment variables from .env using
pydantic-settings.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "PFIM"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Without .env, use a separate development database; never implicitly open the operational
    # database.
    database_url: str = "sqlite:///../data/pfim-dev.db"
    sqlite_busy_timeout_ms: int = Field(default=5000, ge=100, le=60_000)

    cors_origins: str = "http://localhost:5173"
    # Backend origins used by Swagger/ReDoc, separate from CORS. POST requests from /docs may
    # send Origin and must pass CSRF protection.
    backend_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # Defensive limits for all CSV uploads. Check bytes while reading chunks, before loading
    # the entire file; the parser checks row limits before any writes.
    #
    #
    csv_upload_max_bytes: int = 5 * 1024 * 1024
    csv_import_max_rows: int = 100_000
    trusted_hosts: str = "localhost,127.0.0.1"

    # Backup and restore have significant operational impact and require explicit deployment
    # configuration. Restore stays disabled without backups and an exact build revision.
    #
    backup_enabled: bool = False
    backup_copy_timeout_seconds: int = Field(default=60, ge=1, le=600)
    restore_enabled: bool = False
    restore_quiesce_timeout_seconds: int = Field(default=30, ge=1, le=300)
    # Intentionally no default: the revision is a build artifact and must be configured with
    # BACKUP_ENABLED, rather than hardcoded.
    expected_alembic_revision: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def trusted_hosts_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @property
    def backend_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.backend_origins.split(",") if origin.strip()]

    @property
    def mutation_origins_list(self) -> list[str]:
        return list(dict.fromkeys([*self.cors_origins_list, *self.backend_origins_list]))


settings = Settings()
