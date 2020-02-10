import os
from io import (
    BytesIO,
    UnsupportedOperation,
)

import requests
from django.core.files.storage import (
    File,
    Storage,
)
from google.api_core.exceptions import Conflict
from google.cloud.exceptions import NotFound


def _get_storage_client():
    """Gets an instance of a google CloudStorage Client

        Note: google storage python library depends on env variables read at
        module import time, which requires nested imports
    """

    is_app_engine = os.environ.get("GAE_ENV") == "standard"
    http = None

    if not is_app_engine:
        http = requests.Session()

    from google.cloud import storage
    return storage.Client(
        _http=http,
    )


class CloudStorageFile(File):
    def __init__(self, bucket, name=None, mode="rb"):
        self._name = name
        self._mode = mode
        self._blob = bucket.blob(name)

    def read(self, num_bytes=None):
        if "r" not in self._mode:
            raise UnsupportedOperation("File open in '{}' is not readable".format(self._mode))
        if num_bytes:
            raise NotImplementedError("Specified argument 'num_bytes: {}' not supported".format(num_bytes))

        f = BytesIO()
        self._blob.download_to_file(f)
        return f.getvalue()

    def write(self, content):
        raise NotImplementedError("Write of CloudStorageFile object not currently supported.")


class CloudStorage(Storage):
    """
        Google Cloud Storage backend, set this as your default backend
        for ease of use, you can specify and non-default bucket in the
        constructor.

        You can modify objects access control by changing google_acl
        attribute to one of mentioned by docs (XML column):
        https://cloud.google.com/storage/docs/access-control/lists?hl=en#predefined-acl
    """
    def __init__(self, bucket_name="test-bucket", google_acl=None):
        self._bucket_name = bucket_name
        self._client = None
        self._bucket = None
        self._google_acl = google_acl

    @property
    def client(self):
        if self._client is None:
            self._client = _get_storage_client()
        return self._client

    @property
    def bucket(self):
        if not self._bucket:
            try:
                self._bucket = self.client.create_bucket(self._bucket_name)
            except Conflict:
                self._bucket = self.client.get_bucket(self._bucket_name)
        return self._bucket

    def get_valid_name(self, name):
        # App Engine doesn't properly deal with "./" and a blank upload_to argument
        # on a filefield results in ./filename so we must remove it if it's there.
        if name.startswith("./"):
            name = name.replace("./", "", 1)
        return name

    def exists(self, name):
        return bool(self.bucket.get_blob(name))

    def _save(self, name, content):
        # Not sure why, but it looks like django is not actually calling this
        name = self.get_valid_name(name)
        blob = self.bucket.blob(name)
        blob.upload_from_file(
            content.file, size=content.size, predefined_acl=self._google_acl
        )
        return name

    def _open(self, name, mode="r"):
        return CloudStorageFile(self._bucket, name=name, mode=mode)

    def size(self, name):
        blob = self.bucket.get_blob(name)
        if blob is None:
            raise NotFound("File {} does not exists".format(name))
        return blob.size

    def delete(self, name):
        return self._bucket.delete_blob(name)

    def url(self, name):
        return self.get_public_url(name)

    def get_public_url(self, name):
        is_app_engine = os.environ.get("GAE_ENV") == "standard"
        if is_app_engine:
            blob = self.bucket.blob(name)
            return blob.public_url
        else:
            return "http://localhost:10911/test-bucket/{}".format(name)


def has_cloudstorage():
    return True
