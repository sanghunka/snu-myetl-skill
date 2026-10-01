#!/usr/bin/env python3
"""서울대학교 eTL 조회와 파일 저장. Python 표준 라이브러리만 사용한다."""

import argparse
import hashlib
import html
from http.client import HTTPException
import json
import os
import re
import shlex
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


BASE = "https://myetl.snu.ac.kr"
API = BASE + "/api/v1"
SECRET_QUERY = re.compile(r"^(access_token|token|verifier|signature|sig|policy|credential|key-pair-id|x-amz-.+)$", re.I)
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


class CanvasError(Exception):
    """인증정보와 임시 주소를 포함하지 않는 사용자 안내용 오류."""


class KoreanParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = "필수 인수"
        self._optionals.title = "선택 인수"
        self.add_argument("-h", "--help", action="help", help="사용 안내 표시")

    def format_help(self):
        return super().format_help().replace("usage: ", "사용법: ", 1)

    def format_usage(self):
        return super().format_usage().replace("usage: ", "사용법: ", 1)

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "오류: 명령이나 인수가 올바르지 않습니다. --help로 사용법을 확인하세요.\n")


def origin(url):
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port or 443


def validate_https(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise CanvasError("인증정보가 없는 HTTPS 주소만 사용할 수 있습니다.")


def validate_api(url):
    validate_https(url)
    parts = urlsplit(url)
    if origin(url) != origin(BASE) or not parts.path.startswith(("/api/v1/", "/api/quiz/v1/")):
        raise CanvasError("서울대학교 eTL의 /api/v1 또는 /api/quiz/v1 경로만 조회할 수 있습니다.")
    if any(SECRET_QUERY.match(key) for key, _ in parse_qsl(parts.query)):
        raise CanvasError("인증정보를 URL에 넣을 수 없습니다. 로컬 환경파일을 사용하세요.")


class ApiRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_api(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DownloadRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_https(newurl)
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result is not None and origin(newurl) != origin(BASE):
            result.remove_header("Authorization")
        return result


def token_from_file(path):
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                key, separator, value = line.strip().removeprefix("export ").partition("=")
                if separator and key.strip() == "CANVAS_API_TOKEN":
                    words = shlex.split(value, comments=True, posix=True)
                    return words[0] if len(words) == 1 else ""
    except FileNotFoundError:
        return ""
    except (OSError, ValueError, UnicodeError):
        raise CanvasError("환경파일의 토큰 항목을 읽을 수 없습니다. 파일 권한과 형식을 확인하세요.") from None
    return ""


def load_token(env_file=None):
    value = os.environ.get("CANVAS_API_TOKEN", "").strip()
    if not value:
        paths = [Path(env_file).expanduser()] if env_file else [
            Path.home() / ".config/snu-myetl-skill/.env", Path.home() / ".env"
        ]
        for path in paths:
            value = token_from_file(path)
            if value:
                break
    if not value:
        raise CanvasError("CANVAS_API_TOKEN이 없습니다. README의 로컬 토큰 설정 안내를 확인하세요.")
    if "\n" in value or "\r" in value:
        raise CanvasError("토큰은 줄바꿈이 없는 한 줄이어야 합니다.")
    return value


def hide_signed_url(match):
    url = match.group(0)
    decoded = html.unescape(url)
    parts = urlsplit(decoded)
    params = parse_qsl(parts.query, keep_blank_values=True)
    safe_params = [(key, value) for key, value in params if not SECRET_QUERY.match(key)]
    if len(safe_params) == len(params):
        return url
    cleaned = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_params), ""))
    return html.escape(cleaned, quote=False) if decoded != url else cleaned


def public_value(value):
    if isinstance(value, dict):
        return {key: public_value(item) for key, item in value.items()
                if key.lower() not in {"access_token", "token", "authorization", "upload_url", "upload_params"}}
    if isinstance(value, list):
        return [public_value(item) for item in value]
    if isinstance(value, str):
        return URL_PATTERN.sub(hide_signed_url, value)
    return value


def retry_delay(value, attempt):
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            delay = 2 ** attempt
    return max(0, delay)


def open_response(opener, req):
    for attempt in range(4):
        try:
            return opener.open(req, timeout=30)
        except HTTPError as error:
            code = error.code
            delay = retry_delay(error.headers.get("Retry-After"), attempt)
            error.close()
            if code == 429 and attempt < 3 and delay <= 30:
                time.sleep(delay)
                continue
            explanations = {
                401: "인증 실패입니다. 토큰의 유효성을 확인하세요.",
                419: "인증이 만료되었거나 로그인 응답입니다. 토큰과 API 주소를 확인하세요.",
                403: "해당 자료를 조회할 권한이 없습니다.",
                404: "해당 항목을 찾지 못했습니다. ID·경로·과목 설정을 확인하세요.",
                429: "요청 제한에 도달했습니다. 안내된 대기 시간 뒤 다시 실행하세요.",
            }
            raise CanvasError(f"HTTP {code}: " + explanations.get(code, "서버 응답을 확인할 수 없습니다. 잠시 후 다시 시도하세요.")) from None
        except (URLError, TimeoutError, OSError):
            raise CanvasError("네트워크 연결에 실패했습니다. 연결 상태를 확인하세요.") from None
    raise CanvasError("요청을 완료하지 못했습니다.")


