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
            "S3_PUBLIC_ENDPOINT_URL": "http://localhost:19000",
            "S3_SESSION_TOKEN": "token",
            "S3_CONNECT_TIMEOUT": "2.5",
            "S3_READ_TIMEOUT": "30",
            "S3_MAX_ATTEMPTS": "3",
            "S3_CA_BUNDLE": "/etc/ssl/internal-ca.pem",
        }
    )

    assert config == S3Config(
        bucket="bucket",
        access_key="access",
        secret_key="secret",
        endpoint_url="http://rustfs:9000",
        region="ap-northeast-1",
        force_path_style=True,
        public_endpoint_url="http://localhost:19000",
        session_token="token",
        connect_timeout=2.5,
        read_timeout=30,
        max_attempts=3,
        verify="/etc/ssl/internal-ca.pem",
    )


def test_from_env_uses_defaults():
    config = S3Config.from_env(REQUIRED_ENV)

    assert config.endpoint_url is None
    assert config.region == "us-east-1"
    assert config.force_path_style is False
    assert config.public_endpoint_url is None
    assert config.session_token is None
    assert config.connect_timeout is None
    assert config.read_timeout is None
    assert config.max_attempts is None
    assert config.verify is True


def test_from_env_treats_empty_values_as_unset():
    config = S3Config.from_env(
        {
            **REQUIRED_ENV,
            "S3_ENDPOINT_URL": "",
            "S3_REGION": "",
            "S3_PUBLIC_ENDPOINT_URL": "",
            "S3_ACCESS_KEY": "",
            "S3_SECRET_KEY": "",
            "S3_SESSION_TOKEN": "",
            "S3_CONNECT_TIMEOUT": "",
            "S3_READ_TIMEOUT": "",
            "S3_MAX_ATTEMPTS": "",
            "S3_VERIFY_SSL": "",
            "S3_CA_BUNDLE": "",
        }
    )

    assert config.endpoint_url is None
    assert config.region == "us-east-1"
    assert config.public_endpoint_url is None
    assert config.access_key is None
    assert config.secret_key is None
    assert config.session_token is None
    assert config.connect_timeout is None
    assert config.read_timeout is None
    assert config.max_attempts is None
    assert config.verify is True


def test_from_env_requires_bucket():
    env = {key: value for key, value in REQUIRED_ENV.items() if key != "S3_BUCKET"}

    with pytest.raises(KeyError, match="S3_BUCKET"):
        S3Config.from_env(env)


def test_from_env_allows_missing_credentials():
    config = S3Config.from_env({"S3_BUCKET": "bucket"})

    assert config.access_key is None
    assert config.secret_key is None


@pytest.mark.parametrize("missing", ["S3_ACCESS_KEY", "S3_SECRET_KEY"])
def test_from_env_requires_credentials_in_pairs(missing):
    env = {key: value for key, value in REQUIRED_ENV.items() if key != missing}

    with pytest.raises(ValueError, match="access_key"):
        S3Config.from_env(env)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("S3_CONNECT_TIMEOUT", "abc"),
        ("S3_READ_TIMEOUT", "10s"),
        ("S3_MAX_ATTEMPTS", "1.5"),
    ],
)
def test_from_env_rejects_invalid_numbers(name, value):
    with pytest.raises(ValueError, match=name):
        S3Config.from_env({**REQUIRED_ENV, name: value})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", True),
        ("true", True),
        ("1", True),
        ("0", False),
        ("false", False),
        ("NO", False),
    ],
)
def test_from_env_parses_verify_ssl(value, expected):
    config = S3Config.from_env({**REQUIRED_ENV, "S3_VERIFY_SSL": value})

    assert config.verify is expected


def test_from_env_prefers_ca_bundle_over_verify_ssl():
    config = S3Config.from_env(
        {**REQUIRED_ENV, "S3_VERIFY_SSL": "false", "S3_CA_BUNDLE": "/ca.pem"}
    )

    assert config.verify == "/ca.pem"


@pytest.mark.parametrize(
    "values",
    [
        {"access_key": "access"},
        {"secret_key": "secret"},
        {"session_token": "token"},
    ],
)
def test_rejects_incomplete_credentials(values):
    with pytest.raises(ValueError, match="access_key"):
        S3Config(bucket="bucket", **values)


@pytest.mark.parametrize(
    ("values", "name"),
    [
        ({"connect_timeout": 0}, "connect_timeout"),
        ({"read_timeout": -1}, "read_timeout"),
        ({"max_attempts": 0}, "max_attempts"),
    ],
)
def test_rejects_invalid_connection_settings(values, name):
    with pytest.raises(ValueError, match=name):
        S3Config(bucket="bucket", **values)


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
    config = S3Config(
        bucket="bucket",
        access_key="my-access",
        secret_key="my-secret",
        session_token="my-token",
    )

    assert "my-access" not in repr(config)
    assert "my-secret" not in repr(config)
    assert "my-token" not in repr(config)
