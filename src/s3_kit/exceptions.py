"""對外例外。原始的 boto3 例外保留在 __cause__，使用方不需要依賴 boto3 的例外型別。"""


class S3KitError(Exception):
    """S3-kit 所有例外的基底類別。"""


class ObjectNotFoundError(S3KitError):
    """指定的物件不存在。"""


class BucketNotFoundError(S3KitError):
    """設定的 bucket 不存在。"""


class AccessDeniedError(S3KitError):
    """憑證無效或沒有權限。"""


class StorageConnectionError(S3KitError):
    """無法連線到 S3 服務或連線逾時。"""
