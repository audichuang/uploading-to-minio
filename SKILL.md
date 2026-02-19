---
name: uploading-to-minio
description: "Upload files to MinIO (S3-compatible) storage and return public URLs. Use when any skill needs to upload images or files to object storage. Trigger keywords: upload image, MinIO, 上傳圖片, 上傳檔案, object storage."
---

# Uploading to MinIO — 檔案上傳原子技能

將圖片或檔案上傳到 MinIO (S3 相容) 物件儲存，回傳公開 URL。

> **這是原子技能**：只負責「上傳檔案到 MinIO」這個動作。

## 環境設定

> **Doppler 配置**: `doppler run -p minio -c dev --`

| 環境變數 | 說明 |
|----------|------|
| `MINIO_ENDPOINT` | MinIO 端點 (e.g. 192.168.31.105:9000) |
| `MINIO_ACCESS_KEY` | Access Key |
| `MINIO_SECRET_KEY` | Secret Key |
| `MINIO_BUCKET` | Bucket 名稱 (預設: collections) |
| `MINIO_SECURE` | 是否用 HTTPS (預設: false) |

## 腳本

### upload\_file.py — 上傳檔案

```bash
# 上傳單張圖片
doppler run -p minio -c dev -- python3 ~/skills/uploading-to-minio/scripts/upload_file.py image.png

# 上傳多張 + 指定前綴路徑
doppler run -p minio -c dev -- python3 ~/skills/uploading-to-minio/scripts/upload_file.py \
  screenshot1.png screenshot2.png --prefix "xiaohongshu/2026-02-19"

# 指定 bucket
doppler run -p minio -c dev -- python3 ~/skills/uploading-to-minio/scripts/upload_file.py \
  photo.jpg --bucket my-bucket
```

輸出 JSON: `[{"file": "image.png", "url": "http://...", "key": "..."}]`

腳本會自動：

* 確保 bucket 存在（不存在則建立）
* 設定 bucket 為公開讀取
* 在檔名加上時間戳避免重名
