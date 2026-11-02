from collections.abc import Iterator

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from s3_kit import S3Config, S3Provider

# 連線到 examples/docker-compose.yaml 的 RustFS。
# 使用獨立的 bucket，測試前後清空時不會動到範例的資料。
CONFIG = S3Config(
    bucket="s3-kit-e2e",
    access_key="s3kit-local",
    secret_key="s3kit-local-secret",
    endpoint_url="http://127.0.0.1:19000",
    force_path_style=True,
)


def _clear(provider: S3Provider) -> None:
    for key in list(provider.list_keys()):
        provider.delete_object(key)


@pytest.fixture(scope="session")
def rustfs_provider() -> S3Provider:
    provider = S3Provider(CONFIG)
    try:
        provider.ensure_bucket()
    except (BotoCoreError, ClientError) as error:
        pytest.fail(
            f"無法連線到 RustFS（{CONFIG.endpoint_url}），"
            f"請先在 examples 資料夾執行 docker compose up -d：{error}"
        )
    return provider


@pytest.fixture
def provider(rustfs_provider: S3Provider) -> Iterator[S3Provider]:
    _clear(rustfs_provider)
    yield rustfs_provider
    _clear(rustfs_provider)