class CanvasClient:
    def __init__(self, token):
        self.token = token
        self.api_opener = build_opener(ApiRedirects())
        self.download_opener = build_opener(DownloadRedirects())

    def api_url(self, endpoint, params=()):
        if endpoint.startswith("https://"):
            url = endpoint
        elif endpoint.startswith(("/api/v1/", "/api/quiz/v1/")):
            url = BASE + endpoint
        elif endpoint.startswith("/"):
            url = API + endpoint
        else:
            raise CanvasError("API 경로는 /courses처럼 슬래시로 시작해야 합니다.")
        validate_api(url)
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True) + list(params)
        if any(key == "include[]" and value == "read_status" for key, value in query):
            raise CanvasError("read_status 조회는 읽음 상태를 변경합니다. 일반 조회에서는 제외하세요.")
        if re.fullmatch(r"/api/v1/conversations/\d+", parts.path):
            query = [(key, value) for key, value in query if key != "auto_mark_as_read"]
            query.append(("auto_mark_as_read", "false"))
        if not any(key == "per_page" for key, _ in query):
            query.append(("per_page", "100"))
        result = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        validate_api(result)
        return result

    def get(self, endpoint, params=()):
        url = self.api_url(endpoint, params)
        seen = set()
        combined = None
        while url:
            if url in seen:
                raise CanvasError("다음 페이지가 이미 조회한 주소로 연결됩니다. 페이지네이션을 중단했습니다.")
            seen.add(url)
            validate_api(url)
            req = Request(url, headers={"Authorization": "Bearer " + self.token,
                                       "Accept": "application/json", "User-Agent": "snu-myetl-skill/1.0"})
            with open_response(self.api_opener, req) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                if "json" not in content_type:
                    raise CanvasError("API에서 JSON 대신 다른 형식이 반환되었습니다. 주소와 인증을 확인하세요.")
                try:
                    data = json.load(response)
                except (ValueError, UnicodeError):
                    raise CanvasError("API 응답을 JSON으로 읽을 수 없습니다.") from None
                links = response.headers.get("Link", "")
                next_url = None
                for match in re.finditer(r'<([^>]+)>\s*;\s*rel="([^"]+)"', links):
                    if "next" in match.group(2).split():
                        next_url = urljoin(url, match.group(1))
                if isinstance(data, list):
                    if combined is None:
                        combined = []
                    if not isinstance(combined, list):
                        raise CanvasError("페이지 사이에 응답 형식이 달라졌습니다.")
                    combined.extend(data)
                elif combined is None and not next_url:
                    return data
                else:
                    raise CanvasError("페이지 목록의 응답 형식을 확인할 수 없습니다.")
                url = next_url
        return combined

    def download(self, file_id, destination, course_root=None):
        metadata = self.get(f"/files/{file_id}")
        if metadata.get("locked_for_user"):
            raise CanvasError("현재 사용자에게 잠긴 파일입니다.")
        url = metadata.get("url")
        if not url:
            raise CanvasError("파일 메타데이터에 다운로드 주소가 없습니다.")
        validate_https(url)
        root = Path(destination).expanduser().resolve()
        record_root = Path(course_root).expanduser().resolve() if course_root else root
        if not root.is_relative_to(record_root):
            raise CanvasError("자료 저장폴더는 지정한 과목 폴더 안에 있어야 합니다.")
        root.mkdir(parents=True, exist_ok=True)
        state_dir = record_root / ".snu-myetl"
        state_dir.mkdir(exist_ok=True)
        if state_dir.is_symlink():
            raise CanvasError("다운로드 기록 폴더가 심볼릭 링크입니다. 저장 위치를 확인하세요.")
        state_path = state_dir / "downloads.json"
        state = {"version": 1, "files": {}}
        if state_path.exists():
            if state_path.is_symlink():
                raise CanvasError("다운로드 기록 파일이 심볼릭 링크입니다.")
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if not isinstance(state.get("files"), dict):
                    raise ValueError()
            except (ValueError, AttributeError):
                raise CanvasError("다운로드 기록을 읽을 수 없습니다. 기존 기록을 확인하세요.") from None
        key = str(file_id)
        old = state["files"].get(key)
        if old:
            local = record_root / old["path"]
            if not local.resolve().is_relative_to(record_root):
                raise CanvasError("다운로드 기록의 파일 경로가 저장폴더 밖을 가리킵니다.")
            if (local.is_file() and not local.is_symlink()
                    and old.get("updated_at") == metadata.get("updated_at")
                    and old.get("size") == metadata.get("size")
                    and file_hash(local) == old.get("sha256")):
                return {"상태": "기존", "파일 ID": file_id, "경로": str(local), "크기": local.stat().st_size}
        name = safe_name(metadata.get("display_name") or metadata.get("filename") or f"자료-{file_id}")
        target = root / name
        if target.exists() or target.is_symlink():
            stem, suffix = Path(name).stem, Path(name).suffix
            index = 1
            while target.exists() or target.is_symlink():
                target = root / f"{stem}__수정-{file_id}-{index}{suffix}"
                index += 1
        temporary = None
        try:
            req = Request(url, headers={"User-Agent": "snu-myetl-skill/1.0"})
            if origin(url) == origin(BASE):
                req.add_header("Authorization", "Bearer " + self.token)
            with open_response(self.download_opener, req) as response:
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                expected_mime = metadata.get("content-type", "").lower()
                if mime == "text/html" and expected_mime != "text/html" and target.suffix.lower() not in {".html", ".htm"}:
                    raise CanvasError("자료 대신 HTML 로그인·오류 페이지가 반환되었습니다.")
                with tempfile.NamedTemporaryFile(dir=root, prefix=".etl-", delete=False) as handle:
                    temporary = Path(handle.name)
                    digest = hashlib.sha256()
                    total = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
                        total += len(chunk)
            expected = metadata.get("size")
            if expected is not None and total != int(expected):
                raise CanvasError("다운로드 크기가 원본과 다릅니다. 파일을 완료로 기록하지 않았습니다.")
            # 완료된 임시 파일만 새 이름으로 연결하며 기존 파일은 덮어쓰지 않는다.
            os.link(temporary, target)
            temporary.unlink()
            temporary = None
            state["files"][key] = {"path": target.relative_to(record_root).as_posix(), "display_name": metadata.get("display_name", name),
                                   "updated_at": metadata.get("updated_at"), "size": expected,
                                   "sha256": digest.hexdigest(), "saved_at": datetime.now(timezone.utc).isoformat()}
            atomic_json(state_path, state)
            return {"상태": "수정본" if old else "신규", "파일 ID": file_id,
                    "경로": str(target), "크기": total}
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value):
    name = unicodedata.normalize("NFC", value)
    name = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', "_", name).strip().rstrip(".")
    return name if name and name not in {".", ".."} else "자료"


