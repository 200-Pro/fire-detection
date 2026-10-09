from pathlib import Path
import re

class EvidenceStore:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.storage_path
        self.root.mkdir(parents=True, exist_ok=True)
        if settings.storage_backend not in ("local", "s3"):
            raise ValueError("Unsupported evidence storage")
        self.s3 = None
        if settings.storage_backend == "s3":
            if not settings.s3_bucket:
                raise ValueError("S3 bucket required")
            import boto3
            self.s3 = boto3.client("s3")  # IAM task role; no credentials in code.

    def put(self, alert_id, data):
        key = f"alerts/{alert_id}.jpg"
        if self.s3:
            self.s3.put_object(Bucket=self.settings.s3_bucket, Key=key, Body=data, ContentType="image/jpeg", ServerSideEncryption="AES256")
        else:
            target = self.root / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return key

    def get(self, key):
        if not re.fullmatch(r"alerts/[0-9a-f]{32}\.jpg", key):
            raise ValueError("Invalid evidence key")
        if self.s3:
            return self.s3.get_object(Bucket=self.settings.s3_bucket, Key=key)["Body"].read(2_000_001)
        return (self.root / key).read_bytes()

    def delete(self, key):
        if not re.fullmatch(r"alerts/[0-9a-f]{32}\.jpg", key):
            raise ValueError("Invalid evidence key")
        if self.s3:
            # Versioned buckets need an explicit lifecycle policy for old versions.
            self.s3.delete_object(Bucket=self.settings.s3_bucket, Key=key)
        else:
            target = self.root / key
            if target.is_symlink() or not target.resolve().is_relative_to(self.root.resolve()):
                raise ValueError("Evidence path escaped storage")
            target.unlink(missing_ok=True)
