from collections.abc import Iterator
from dataclasses import replace

import pytest
from botocore.exceptions import ClientError

from s3_kit import S3Config, S3KitError, S3Provider

# 連線到 examples/docker-compose.yaml 的 RustFS。
# 使用獨立的 bucket，測試前後清空時不會動到範例的資料。
CONFIG = S3Config(
    bucket="s3-kit-e2e",
    access_key="s3kit-local",
    secret_key="s3kit-local-secret",
    endpoint_url="http://127.0.0.1:19000",
    force_path_style=True,
)
PUBLIC_ENDPOINT_URL = "http://localhost:19000"
# 只用來測試 bucket 不存在的情況，測試不得建立它
MISSING_BUCKET = "s3-kit-e2e-missing"


def _clear(provider: S3Provider) -> None:
    for key in list(provider.list_keys()):
        provider.delete_object(key)


def _bucket_exists(provider: S3Provider, bucket: str) -> bool:
    # 直接使用 boto3 確認，避免依賴受測的錯誤轉換
    try:
        provider._client.head_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] in {"404", "NoSuchBucket"}:
            return False
        raise
    return True


@pytest.fixture(scope="session")
def rustfs_provider() -> S3Provider:
    provider = S3Provider(CONFIG)
    try:
        provider.ensure_bucket()
    except S3KitError as error:
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


@pytest.fixture
def rustfs_config() -> S3Config:
    return CONFIG


@pytest.fixture
def public_endpoint_provider(provider: S3Provider) -> S3Provider:
    """用另一個也連得到 RustFS 的位址當對外位址，模擬內外位址不同的部署。"""
    return S3Provider(replace(CONFIG, public_endpoint_url=PUBLIC_ENDPOINT_URL))


@pytest.fixture
def missing_bucket_config(rustfs_provider: S3Provider) -> Iterator[S3Config]:
    """指向不存在的 bucket，測試前後都確認它沒有被建立。"""
    if _bucket_exists(rustfs_provider, MISSING_BUCKET):
        pytest.fail(f"bucket {MISSING_BUCKET} 不應存在，請先手動刪除它")
    yield replace(CONFIG, bucket=MISSING_BUCKET)
    if _bucket_exists(rustfs_provider, MISSING_BUCKET):
        pytest.fail(f"測試建立了 bucket {MISSING_BUCKET}，被拒絕的操作不應留下副作用")


@pytest.fixture
def missing_bucket_provider(missing_bucket_config: S3Config) -> S3Provider:
    return S3Provider(missing_bucket_config)
