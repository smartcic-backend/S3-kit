import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TypeVar

_DEFAULT_REGION = "us-east-1"
_TRUE_VALUES = {"1", "true", "yes"}
_FALSE_VALUES = {"0", "false", "no"}

_Number = TypeVar("_Number", int, float)


@dataclass(frozen=True, slots=True)
class S3Config:
    """S3 連線設定，所有後端差異都由這裡傳入。

    endpoint_url 留空時連線到 AWS S3。
    public_endpoint_url 只用來產生預簽連結，留空時與 endpoint_url 相同。
    access_key 與 secret_key 必須同時提供或同時省略，省略時由 boto3 預設的憑證來源取得。
    connect_timeout、read_timeout、max_attempts 為 None 時沿用 botocore 的預設值。
    verify 為 False 時不驗證 TLS 憑證，為字串時代表 CA bundle 路徑。
    """

    bucket: str
    access_key: str | None = field(default=None, repr=False)
    secret_key: str | None = field(default=None, repr=False)
    endpoint_url: str | None = None
    region: str = _DEFAULT_REGION
    force_path_style: bool = False
    public_endpoint_url: str | None = None
    session_token: str | None = field(default=None, repr=False)
    connect_timeout: float | None = None
    read_timeout: float | None = None
    max_attempts: int | None = None
    verify: bool | str = True

    def __post_init__(self) -> None:
        if (self.access_key is None) != (self.secret_key is None):
            raise ValueError("access_key 與 secret_key 必須同時提供或同時省略")
        if self.session_token is not None and self.access_key is None:
            raise ValueError(
                "提供 session_token 時必須同時提供 access_key 與 secret_key"
            )
        for name in ("connect_timeout", "read_timeout"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} 必須大於 0：{value}")
        if self.max_attempts is not None and self.max_attempts < 1:
            raise ValueError(f"max_attempts 必須大於等於 1：{self.max_attempts}")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "S3Config":
        """從環境變數建立設定。缺少 S3_BUCKET 時拋出 KeyError，數字格式錯誤時拋出 ValueError。"""
        env = os.environ if env is None else env
        return cls(
            bucket=env["S3_BUCKET"],
            access_key=env.get("S3_ACCESS_KEY") or None,
            secret_key=env.get("S3_SECRET_KEY") or None,
            endpoint_url=env.get("S3_ENDPOINT_URL") or None,
            region=env.get("S3_REGION") or _DEFAULT_REGION,
            force_path_style=env.get("S3_FORCE_PATH_STYLE", "").lower() in _TRUE_VALUES,
            public_endpoint_url=env.get("S3_PUBLIC_ENDPOINT_URL") or None,
            session_token=env.get("S3_SESSION_TOKEN") or None,
            connect_timeout=_parse_number(env, "S3_CONNECT_TIMEOUT", float),
            read_timeout=_parse_number(env, "S3_READ_TIMEOUT", float),
            max_attempts=_parse_number(env, "S3_MAX_ATTEMPTS", int),
            # CA bundle 優先於 S3_VERIFY_SSL
            verify=env.get("S3_CA_BUNDLE")
            or env.get("S3_VERIFY_SSL", "").lower() not in _FALSE_VALUES,
        )


def _parse_number(
    env: Mapping[str, str], name: str, parse: Callable[[str], _Number]
) -> _Number | None:
    value = env.get(name)
    if not value:
        return None
    try:
        return parse(value)
    except ValueError as error:
        raise ValueError(f"{name} 的格式錯誤：{value}") from error
