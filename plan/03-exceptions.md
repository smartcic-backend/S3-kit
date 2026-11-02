# 例外層

## 問題

### 對外例外不完整

CLAUDE.md 說明 `exceptions.py` 的目的是「避免使用方依賴 boto3 的例外型別」，但目前只有 `ObjectNotFoundError`。README 也寫明連線失敗、權限不足等錯誤會直接拋出 `botocore.exceptions.ClientError` 或 `BotoCoreError`。

使用方要處理這些錯誤時，必須 import botocore 並解析 `error.response["Error"]["Code"]`，等於綁定了 S3-kit 的底層實作。

### bucket 不存在被誤判為物件不存在

`exists()` 與 `get_info()` 使用 `head_object`。HEAD 回應沒有 body，botocore 只能用 HTTP 狀態碼當錯誤代碼。而 bucket 不存在時，`head_object` 同樣回傳 `404`，因此：

- `exists()` 會回傳 `False`。
- `get_info()` 會拋出 `ObjectNotFoundError`。

bucket 名稱設錯時，錯誤會被當成「檔案不存在」默默吞掉，很難察覺。

`get_object` 有 response body，可以區分 `NoSuchKey` 與 `NoSuchBucket`，目前 `NoSuchBucket` 會以 `ClientError` 拋出，與 `head_object` 的行為不一致。

## 提案

### 例外階層

```python
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
```

- 名稱避開 Python 內建的 `ConnectionError` 與 `PermissionError`，避免使用方混淆。
- 所有包裝後的例外都用 `raise ... from error` 保留原始 boto3 例外，除錯時可以從 `__cause__` 取得。
- 無法歸類的錯誤包成 `S3KitError`，使用方只要 catch `S3KitError` 就能處理所有錯誤。

### 錯誤對照

| 來源 | 包裝成 |
|---|---|
| `NoSuchKey`；`head_object` 的 `404`（bucket 存在時） | `ObjectNotFoundError` |
| `NoSuchBucket`；`head_bucket` 的 `404` | `BucketNotFoundError` |
| `AccessDenied`、`InvalidAccessKeyId`、`SignatureDoesNotMatch`、`403` | `AccessDeniedError` |
| `EndpointConnectionError`、`ConnectTimeoutError`、`ReadTimeoutError` | `StorageConnectionError` |
| 其他 `ClientError`、`BotoCoreError` | `S3KitError` |

錯誤代碼都是標準 S3 定義的代碼，不針對特定後端判斷。

### 集中轉換

在 `provider.py` 新增一個 context manager，所有公開方法都透過它轉換錯誤，避免每個方法各自判斷：

```python
@contextmanager
def _translate_errors(key: str | None = None) -> Iterator[None]:
    ...
```

`download_stream` 的迭代過程也要包起來，讀取中途斷線時拋出 `StorageConnectionError`。

### 區分 bucket 不存在與物件不存在

`head_object` 回傳 `404` 時，再呼叫一次 `head_bucket` 確認 bucket 是否存在：

- bucket 存在：物件不存在，`exists()` 回傳 `False`，`get_info()` 拋出 `ObjectNotFoundError`。
- bucket 不存在：兩者都拋出 `BucketNotFoundError`。

這只會讓「物件不存在」的情況多一次請求，物件存在時不受影響。

考慮過的其他做法：

| 做法 | 不採用的原因 |
|---|---|
| 改用 `get_object` 加 `Range` | 空檔案會回傳 `416`，各後端行為不一，也會多傳資料 |
| 只在 `ensure_bucket` 時檢查一次 | 執行期間 bucket 被刪除或設定錯誤時仍會誤判 |
| 快取 bucket 是否存在 | 增加狀態與失效處理，收益不大 |

## 相容性

- `ObjectNotFoundError` 改為繼承 `S3KitError`，現有的 `except ObjectNotFoundError` 不受影響。
- 目前 catch `ClientError` 的使用方會失效，屬於不相容變更。需要在發佈前決定版本號與變更說明。
- `exists()` 在 bucket 不存在時從回傳 `False` 改為拋出例外，也是行為變更。

## 測試

- 單元測試：每種錯誤對照都有測試，包括 `__cause__` 保留原始例外。
- 單元測試：bucket 不存在時，`exists()`、`get_info()`、`get_object()`、`download_stream()` 都拋出 `BucketNotFoundError`。
- 單元測試：`ensure_bucket` 遇到 `403` 時拋出 `AccessDeniedError`，而不是嘗試建立 bucket。
- 單元測試：錯誤的憑證拋出 `AccessDeniedError`。
- e2e：連到不存在的 port 時拋出 `StorageConnectionError`；用錯誤的 secret key 時拋出 `AccessDeniedError`。

## 待確認事項

- 例外名稱。
- 是否接受這次的不相容變更，以及對應的版本號（套件發佈方式尚未決定）。
- `delete_object` 在 bucket 不存在時是否也要拋出 `BucketNotFoundError`（目前刪除不存在的 key 不報錯）。
- README「錯誤處理」章節需要同步改寫。
