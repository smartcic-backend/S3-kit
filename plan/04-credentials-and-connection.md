# 憑證與連線設定

## 問題

### 憑證只能用靜態金鑰

`access_key`、`secret_key` 是必填，也沒有 `session_token`，因此無法使用：

- AWS IAM role（ECS task role、EKS IRSA、EC2 instance profile）。
- STS 等臨時憑證。

在 AWS 上，使用長期金鑰通常不符合安全規範，這會讓 S3-kit 在 AWS 上難以採用。

### 無法設定逾時與重試

botocore 預設的連線與讀取逾時都是 60 秒，重試使用 legacy 模式。後端無回應時，每個請求可能卡住數分鐘，使用方無法調整。

### 無法設定 TLS 驗證

自架服務若使用內部 CA 簽發的憑證，目前無法指定 CA bundle，連線會因為憑證驗證失敗而中斷。

## 提案

### 憑證

```python
@dataclass(frozen=True, slots=True)
class S3Config:
    bucket: str
    access_key: str | None = field(default=None, repr=False)
    secret_key: str | None = field(default=None, repr=False)
    session_token: str | None = field(default=None, repr=False)
    ...
```

- `access_key` 與 `secret_key` 改為選填，但必須同時提供或同時省略，只提供一個時在 `__post_init__` 拋出 `ValueError`。
- 兩者都省略時，不傳入 boto3，由 boto3 預設的憑證來源取得（環境變數、設定檔、IAM role 等）。
- `session_token` 只有在提供金鑰時才有意義，單獨提供時拋出 `ValueError`。
- 新欄位都使用 `repr=False`，維持不在 repr 中顯示機敏資訊。

### 連線設定

```python
    connect_timeout: float | None = None
    read_timeout: float | None = None
    max_attempts: int | None = None
    verify: bool | str = True
```

- `connect_timeout`、`read_timeout`、`max_attempts` 為 `None` 時不覆寫 botocore 的預設值，維持目前行為。
- 指定 `max_attempts` 時使用 botocore 的 `standard` 重試模式。
- `verify` 對應 boto3 的 `verify` 參數：`True` 驗證憑證，`False` 不驗證，字串為 CA bundle 路徑。

### 環境變數

| 環境變數 | 必填 | 預設值 | 說明 |
|---|---|---|---|
| `S3_ACCESS_KEY` | 否（原為必填） | 空值 | 與 `S3_SECRET_KEY` 同時提供或同時省略 |
| `S3_SECRET_KEY` | 否（原為必填） | 空值 | 同上 |
| `S3_SESSION_TOKEN` | 否 | 空值 | 臨時憑證的 session token |
| `S3_CONNECT_TIMEOUT` | 否 | 空值 | 連線逾時秒數 |
| `S3_READ_TIMEOUT` | 否 | 空值 | 讀取逾時秒數 |
| `S3_MAX_ATTEMPTS` | 否 | 空值 | 最多嘗試次數（含第一次） |
| `S3_VERIFY_SSL` | 否 | `true` | `0`、`false`、`no` 代表不驗證憑證 |
| `S3_CA_BUNDLE` | 否 | 空值 | CA bundle 路徑，設定時優先於 `S3_VERIFY_SSL` |

數字格式錯誤時 `from_env` 拋出 `ValueError`，並在訊息中指出是哪個環境變數。

## 設計原則檢查

- 全部是 boto3 / botocore 的通用參數，不依賴任何後端。
- 差異完全由設定處理。

## 注意事項

- `read_timeout` 是單次 socket 讀取的逾時，不是整個下載的時間上限，串流下載大檔案不會因此中斷。但下載端消費過慢時，可能觸發讀取逾時，需要寫進 README。
- 憑證改為選填後，本機未設定金鑰時會改用開發者電腦上的 `~/.aws` 設定，可能意外連到其他帳號。README 要提醒自架服務一定要明確設定金鑰。
- `verify=False` 只能用於本機或測試，README 要明確標示。

## 測試

- 單元測試：只提供 `access_key` 或只提供 `secret_key` 時拋出 `ValueError`。
- 單元測試：省略金鑰時，boto3 從環境變數 `AWS_ACCESS_KEY_ID` 等取得憑證（moto 環境下可驗證）。
- 單元測試：`from_env` 讀取所有新增的環境變數，空值視為未設定，數字格式錯誤時拋出 `ValueError`。
- 單元測試：新增的機敏欄位不出現在 repr。
- 單元測試：建立的 client 帶有正確的 timeout、retries 與 verify 設定。
- e2e：設定很短的 `connect_timeout` 連到不存在的 port，確認在預期時間內失敗。

## 待確認事項

- 是否要設定比 botocore 更短的預設逾時，或維持「不設定就不覆寫」。
- 目前 `test_from_env_requires_values` 預期缺少金鑰時拋出 `KeyError`，這個行為會改變，需要確認可以接受。
- 逾時錯誤要包成哪個例外，與 [03-exceptions.md](03-exceptions.md) 一起決定。
