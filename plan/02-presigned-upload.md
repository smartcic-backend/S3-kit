# 預簽上傳連結與下載檔名

> 實作時改為預簽 POST（`presigned_post`），原因與決定見 [README.md](README.md)。本文件中預簽 PUT 的提案保留作為紀錄。

## 問題

1. 只有 `presigned_get_url`，沒有預簽上傳連結。所有上傳都必須經過使用方的服務轉送。
2. `presigned_get_url` 無法指定下載檔名，瀏覽器會用 key 的最後一段當檔名，也無法強制下載而不是在瀏覽器中開啟。

## 影響

- 大檔案上傳會佔用服務的頻寬、記憶體與連線時間。
- 使用方若把 key 設計成 UUID 等不可讀的名稱，使用者下載到的檔名也會是 UUID。

## 提案

### 預簽上傳連結

```python
def presigned_put_url(
    self,
    key: str,
    expires_in: int = 3600,
    content_type: str | None = None,
) -> str:
    ...
```

- 使用標準 S3 的 `put_object` 預簽連結。
- 指定 `content_type` 時會納入簽名，上傳端必須帶相同的 `Content-Type` header，否則會被拒絕。這要寫進 docstring 與 README。
- 與下載連結相同，使用 `_presign_client`（見 [01-presigned-public-endpoint.md](01-presigned-public-endpoint.md)）。

### 下載檔名

```python
def presigned_get_url(
    self,
    key: str,
    expires_in: int = 3600,
    download_name: str | None = None,
) -> str:
    ...
```

- 指定 `download_name` 時，加上標準 S3 的 `ResponseContentDisposition` 參數，值為 `attachment; filename*=UTF-8''<percent-encoded 檔名>`，與範例 API 目前的寫法一致，支援中文檔名。
- 未指定時維持現在的行為，向下相容。

## 不採用預簽 POST 的原因

預簽 POST（`generate_presigned_post`）可以用 policy 限制檔案大小（`content-length-range`），功能比 PUT 強。但它屬於瀏覽器表單上傳，部分 S3 相容服務支援度不一。依照 CLAUDE.md，「只有部分後端支援的功能要先討論再實作」，因此先只做 PUT。

## 設計原則檢查

- `put_object` 預簽與 `response-content-disposition` 都是標準 S3 API。
- 目前 client 設定 `request_checksum_calculation="when_required"`，預簽 PUT 不會帶額外的 checksum 參數，上傳端不需要計算 checksum。

## 注意事項

- 預簽 PUT 無法限制檔案大小，拿到連結的人可以上傳任意大小的檔案。需要限制時，使用方應縮短 `expires_in`，並在上傳完成後用 `get_info` 檢查大小。
- 預簽 PUT 單次最多 5 GB，更大的檔案需要預簽分段上傳，這次不處理。
- 瀏覽器直接上傳時，S3 服務需要設定 CORS。CORS 設定方式依服務而異，不在 S3-kit 的範圍內，只在 README 提醒。

## 測試

- 單元測試：連結包含 `X-Amz-Signature`、`X-Amz-Expires`；指定 `content_type` 時簽名包含 `content-type` header。
- 單元測試：指定 `download_name` 時連結包含 `response-content-disposition`，中文檔名正確編碼。
- e2e：用 `urllib.request` 對預簽 PUT 連結上傳，再用 `get_object` 讀回內容與 `content_type`。
- e2e：確認 RustFS 下載時回傳的 `Content-Disposition` header 與指定的檔名相同。

## 待確認事項

- RustFS 是否支援 `response-content-disposition` 覆寫（e2e 測試會確認）。
- 預簽 POST 是否需要，需要的話要先確認目前與未來使用的後端都支援。
- 範例 API 是否新增「取得上傳連結」的端點。
