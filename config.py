"""
Configuration Management - 配置管理模块

提供统一的配置管理，支持环境变量、.env 文件和默认值

使用方法:
    from config import Config

    # 获取配置
    akshare_path = Config.get_akshare_path()
    api_key = Config.get_api_key("TAVILY_API_KEY")

    # 验证配置
    Config.validate()
"""

import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class Config:
    """
    配置管理类

    配置优先级:
    1. 环境变量 (最高优先级)
    2. .env 文件
    3. 默认值
    """

    # === 路径配置 ===
    # 基础路径，可通过 COMPANY_DEEP_ANALYSIS_ROOT 环境变量覆盖
    root_path: str = field(
        default_factory=lambda: os.getenv(
            "COMPANY_DEEP_ANALYSIS_ROOT",
            str(Path(__file__).parent.parent)
        )
    )

    # 数据源路径 (可通过环境变量覆盖)
    akshare_docs_path: str = field(
        default_factory=lambda: os.getenv(
            "AKSHARE_DOCS_PATH",
            "/root/.openclaw/workspace/akshare_docs"
        )
    )

    xueqiu_analyzer_path: str = field(
        default_factory=lambda: os.getenv(
            "XUEQIU_ANALYZER_PATH",
            "/root/.openclaw/workspace/xueqiu-analyzer-skill/scripts"
        )
    )

    link_collector_path: str = field(
        default_factory=lambda: os.getenv(
            "LINK_COLLECTOR_PATH",
            "/root/.openclaw/workspace/link-collector"
        )
    )

    # === API Keys ===
    tavily_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("TAVILY_API_KEY")
    )

    exa_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("EXA_API_KEY")
    )

    dashscope_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("DASHSCOPE_API_KEY")
    )

    openai_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )

    # === LLM 配置 ===
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "glm-5")
    )

    llm_base_url: Optional[str] = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL")
    )

    # === 分析配置 ===
    default_years: int = field(
        default_factory=lambda: int(os.getenv("DEFAULT_YEARS", "5"))
    )

    default_market: str = field(
        default_factory=lambda: os.getenv("DEFAULT_MARKET", "A 股")
    )

    # === 输出配置 ===
    output_dir: str = field(
        default_factory=lambda: os.getenv("OUTPUT_DIR", "/tmp/company_analysis")
    )

    create_latest_link: bool = field(
        default_factory=lambda: os.getenv("CREATE_LATEST_LINK", "true").lower() == "true"
    )

    # === 日志配置 ===
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )

    log_file: Optional[str] = field(
        default_factory=lambda: os.getenv("LOG_FILE")
    )

    # === 功能开关 ===
    enable_xueqiu: bool = field(
        default_factory=lambda: os.getenv("ENABLE_XUEQIU", "true").lower() == "true"
    )

    enable_news_search: bool = field(
        default_factory=lambda: os.getenv("ENABLE_NEWS_SEARCH", "true").lower() == "true"
    )

    enable_local_retrieval: bool = field(
        default_factory=lambda: os.getenv("ENABLE_LOCAL_RETRIEVAL", "true").lower() == "true"
    )

    # === 性能配置 ===
    request_timeout: int = field(
        default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT", "30"))
    )

    max_retries: int = field(
        default_factory=lambda: int(os.getenv("MAX_RETRIES", "3"))
    )

    cache_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "3600"))
    )

    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量加载配置"""
        return cls()

    @classmethod
    def load_dotenv(cls, env_path: Optional[str] = None) -> None:
        """
        加载 .env 文件

        Args:
            env_path: .env 文件路径，默认项目根目录/.env
        """
        from dotenv import load_dotenv

        if env_path is None:
            # 尝试多个可能的位置
            possible_paths = [
                Path(__file__).parent.parent / ".env",
                Path(__file__).parent / ".env",
                Path.home() / ".company_deep_analysis" / ".env",
            ]

            for path in possible_paths:
                if path.exists():
                    env_path = str(path)
                    break

        if env_path and Path(env_path).exists():
            load_dotenv(env_path)

    def get_akshare_path(self) -> str:
        """获取 AkShare 路径"""
        return self.akshare_docs_path

    def get_xueqiu_path(self) -> str:
        """获取雪球分析器路径"""
        return self.xueqiu_analyzer_path

    def get_link_collector_path(self) -> str:
        """获取本地知识库路径"""
        return self.link_collector_path

    def get_api_key(self, key_name: str) -> Optional[str]:
        """
        获取 API Key

        Args:
            key_name: API Key 名称

        Returns:
            API Key 值，不存在返回 None
        """
        key_mapping = {
            "TAVILY_API_KEY": self.tavily_api_key,
            "EXA_API_KEY": self.exa_api_key,
            "DASHSCOPE_API_KEY": self.dashscope_api_key,
            "OPENAI_API_KEY": self.openai_api_key,
        }
        return key_mapping.get(key_name)

    def get_llm_config(self) -> dict:
        """获取 LLM 配置"""
        return {
            "model": self.llm_model,
            "base_url": self.llm_base_url,
            "api_key": self.dashscope_api_key or self.openai_api_key,
        }

    def validate(self) -> tuple[bool, list[str]]:
        """
        验证配置

        Returns:
            (是否有效，错误信息列表)
        """
        errors = []

        # 检查必需的路径
        required_paths = [
            ("AkShare Docs", self.akshare_docs_path),
            ("Xueqiu Analyzer", self.xueqiu_analyzer_path),
        ]

        for name, path in required_paths:
            if not Path(path).exists():
                errors.append(f"{name} 路径不存在：{path}")

        # 检查至少有一个 LLM API Key
        if not self.dashscope_api_key and not self.openai_api_key:
            errors.append("需要配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY")

        return len(errors) == 0, errors

    def get_enabled_features(self) -> list[str]:
        """获取已启用的功能列表"""
        features = []

        if self.enable_xueqiu:
            features.append("雪球舆情")

        if self.tavily_api_key or self.exa_api_key:
            if self.enable_news_search:
                features.append("新闻搜索")

        if self.enable_local_retrieval:
            features.append("本地知识库")

        return features

    def __str__(self) -> str:
        """配置摘要 (不显示敏感信息)"""
        features = self.get_enabled_features()
        return f"""
=== Company Deep Analysis 配置 ===
根目录：{self.root_path}
启用的功能：{', '.join(features) if features else '无'}
默认年份：{self.default_years}
默认市场：{self.default_market}
输出目录：{self.output_dir}
日志级别：{self.log_level}
LLM 模型：{self.llm_model}
"""


# 全局配置实例
_global_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置实例"""
    global _global_config
    if _global_config is None:
        _global_config = Config.from_env()
    return _global_config


def reload_config() -> Config:
    """重新加载配置"""
    global _global_config
    _global_config = Config.from_env()
    return _global_config


# 便捷函数
def get_akshare_path() -> str:
    """获取 AkShare 路径"""
    return get_config().get_akshare_path()


def get_xueqiu_path() -> str:
    """获取雪球分析器路径"""
    return get_config().get_xueqiu_path()


def get_link_collector_path() -> str:
    """获取本地知识库路径"""
    return get_config().get_link_collector_path()


def get_api_key(key_name: str) -> Optional[str]:
    """获取 API Key"""
    return get_config().get_api_key(key_name)


def get_llm_config() -> dict:
    """获取 LLM 配置"""
    return get_config().get_llm_config()


def validate_config() -> tuple[bool, list[str]]:
    """验证配置"""
    return get_config().validate()
