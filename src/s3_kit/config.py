import os
from collections.abc import Mapping
from dataclasses import dataclass, field

_DEFAULT_REGION = "us-east-1"
_TRUE_VALUES = {"1", "true", "yes"}


@dataclass(frozen=True, slots=True)
class S3Config:
    """S3 連線設定，所有後端差異都由這裡傳入。

    endpoint_url 留空時連線到 AWS S3。
    """

    bucket: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    endpoint_url: str | None = None
    region: str = _DEFAULT_REGION
    force_path_style: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "S3Config":
        """從環境變數建立設定，缺少必要變數時拋出 KeyError。"""
        env = os.environ if env is None else env
        return cls(
            bucket=env["S3_BUCKET"],
            access_key=env["S3_ACCESS_KEY"],
            secret_key=env["S3_SECRET_KEY"],
            endpoint_url=env.get("S3_ENDPOINT_URL") or None,
            region=env.get("S3_REGION") or _DEFAULT_REGION,
            force_path_style=env.get("S3_FORCE_PATH_STYLE", "").lower() in _TRUE_VALUES,
        )
