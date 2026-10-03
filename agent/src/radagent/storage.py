"""
Where chats are kept: a folder on this machine, or an S3 bucket every device shares (see infra/storage.tf)

Set RADAGENT_S3_BUCKET to keep chats in the bucket; leave it unset to keep them in a local folder. Both lay chats out
the same way, so a chat's files can be copied from one to the other as they are (scripts/migrate-chats.sh)

    RADAGENT_S3_BUCKET      the bucket; on AWS the runtime's role grants access, so nothing else is needed
    RADAGENT_S3_PREFIX      default "chats"; where the chats sit in the bucket
    RADAGENT_S3_REGION      default AWS_REGION

An S3-compatible server other than AWS also takes these; its key stays apart from the credentials Bedrock uses
    RADAGENT_S3_ENDPOINT    e.g. http://localhost:9000
    RADAGENT_S3_ACCESS_KEY
    RADAGENT_S3_SECRET_KEY
"""
import os
import shutil
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from strands.storage import LocalFileStorage, S3Storage


# Requests in flight at once when reading many objects, e.g. every chat's title for the sidebar
S3_READ_WORKERS: int = 16
# Give up quickly when the server can't be reached (the laptop is off the tailnet, say) instead of botocore's 60 s
S3_CONNECT_TIMEOUT_S: int = 3
S3_READ_TIMEOUT_S: int = 30
# The most keys one DeleteObjects request takes
S3_DELETE_BATCH: int = 1000



class StorageUnavailable(Exception):
    """The chat storage couldn't be reached or refused a request; the message says which and why"""



class Entry(NamedTuple):
    key: str            # relative to the root, '/'-separated
    modified: float     # POSIX timestamp



class Files(Protocol):
    """
    Bytes under '/'-separated keys relative to a root, which is a folder or a bucket prefix

    Synchronous, unlike Strands' Storage, because ChatStore and its callers are; `storage` hands the harness a
    Strands Storage over the same place
    """

    def read(self, key: str) -> bytes | None:
        """The bytes under `key`, or None when there's nothing there"""
        ...

    def read_many(self, keys: Iterable[str]) -> list[bytes | None]:
        ...

    def write(self, key: str, data: bytes) -> None:
        ...

    def append(self, key: str, data: bytes) -> None:
        ...

    def delete(self, key: str) -> None:
        ...

    def delete_folder(self, folder: str) -> None:
        """Delete every key under `folder`"""
        ...

    def entries(self, folder: str = "") -> list[Entry]:
        """Every key under `folder`, however deep"""
        ...

    def folders(self, folder: str = "") -> list[str]:
        """The names of the folders directly inside `folder`"""
        ...

    def storage(self, folder: str) -> LocalFileStorage | S3Storage:
        """A Strands Storage rooted at `folder`, not yet namespaced, for the harness to save into"""
        ...



class LocalFiles:
    """Files in a folder on this machine"""

    def __init__(self, root: Path) -> None:
        self.root = root


    def read(self, key: str) -> bytes | None:
        try:
            return (self.root / key).read_bytes()
        except FileNotFoundError:
            return None


    def read_many(self, keys: Iterable[str]) -> list[bytes | None]:
        return [self.read(key) for key in keys]


    def write(self, key: str, data: bytes) -> None:
        """Through a temporary file, so a crash mid-write never leaves half a file behind"""
        path = self.root / key
        path.parent.mkdir(parents = True, exist_ok = True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)


    def append(self, key: str, data: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents = True, exist_ok = True)
        with open(path, "ab") as file:
            file.write(data)


    def delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok = True)


    def delete_folder(self, folder: str) -> None:
        shutil.rmtree(self.root / folder, ignore_errors = True)


    def entries(self, folder: str = "") -> list[Entry]:
        found = []
        for path in (self.root / folder).rglob("*"):
            try:
                if path.is_file():
                    found.append(Entry(path.relative_to(self.root).as_posix(), path.stat().st_mtime))
            except OSError:
                # Deleted while we looked
                continue
        return found


    def folders(self, folder: str = "") -> list[str]:
        try:
            return [path.name for path in (self.root / folder).iterdir() if path.is_dir()]
        except OSError:
            return []


    def storage(self, folder: str) -> LocalFileStorage | S3Storage:
        return LocalFileStorage(str(self.root / folder))



