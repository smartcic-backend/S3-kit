import pytest

from s3_kit import S3Config

REQUIRED_ENV = {
    "S3_BUCKET": "bucket",
    "S3_ACCESS_KEY": "access",
    "S3_SECRET_KEY": "secret",
}


def test_from_env_reads_all_values():
    config = S3Config.from_env(
        {
            **REQUIRED_ENV,
            "S3_ENDPOINT_URL": "http://rustfs:9000",
            "S3_REGION": "ap-northeast-1",
            "S3_FORCE_PATH_STYLE": "true",
        }
    )

    assert config == S3Config(
        bucket="bucket",
        access_key="access",
        secret_key="secret",
        endpoint_url="http://rustfs:9000",
        region="ap-northeast-1",
        force_path_style=True,
    )


def test_from_env_uses_defaults():
    config = S3Config.from_env(REQUIRED_ENV)

    assert config.endpoint_url is None
    assert config.region == "us-east-1"
    assert config.force_path_style is False


def test_from_env_treats_empty_values_as_unset():
    config = S3Config.from_env({**REQUIRED_ENV, "S3_ENDPOINT_URL": "", "S3_REGION": ""})

    assert config.endpoint_url is None
    assert config.region == "us-east-1"


@pytest.mark.parametrize("missing", REQUIRED_ENV)
def test_from_env_requires_values(missing):
    env = {key: value for key, value in REQUIRED_ENV.items() if key != missing}

    with pytest.raises(KeyError, match=missing):
        S3Config.from_env(env)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("", False),
    ],
)
def test_from_env_parses_force_path_style(value, expected):
    config = S3Config.from_env({**REQUIRED_ENV, "S3_FORCE_PATH_STYLE": value})

    assert config.force_path_style is expected


def test_repr_hides_credentials():
    config = S3Config(bucket="bucket", access_key="my-access", secret_key="my-secret")

    assert "my-access" not in repr(config)
    assert "my-secret" not in repr(config)
