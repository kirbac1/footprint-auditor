"""The impersonation check's reverse-image provider.

TinEye answers with matches, each carrying the pages the image was found on.
A finding points at a page, so that is what a result has to be.
"""

from types import SimpleNamespace

import pytest

from exposure_auditor.tools.reverse_image import TinEyeSearch
from exposure_auditor.tools.search import SearchError


class _FakeHttp:
    def __init__(self, body=None, status_code=200, raises=None):
        self.body, self.status_code, self.raises = body, status_code, raises
        self.sent = {}

    async def post(self, url, headers=None, params=None, files=None):
        if self.raises:
            raise self.raises
        self.sent = {"url": url, "headers": headers, "params": params, "files": files}
        return SimpleNamespace(status_code=self.status_code, json=lambda: self.body)


def _match(score=91, backlinks=None):
    return {"score": score, "backlinks": backlinks or [
        {"url": "https://cdn.example.net/img/1.jpg", "backlink": "https://example.net/profile/copy",
         "crawl_date": "2026-04-02 11:00:00"},
    ]}


def _body(matches):
    return {"code": 200, "messages": [], "results": {"matches": matches, "stats": {}}}


def _tineye(http):
    return TinEyeSearch(http, "test-key", "https://api.tineye.com/rest")


async def test_each_page_the_photo_appears_on_becomes_a_result():
    http = _FakeHttp(_body([_match()]))

    results = await _tineye(http).search(b"\xff\xd8jpegbytes", count=10)

    assert len(results) == 1
    assert results[0].url == "https://example.net/profile/copy"
    assert results[0].title == "example.net"
    assert "match score 91" in results[0].snippet and "2026-04-02" in results[0].snippet


async def test_the_image_is_uploaded_with_the_api_key():
    http = _FakeHttp(_body([]))

    await _tineye(http).search(b"jpegbytes", count=5)

    assert http.sent["url"] == "https://api.tineye.com/rest/search/"
    assert http.sent["headers"] == {"x-api-key": "test-key"}
    assert http.sent["params"]["limit"] == 5
    assert http.sent["files"]["image_upload"][1] == b"jpegbytes"


async def test_one_page_linked_by_several_matches_is_listed_once():
    link = {"url": "https://cdn.example.net/a.jpg", "backlink": "https://example.net/same"}
    http = _FakeHttp(_body([_match(backlinks=[link]), _match(score=80, backlinks=[link])]))

    results = await _tineye(http).search(b"jpegbytes")

    assert [r.url for r in results] == ["https://example.net/same"]


async def test_count_caps_the_pages_returned():
    links = [{"backlink": f"https://example.net/{i}"} for i in range(10)]
    http = _FakeHttp(_body([_match(backlinks=links)]))

    results = await _tineye(http).search(b"jpegbytes", count=3)

    assert len(results) == 3


@pytest.mark.parametrize(
    "http",
    [
        _FakeHttp(status_code=403),
        _FakeHttp({"code": 400, "messages": ["NO_SIGNATURE"], "results": {}}),
        _FakeHttp(raises=OSError("connection reset")),
    ],
)
async def test_provider_trouble_is_reported_to_the_agent_not_raised_raw(http):
    # SearchError is what the agent turns into a tool error the model can read.
    with pytest.raises(SearchError):
        await _tineye(http).search(b"jpegbytes")
