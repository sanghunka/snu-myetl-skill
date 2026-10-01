"""실계정·실토큰·외부 요청 없이 조회와 자료 저장 동작을 검증한다."""

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request


SPEC = importlib.util.spec_from_file_location("canvas_api", Path(__file__).parents[1] / "scripts/canvas_api.py")
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


class Response(io.BytesIO):
    def __init__(self, value, headers=None):
        raw = json.dumps(value).encode() if not isinstance(value, bytes) else value
        super().__init__(raw)
        self.headers = {"Content-Type": "application/json", **(headers or {})}


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, req, timeout=30):
        self.requests.append(req)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class DownloadClient(api.CanvasClient):
    def __init__(self, content="자료의 원문".encode()):
        super().__init__("가짜-검증용-토큰")
        self.metadata = {"id": 77, "display_name": "강의자료.pdf", "size": len(content),
                         "content-type": "application/pdf", "updated_at": "2026-09-01T00:00:00Z",
                         "url": "https://자료.example/강의자료.pdf?signature=가짜값"}
        self.download_opener = Opener(Response(content, {"Content-Type": "application/pdf"}))

    def get(self, endpoint, params=()):
        return dict(self.metadata)

    def add_content(self, content):
        self.download_opener.responses.append(Response(content, {"Content-Type": "application/pdf"}))