class _EndpointSession(boto3.Session):
    """A boto3 session whose clients all go to one endpoint; Strands' S3Storage makes its own client and takes none"""

    def __init__(self, endpoint_url: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.endpoint_url = endpoint_url


    def client(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("endpoint_url", self.endpoint_url)
        return super().client(*args, **kwargs)



class S3Files:
    """Objects in an S3 bucket, under a prefix"""

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        region: str | None = None,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        """
        Args:
            bucket: {str}
            prefix: {str} Where the files sit in the bucket
            region: {str | None} The bucket's region; None takes AWS_REGION
            endpoint: {str | None} An S3-compatible server other than AWS; None is AWS itself
            access_key: {str | None} With secret_key, the server's own key; None uses the AWS credential chain
            secret_key: {str | None}
        """
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.where = endpoint or f"s3://{bucket}"
        keys = {"aws_access_key_id": access_key, "aws_secret_access_key": secret_key} if access_key else {}
        self.session = (
            _EndpointSession(endpoint, region_name = region, **keys) if endpoint
            else boto3.Session(region_name = region, **keys)
        )
        self.config = Config(
            # A server of your own usually has no DNS for <bucket>.<host>, so the bucket goes in the path there
            s3 = {"addressing_style": "path" if endpoint else "virtual"},
            connect_timeout = S3_CONNECT_TIMEOUT_S,
            read_timeout = S3_READ_TIMEOUT_S,
            retries = {"mode": "standard", "total_max_attempts": 2},
            # Room for read_many's requests, plus the ones /memory makes reading several chats at once
            max_pool_connections = 4 * S3_READ_WORKERS,
        )
        self.client = self.session.client("s3", config = self.config)


    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key


    def _folder(self, folder: str) -> str:
        """The key prefix of everything in `folder`; "" is the whole root"""
        path = "/".join(part for part in (self.prefix, folder.strip("/")) if part)
        return f"{path}/" if path else ""


    @contextmanager
    def _request(self, what: str) -> Iterator[None]:
        try:
            yield
        except (BotoCoreError, ClientError) as e:
            raise StorageUnavailable(f"Couldn't {what} in chat storage at {self.where}: {e}") from e


    def read(self, key: str) -> bytes | None:
        with self._request(f"read {key}"):
            try:
                response = self.client.get_object(Bucket = self.bucket, Key = self._key(key))
            except self.client.exceptions.NoSuchKey:
                return None
            return response["Body"].read()


    def read_many(self, keys: Iterable[str]) -> list[bytes | None]:
        keys = list(keys)
        if len(keys) < 2:
            return [self.read(key) for key in keys]
        with ThreadPoolExecutor(max_workers = min(S3_READ_WORKERS, len(keys))) as pool:
            return list(pool.map(self.read, keys))


    def write(self, key: str, data: bytes) -> None:
        with self._request(f"write {key}"):
            self.client.put_object(Bucket = self.bucket, Key = self._key(key), Body = data)


    def append(self, key: str, data: bytes) -> None:
        # S3 objects can't be appended to; fine while each chat has one writer
        self.write(key, (self.read(key) or b"") + data)


    def delete(self, key: str) -> None:
        with self._request(f"delete {key}"):
            self.client.delete_object(Bucket = self.bucket, Key = self._key(key))


    def delete_folder(self, folder: str) -> None:
        keys = [self._key(entry.key) for entry in self.entries(folder)]
        with self._request(f"delete {folder}"):
            for start in range(0, len(keys), S3_DELETE_BATCH):
                batch = keys[start:start + S3_DELETE_BATCH]
                response = self.client.delete_objects(
                    Bucket = self.bucket, Delete = {"Objects": [{"Key": key} for key in batch], "Quiet": True}
                )
                if errors := response.get("Errors"):
                    raise StorageUnavailable(f"Couldn't delete {len(errors)} object(s) in {folder}: {errors[0]}")


    def entries(self, folder: str = "") -> list[Entry]:
        root = self._folder("")
        found = []
        with self._request(f"list {folder or 'the chats'}"):
            pages = self.client.get_paginator("list_objects_v2").paginate(Bucket = self.bucket, Prefix = self._folder(folder))
            for page in pages:
                for item in page.get("Contents", []):
                    found.append(Entry(item["Key"][len(root):], item["LastModified"].timestamp()))
        return found


    def folders(self, folder: str = "") -> list[str]:
        prefix = self._folder(folder)
        with self._request(f"list {folder or 'the chats'}"):
            pages = self.client.get_paginator("list_objects_v2").paginate(Bucket = self.bucket, Prefix = prefix, Delimiter = "/")
            return [common["Prefix"][len(prefix):].rstrip("/") for page in pages for common in page.get("CommonPrefixes", [])]


    def storage(self, folder: str) -> LocalFileStorage | S3Storage:
        # S3Storage adds the trailing slash itself
        prefix = self._folder(folder).rstrip("/")
        return S3Storage(self.bucket, prefix = prefix, boto_session = self.session, boto_client_config = self.config)



def bucket_files(local_root: Path, prefix: str) -> Files:
    """
    Files in the bucket under `prefix` when RADAGENT_S3_BUCKET is set, otherwise in `local_root`

    Args:
        local_root: {Path} The folder the files live in without a bucket
        prefix: {str} Where they sit in the bucket
    """
    bucket = os.getenv("RADAGENT_S3_BUCKET")
    if not bucket:
        return LocalFiles(local_root)

    endpoint = os.getenv("RADAGENT_S3_ENDPOINT") or None
    access_key, secret_key = os.getenv("RADAGENT_S3_ACCESS_KEY"), os.getenv("RADAGENT_S3_SECRET_KEY")
    if bool(access_key) != bool(secret_key):
        raise ValueError("Set both RADAGENT_S3_ACCESS_KEY and RADAGENT_S3_SECRET_KEY, or neither to use AWS credentials")
    return S3Files(
        bucket,
        prefix = prefix,
        region = os.getenv("RADAGENT_S3_REGION") or None,
        endpoint = endpoint,
        access_key = access_key or None,
        secret_key = secret_key or None,
    )


def chat_files(local_root: Path) -> Files:
    """
    Where the chats are: the bucket when RADAGENT_S3_BUCKET is set, otherwise `local_root`

    Args:
        local_root: {Path} The folder chats live in without a bucket
    """
    return bucket_files(local_root, os.getenv("RADAGENT_S3_PREFIX", "chats"))