def atomic_json(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".기록-", mode="w", encoding="utf-8", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = KoreanParser(description="서울대학교 eTL 과목·학습정보 조회와 파일 다운로드")
    parser.add_argument("--env-file", metavar="환경파일", help="토큰이 설정된 로컬 환경파일 경로")
    subparsers = parser.add_subparsers(dest="command", required=True, title="명령")
    subparsers.add_parser("courses", help="등록 중인 학생 과목과 학기 조회")
    get_parser = subparsers.add_parser("get", help="API 조회, 목록은 다음 페이지까지 합쳐서 출력")
    get_parser.add_argument("endpoint", metavar="API경로", help="/courses처럼 /api/v1을 뺀 경로")
    get_parser.add_argument("--param", metavar="이름=값", action="append", default=[], help="이름=값 형식, 여러 번 지정 가능")
    download_parser = subparsers.add_parser("download", help="파일 ID로 저장, 기존 파일과 수정본 구분")
    download_parser.add_argument("file_id", metavar="파일ID", type=int, help="조회한 파일 ID")
    download_parser.add_argument("--destination", metavar="저장폴더", required=True, help="저장할 폴더")
    download_parser.add_argument("--course-root", metavar="과목폴더", help="모듈 이름·위치가 바뀌어도 재사용할 과목 단위 저장 기록")
    args = parser.parse_args()
    try:
        client = CanvasClient(load_token(args.env_file))
        if args.command == "courses":
            data = client.get("/courses", [("enrollment_type", "student"), ("enrollment_state", "active"),
                                           ("include[]", "term"), ("include[]", "teachers")])
            data = [{key: item[key] for key in ("id", "name", "course_code", "term", "workflow_state", "start_at", "end_at", "teachers") if key in item}
                    | {"html_url": f"{BASE}/courses/{item['id']}"} for item in data]
        elif args.command == "get":
            params = []
            for value in args.param:
                name, separator, content = value.partition("=")
                if not name or not separator:
                    raise CanvasError("조회 조건은 이름=값 형식이어야 합니다.")
                params.append((name, content))
            data = client.get(args.endpoint, params)
        else:
            data = client.download(args.file_id, args.destination, args.course_root)
        print(json.dumps(public_value(data), ensure_ascii=False, indent=2))
        return 0
    except (CanvasError, OSError, ValueError, KeyError, TypeError, HTTPException):
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, CanvasError) else "로컬 파일 또는 응답 형식을 처리할 수 없습니다. 저장 위치와 조회 결과를 확인하세요."
        print("오류: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
