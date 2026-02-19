#!/usr/bin/env python3
"""
upload_file.py — 上傳檔案到 MinIO (S3 相容)

使用純 stdlib 實作 AWS Signature V4 PUT 上傳，不需要額外套件。

環境變數（由 doppler 注入）:
  MINIO_ENDPOINT   — MinIO 端點 (e.g. 192.168.31.105:9000)
  MINIO_ACCESS_KEY  — Access Key
  MINIO_SECRET_KEY  — Secret Key
  MINIO_BUCKET     — Bucket 名稱 (預設: collections)
  MINIO_SECURE     — 是否用 HTTPS (預設: false)

用法:
  doppler run -p minio -c dev -- python3 upload_file.py image1.png image2.jpg
  doppler run -p minio -c dev -- python3 upload_file.py --prefix "xiaohongshu/2026-02-19" screenshot.png

輸出 JSON:
  [{"file": "screenshot.png", "url": "http://192.168.31.105:9000/collections/...png"}]
"""

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from urllib.parse import urlparse


def sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def aws_sig_v4_headers(
    method: str,
    url: str,
    host: str,
    region: str,
    access_key: str,
    secret_key: str,
    payload_hash: str,
    content_type: str,
) -> dict:
    """產生 AWS Signature V4 認證 headers"""
    now = datetime.now(timezone.utc)
    datestamp = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")

    parsed = urlparse(url)
    canonical_uri = parsed.path or "/"

    if parsed.query:
        qs_params = sorted(parsed.query.split("&"))
        canonical_querystring = "&".join(
            p if "=" in p else f"{p}=" for p in qs_params
        )
    else:
        canonical_querystring = ""

    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"

    canonical_request = (
        f"{method}\n{canonical_uri}\n{canonical_querystring}\n"
        f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    credential_scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    signing_key = sign(
        sign(
            sign(
                sign(f"AWS4{secret_key}".encode("utf-8"), datestamp),
                region,
            ),
            "s3",
        ),
        "aws4_request",
    )

    signature = hmac.new(
        signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Authorization": authorization,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Content-Type": content_type,
        "Host": host,
    }


def ensure_bucket(endpoint: str, bucket: str, access_key: str, secret_key: str, secure: bool):
    """確保 bucket 存在，不存在則建立"""
    scheme = "https" if secure else "http"
    url = f"{scheme}://{endpoint}/{bucket}"

    payload_hash = hashlib.sha256(b"").hexdigest()
    headers = aws_sig_v4_headers(
        "HEAD", url, endpoint, "us-east-1",
        access_key, secret_key, payload_hash, "application/octet-stream",
    )
    req = urllib.request.Request(url, method="HEAD", headers=headers)
    try:
        urllib.request.urlopen(req)
        return
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return

    headers = aws_sig_v4_headers(
        "PUT", url, endpoint, "us-east-1",
        access_key, secret_key, payload_hash, "application/octet-stream",
    )
    req = urllib.request.Request(url, data=b"", method="PUT", headers=headers)
    try:
        urllib.request.urlopen(req)
        print(f"✅ Bucket '{bucket}' 已建立", file=sys.stderr)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if "BucketAlreadyOwnedByYou" not in body:
            print(f"⚠️ 建立 bucket 失敗: HTTP {e.code}: {body}", file=sys.stderr)


def set_bucket_public(endpoint: str, bucket: str, access_key: str, secret_key: str, secure: bool):
    """設定 bucket 為公開讀取"""
    scheme = "https" if secure else "http"
    url = f"{scheme}://{endpoint}/{bucket}?policy"

    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:GetObject"],
            "Resource": [f"arn:aws:s3:::{bucket}/*"],
        }],
    }).encode("utf-8")

    payload_hash = hashlib.sha256(policy).hexdigest()
    headers = aws_sig_v4_headers(
        "PUT", url, endpoint, "us-east-1",
        access_key, secret_key, payload_hash, "application/json",
    )
    req = urllib.request.Request(url, data=policy, method="PUT", headers=headers)
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"⚠️ 設定 bucket policy: HTTP {e.code}: {body}", file=sys.stderr)


def upload_file(
    filepath: str,
    object_key: str,
    endpoint: str,
    bucket: str,
    access_key: str,
    secret_key: str,
    secure: bool,
) -> str:
    """上傳檔案到 MinIO，回傳公開 URL"""
    scheme = "https" if secure else "http"
    url = f"{scheme}://{endpoint}/{bucket}/{object_key}"

    with open(filepath, "rb") as f:
        data = f.read()

    content_type = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
    payload_hash = hashlib.sha256(data).hexdigest()

    headers = aws_sig_v4_headers(
        "PUT", url, endpoint, "us-east-1",
        access_key, secret_key, payload_hash, content_type,
    )

    req = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    urllib.request.urlopen(req)

    return url


def main():
    parser = argparse.ArgumentParser(description="上傳檔案到 MinIO")
    parser.add_argument("files", nargs="+", help="要上傳的檔案")
    parser.add_argument("--prefix", default="", help="物件路徑前綴 (e.g. xiaohongshu/2026-02-19)")
    parser.add_argument("--bucket", default=None, help="覆寫 bucket 名稱")
    args = parser.parse_args()

    endpoint = os.environ.get("MINIO_ENDPOINT")
    access_key = os.environ.get("MINIO_ACCESS_KEY")
    secret_key = os.environ.get("MINIO_SECRET_KEY")
    bucket = args.bucket or os.environ.get("MINIO_BUCKET", "collections")
    secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"

    if not all([endpoint, access_key, secret_key]):
        print("錯誤: 需要設定 MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY", file=sys.stderr)
        sys.exit(1)

    ensure_bucket(endpoint, bucket, access_key, secret_key, secure)
    set_bucket_public(endpoint, bucket, access_key, secret_key, secure)

    results = []
    for filepath in args.files:
        if not os.path.isfile(filepath):
            print(f"⚠️ 跳過: {filepath} (不存在)", file=sys.stderr)
            continue

        basename = os.path.basename(filepath)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        name, ext = os.path.splitext(basename)
        object_key = f"{args.prefix}/{ts}-{name}{ext}" if args.prefix else f"{ts}-{name}{ext}"
        object_key = object_key.lstrip("/")

        try:
            url = upload_file(filepath, object_key, endpoint, bucket, access_key, secret_key, secure)
            results.append({"file": basename, "url": url, "key": object_key})
            print(f"✅ {basename} → {url}", file=sys.stderr)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"❌ {basename}: HTTP {e.code}: {body}", file=sys.stderr)
            results.append({"file": basename, "error": f"HTTP {e.code}"})
        except Exception as e:
            print(f"❌ {basename}: {e}", file=sys.stderr)
            results.append({"file": basename, "error": str(e)})

    print(json.dumps(results))


if __name__ == "__main__":
    main()
