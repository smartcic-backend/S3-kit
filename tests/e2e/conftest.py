import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from s3_kit import S3Config, S3Provider

COMPOSE = ["docker", "compose", "-f", str(Path(__file__).parent / "docker-compose.yaml")]


@pytest.fixture(scope="session")
def rustfs_config() -> Iterator[S3Config]:
    """啟動測試專用的 RustFS，所有測試結束後連同資料一起清除。"""
    subprocess.run([*COMPOSE, "up", "--detach", "--wait"], check=True)
    try:
        yield S3Config(
            bucket="s3-kit-e2e",
            access_key="e2e-access-key",
            secret_key="e2e-secret-key",
            endpoint_url="http://127.0.0.1:19000",
            force_path_style=True,
        )
    finally:
        subprocess.run([*COMPOSE, "down", "--volumes"], check=True)


@pytest.fixture
def provider(rustfs_config: S3Config) -> Iterator[S3Provider]:
    provider = S3Provider(rustfs_config)
    provider.ensure_bucket()
    yield provider
    for key in list(provider.list_keys()):
        provider.delete_object(key)
