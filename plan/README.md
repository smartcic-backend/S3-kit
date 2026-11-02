# 改進計畫

記錄目前 S3-kit 的重要缺口與改進提案。每份文件都是提案，實作前請先與維護者確認「待確認事項」。

| 順序 | 文件 | 摘要 | 狀態 |
|---|---|---|---|
| 1 | [01-presigned-public-endpoint.md](01-presigned-public-endpoint.md) | 預簽連結使用內部 endpoint，Docker 外部打不開 | 已實作 |
| 2 | [02-presigned-upload.md](02-presigned-upload.md) | 沒有預簽上傳連結，下載連結也無法指定檔名 | 已實作 |
| 3 | [03-exceptions.md](03-exceptions.md) | 例外層不完整，bucket 不存在會被誤判為物件不存在 | 已實作 |
| 4 | [04-credentials-and-connection.md](04-credentials-and-connection.md) | 憑證必填、無法設定逾時、重試與 TLS | 已實作 |

## 建議順序

1. 先處理預簽連結（1、2），兩者都會改到 `presigned_*` 與 `S3Config`，一起做可以減少重工。
2. 再處理例外層（3），它會改變對外的錯誤型別，屬於不相容變更，需要在發佈前決定。
3. 最後處理憑證與連線設定（4），它主要擴充 `S3Config`，不影響既有使用方式。

## 待確認事項的決定

### 01 預簽連結的對外 endpoint

- 欄位名稱使用 `public_endpoint_url`，環境變數為 `S3_PUBLIC_ENDPOINT_URL`。
- 範例的 `docker-compose.yaml` 設定 `S3_PUBLIC_ENDPOINT_URL=http://127.0.0.1:19000`，讓範例 API 示範預簽連結。

### 02 預簽上傳連結與下載檔名

- 上傳改用預簽 POST（`presigned_post`），不提供預簽 PUT。RustFS 1.0.4 實測支援 POST policy 的大小、Content-Type、key、有效期限與多餘欄位檢查，AWS S3 與 MinIO 也支援；POST 能在簽名中限制檔案大小，PUT 做不到。
- 違反 policy 時的狀態碼各後端不同（RustFS 回 400，AWS 回 403），測試只確認被拒絕且沒有存檔。
- 範例 API 新增「取得上傳表單」與「取得下載連結」端點。
- RustFS 1.0.4 支援 `response-content-disposition` 覆寫，由 e2e 測試 `test_presigned_get_url_sets_download_name` 確認。

### 03 例外層

- 例外名稱依照提案：`S3KitError`、`ObjectNotFoundError`、`BucketNotFoundError`、`AccessDeniedError`、`StorageConnectionError`。
- 接受這次的不相容變更。套件發佈方式尚未決定，暫不調整版本號。
- `delete_object` 在 bucket 不存在時拋出 `BucketNotFoundError`，來自服務回傳的 `NoSuchBucket`，不額外發出請求。
- e2e 允許使用不存在的 `s3-kit-e2e-missing` bucket 測試 bucket 不存在的情況，已更新 CLAUDE.md。

### 04 憑證與連線設定

- 不設定比 botocore 更短的預設逾時，未設定時不覆寫。
- `from_env` 缺少金鑰時不再拋出 `KeyError`，改為使用 boto3 預設的憑證來源；只提供一個金鑰時拋出 `ValueError`。
- 逾時錯誤包成 `StorageConnectionError`。

## 共通原則

所有提案都必須符合 [CLAUDE.md](../CLAUDE.md) 的設計原則：

- 只使用標準 S3 API，不針對特定後端寫專屬邏輯。
- 後端差異一律透過 `S3Config` 傳入，不用服務名稱做條件判斷。
- 新功能要同時補上單元測試（moto）與 e2e 測試（RustFS）。
