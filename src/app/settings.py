from functools import cached_property
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict # Import SettingsConfigDict
from pathlib import Path
import json

class Settings(BaseSettings):

    POSTGRES_USER: str = Field(default="ft")
    POSTGRES_PASSWORD: str = Field(default="ftpass")
    POSTGRES_DB: str = Field(default="ftrade")
    POSTGRES_PORT: int = Field(default=5432)
    DATABASE_URL: str = Field(default="") # The direct URL, optional; will be read from env if set.


    freqtrade_config_path: Path = Field(
        default=Path("/user_data/config.json"),
        alias='FREQTRADE_CONFIG_PATH' # Map the variable to the model field
    )
    # `freqtrade_userdir` isn't in .env, keeping the default here:
    freqtrade_userdir: Path = Path("/user_data")
    
    # PYDANTIC V2 CONFIGURATION
    model_config = SettingsConfigDict(
        env_file='.env',
        case_sensitive=False,
        extra='ignore' # Silently ignore PGADMIN_ and other unused fields.
    )

    # CACHED PROPERTY (Adjusted to use the correctly mapped path)
    @cached_property
    def freqtrade_config(self) -> dict:
        """Loads the freqtrade config file."""
        # Use self.freqtrade_config_path which is mapped from FREQTRADE_CONFIG_PATH
        with open(self.freqtrade_config_path) as f:
            return json.load(f)

    @cached_property
    def get_sync_db_url(self) -> str:
        """Constructs the standard psycopg2 (synchronous) database URL."""
        # This uses the specific fields defined above, in case DATABASE_URL isn't set
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"db:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()