class CanvasTests(unittest.TestCase):
    def test_pagination_preserves_next_url(self):
        client = api.CanvasClient("검증용")
        next_url = api.API + "/courses?page=opaque%2B2&per_page=1"
        client.api_opener = Opener(Response([{"id": 1}], {"Link": f'<{next_url}>; rel="next"'}), Response([{"id": 2}]))
        self.assertEqual(client.get("/courses"), [{"id": 1}, {"id": 2}])
        self.assertEqual(client.api_opener.requests[1].full_url, next_url)

    def test_foreign_next_page_is_rejected(self):
        client = api.CanvasClient("검증용")
        client.api_opener = Opener(Response([], {"Link": '<https://다른.example/api/v1/courses>; rel="next"'}))
        with self.assertRaises(api.CanvasError):
            client.get("/courses")
        self.assertEqual(len(client.api_opener.requests), 1)

    def test_non_json_is_not_empty_result(self):
        client = api.CanvasClient("검증용")
        client.api_opener = Opener(Response("<html>로그인</html>".encode(), {"Content-Type": "text/html"}))
        with self.assertRaises(api.CanvasError):
            client.get("/courses")

    def test_404_is_not_empty_list(self):
        opener = Opener(HTTPError(api.API + "/courses/9", 404, "검증용", {}, None))
        with self.assertRaisesRegex(api.CanvasError, "404"):
            api.open_response(opener, Request(api.API + "/courses/9"))

    def test_rate_limit_retries(self):
        opener = Opener(HTTPError(api.API + "/courses", 429, "검증용", {"Retry-After": "0"}, None), Response([]))
        with patch.object(api.time, "sleep") as sleep:
            with api.open_response(opener, Request(api.API + "/courses")) as result:
                self.assertEqual(json.load(result), [])
            sleep.assert_called_once_with(0)

    def test_signed_html_keeps_file_identifier_without_secret(self):
        body = '<a href="https://myetl.snu.ac.kr/courses/1/files/77?download=1&amp;verifier=가짜서명">강의계획서</a>'
        cleaned = api.public_value({"body": body, "upload_params": {"secret": "가짜"}})
        self.assertIn("/files/77?download=1", cleaned["body"])
        self.assertNotIn("가짜서명", cleaned["body"])
        self.assertNotIn("verifier", cleaned["body"])
        self.assertNotIn("upload_params", cleaned)

    def test_external_redirect_does_not_receive_token(self):
        req = Request(api.BASE + "/files/77/download", headers={"Authorization": "Bearer 검증용"})
        redirected = api.DownloadRedirects().redirect_request(req, None, 302, "", {}, "https://자료.example/파일")
        self.assertIsNone(redirected.get_header("Authorization"))
        with self.assertRaises(api.CanvasError):
            api.ApiRedirects().redirect_request(req, None, 302, "", {}, "https://자료.example/api/v1/courses")

    def test_new_quiz_path_is_preserved(self):
        client = api.CanvasClient("검증용")
        url = client.api_url("/api/quiz/v1/courses/4/quizzes")
        self.assertEqual(urlsplit(url).path, "/api/quiz/v1/courses/4/quizzes")

    def test_read_state_is_preserved(self):
        client = api.CanvasClient("검증용")
        query = dict(parse_qsl(urlsplit(client.api_url("/conversations/7")).query))
        self.assertEqual(query["auto_mark_as_read"], "false")
        with self.assertRaises(api.CanvasError):
            client.api_url("/courses/1/assignments/2/submissions/self", [("include[]", "read_status")])

    def test_env_file_is_read_without_shell_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "토큰.env"
            marker = Path(folder) / "실행되면안되는파일"
            path.write_text(f'다른설정=$(touch "{marker}")\nexport CANVAS_API_TOKEN="검증용값"\n', encoding="utf-8")
            self.assertEqual(api.token_from_file(path), "검증용값")
            self.assertFalse(marker.exists())

    def test_unchanged_download_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            client = DownloadClient()
            first = client.download(77, folder)
            second = client.download(77, folder)
            self.assertEqual(first["상태"], "신규")
            self.assertEqual(second["상태"], "기존")
            self.assertEqual(len(client.download_opener.requests), 1)
            self.assertIsNone(client.download_opener.requests[0].get_header("Authorization"))

    def test_changed_download_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            client = DownloadClient("원본".encode())
            first = client.download(77, folder)
            client.metadata.update(size=len("수정본".encode()), updated_at="2026-09-08T00:00:00Z")
            client.add_content("수정본".encode())
            second = client.download(77, folder)
            self.assertEqual(Path(first["경로"]).read_bytes(), "원본".encode())
            self.assertEqual(Path(second["경로"]).read_bytes(), "수정본".encode())
            self.assertEqual(second["상태"], "수정본")
            self.assertNotEqual(first["경로"], second["경로"])

    def test_local_edit_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            client = DownloadClient("원본".encode())
            first = client.download(77, folder)
            Path(first["경로"]).write_bytes("사용자 메모".encode())
            client.add_content("원본".encode())
            second = client.download(77, folder)
            self.assertEqual(Path(first["경로"]).read_bytes(), "사용자 메모".encode())
            self.assertEqual(Path(second["경로"]).read_bytes(), "원본".encode())

    def test_module_rename_reuses_course_record(self):
        with tempfile.TemporaryDirectory() as folder:
            client = DownloadClient()
            root = Path(folder)
            first = client.download(77, root / "첫 모듈", root)
            second = client.download(77, root / "바뀐 모듈", root)
            self.assertEqual(second["상태"], "기존")
            self.assertEqual(first["경로"], second["경로"])
            self.assertEqual(len(client.download_opener.requests), 1)
            self.assertTrue((root / ".snu-myetl/downloads.json").exists())

    def test_incomplete_download_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            client = DownloadClient("원본".encode())
            client.metadata["size"] += 1
            with self.assertRaises(api.CanvasError):
                client.download(77, folder)
            self.assertFalse((Path(folder) / ".snu-myetl/downloads.json").exists())
            self.assertEqual(list(Path(folder).glob("*.pdf")), [])
            self.assertEqual(list(Path(folder).glob(".etl-*")), [])

    def test_filename_and_record_stay_inside_course(self):
        with tempfile.TemporaryDirectory() as folder:
            client = DownloadClient()
            root = Path(folder)
            client.metadata["display_name"] = "../강의자료.pdf"
            result = client.download(77, root / "자료", root)
            self.assertEqual(Path(result["경로"]).parent, (root / "자료").resolve())
            with self.assertRaises(api.CanvasError):
                client.download(77, root, root / "자료")


if __name__ == "__main__":
    unittest.main()
