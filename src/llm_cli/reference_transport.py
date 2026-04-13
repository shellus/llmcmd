import mimetypes
from pathlib import Path
from time import time_ns
from uuid import uuid4

from .api import _debug_json, debug_log
from .utils import resolve_path

try:
    import boto3
except ImportError:
    boto3 = None

try:
    from botocore.config import Config as BotocoreConfig
except ImportError:
    BotocoreConfig = None


def create_s3_client(transport_config):
    if boto3 is None:
        raise ValueError("reference_transport 需要 boto3，请安装依赖后再使用")
    if BotocoreConfig is None:
        raise ValueError("reference_transport 缺少 botocore.config.Config，无法创建 S3 client")
    return boto3.client(
        "s3",
        endpoint_url=transport_config.get("endpoint"),
        region_name=transport_config.get("region"),
        aws_access_key_id=transport_config.get("access_key_id"),
        aws_secret_access_key=transport_config.get("secret_access_key"),
        config=BotocoreConfig(
            s3={
                "addressing_style": "virtual",
                "payload_signing_enabled": False,
            },
            request_checksum_calculation="when_required",
        ),
    )


def _normalize_public_base_url(value):
    return str(value).rstrip("/")


def _build_object_key(path, prefix=None):
    prefix = str(prefix or "").strip("/")
    suffix = path.suffix.lower()
    filename = f"{time_ns()}-{uuid4().hex}{suffix}"
    if prefix:
        return f"{prefix}/{filename}"
    return filename


def _build_reference_url(client, transport_config, bucket, object_key):
    url_mode = str(transport_config.get("url_mode") or "public").strip().lower()
    object_ref = f"oss://{bucket}/{object_key}"
    if url_mode == "presign":
        expires_in = int(transport_config.get("expires_in") or 3600)
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=expires_in,
        )
        debug_log(f"UPLOAD URL presign {object_ref} expires={expires_in} url={url}")
        return url

    public_base_url = transport_config.get("public_base_url")
    if not public_base_url:
        raise ValueError("reference_transport 使用 public URL 时必须配置 public_base_url")
    url = f"{_normalize_public_base_url(public_base_url)}/{object_key}"
    debug_log(f"UPLOAD URL public {object_ref} url={url}")
    return url


def _upload_one(path, transport_config):
    bucket = transport_config.get("bucket")
    if not bucket:
        raise ValueError("reference_transport 缺少 bucket 配置")

    client = create_s3_client(transport_config)
    object_key = _build_object_key(path, transport_config.get("key_prefix"))
    object_ref = f"oss://{bucket}/{object_key}"
    mime_type = mimetypes.guess_type(path.name)[0]
    debug_log(f"UPLOAD PUT {object_ref} path={path} mime={mime_type or 'application/octet-stream'}")
    kwargs = {
        "Bucket": bucket,
        "Key": object_key,
        "Body": path.read_bytes(),
    }
    if mime_type:
        kwargs["ContentType"] = mime_type
    client.put_object(**kwargs)
    debug_log(f"UPLOAD OK {object_ref} bytes={len(kwargs['Body'])}")
    return _build_reference_url(client, transport_config, bucket, object_key)


def prepare_reference_resources(reference_paths, *, config=None, base_dir=None):
    local_paths = []
    for item in reference_paths or []:
        local_paths.append(str(resolve_path(item, base_dir=base_dir)))

    transport = (config or {}).get("reference_transport")
    if transport is None:
        transport = ((config or {}).get("mode") or {}).get("reference_transport")
    if isinstance(transport, str):
        transport_name = transport
        transport = dict((((config or {}).get("reference_transports") or {}).get(transport_name)) or {})
        if transport:
            transport["name"] = transport_name
    if not transport:
        return {
            "local_paths": local_paths,
            "url_references": [],
        }

    debug_log(
        "UPLOAD config "
        + _debug_json(
            {
                "transport_name": transport.get("name"),
                "url_mode": transport.get("url_mode") or "public",
                "file_count": len(local_paths),
            }
        )
    )

    url_references = []
    for item in local_paths:
        url_references.append(_upload_one(Path(item), transport))

    return {
        "local_paths": local_paths,
        "url_references": url_references,
    }
