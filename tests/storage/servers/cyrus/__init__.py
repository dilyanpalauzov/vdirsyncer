import os

import pytest


class ServerMixin:
    @pytest.fixture
    def get_storage_args(self, item_type, slow_create_collection):
        def inner(collection="test"):
            url1 = "http://127.0.0.3/dav/calendars/"
            url2 = "https://udoma.bapha.be/dav/calendars/"
            args = {
                "username": "p@bapha.be",
                "password": "abc",
            }

            if self.storage_class.fileext == ".ics":
                args["url"] = url2
            elif self.storage_class.fileext == ".vcf":
                args["url"] = url2
            else:
                raise RuntimeError()

            if collection is not None:
                args = slow_create_collection(self.storage_class, args, collection)
            return args

        return inner
