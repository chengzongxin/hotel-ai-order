from functools import cached_property
import os

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv(".env", override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            dotenv_settings,
            env_settings,
            file_secret_settings,
        )

    app_name: str = "LangGraph FastAPI Agent"
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    debug_trace_enabled: bool = False

    openai_api_key: str = Field(default="", repr=False)
    openai_base_url: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = 0.2

    langsmith_tracing: bool = False
    langsmith_api_key: str = Field(default="", repr=False)
    langsmith_project: str = "hotel-ai-order-agent"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    redis_url: str = "redis://localhost:6379/0"
    redis_ttl_seconds: int = 86_400

    sqlite_memory_path: str = "data/agent_memory.sqlite3"
    conversation_summary_max_messages: int = 12

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "agent_db"
    postgres_user: str = "agent_user"
    postgres_password: str = Field(default="agent_password", repr=False)
    postgres_enabled: bool = False

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = Field(default="", repr=False)
    qdrant_collection: str = "agent_knowledge"

    spu_excel_path: str = "assets/spu.xlsx"
    embedding_cache_dir: str = "data/embedding_cache"
    qwen_embedding_model: str = "text-embedding-v4"
    qwen_embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_embedding_api_key: str = Field(default="", repr=False)
    qwen_embedding_batch_size: int = 10
    qwen_embedding_timeout_seconds: float = 30.0

    product_search_threshold: float = 0.3

    tavily_api_key: str = Field(default="", repr=False)

    admin_api_base_url: str = "https://userapp.hxcsz.com"
    login_profile_url: str = "http://192.168.2.223:18080/admin-api/system/user/profile/get"

    user_app_base_url: str = "https://userapp.hxcsz.com"
    user_app_submit_enabled: bool = True
    user_app_timeout_seconds: float = 30.0

    @cached_property
    def database_url(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def apply_runtime_environment(self) -> None:
        """把 .env 配置同步给依赖环境变量的第三方库。

        LangSmith 和部分 LangChain 组件会直接读取 os.environ，
        所以这里显式写入，确保项目 .env 优先于 shell 环境变量。
        """

        os.environ["LANGSMITH_TRACING"] = str(self.langsmith_tracing).lower()
        os.environ["LANGCHAIN_TRACING_V2"] = str(self.langsmith_tracing).lower()
        os.environ["LANGSMITH_PROJECT"] = self.langsmith_project
        os.environ["LANGCHAIN_PROJECT"] = self.langsmith_project
        os.environ["LANGSMITH_ENDPOINT"] = self.langsmith_endpoint

        if self.langsmith_api_key:
            os.environ["LANGSMITH_API_KEY"] = self.langsmith_api_key


settings = Settings()
settings.apply_runtime_environment()
