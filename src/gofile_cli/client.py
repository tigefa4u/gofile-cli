"""Thin client for the Gofile REST API (https://api.gofile.io)."""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

API_BASE = "https://api.gofile.io"
UPLOAD_BASE = "https://upload.gofile.io"


class GofileError(Exception):
    """Raised when the Gofile API returns an error or the request fails."""

    def __init__(
        self,
        status: str,
        message: str | None = None,
        http: int | None = None,
    ) -> None:
        self.status = status
        self.message = message or status
        self.http = http
        # Avoid "status: status" when the API gave no separate message.
        detail = f"{status}: {message}" if message else status
        super().__init__(detail)


def _parse_response(resp) -> tuple[Any, Any]:
    raw = resp.read()
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GofileError(
            "error-parse",
            raw.decode("utf-8", errors="replace"),
            getattr(resp, "status", None),
        ) from exc
    status = payload.get("status")
    if status != "ok":
        raise GofileError(
            status or "error",
            payload.get("message") or status,
            getattr(resp, "status", None),
        )
    return payload.get("data"), payload.get("metadata")


def _request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    timeout: float = 30.0,
) -> tuple[Any, Any]:
    url = API_BASE + path
    if params:
        url = (
            url
            + "?"
            + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}, doseq=True
            )
        )
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _parse_response(resp)
    except urllib.error.HTTPError as exc:
        try:
            err_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            raise GofileError(
                err_payload.get("status") or "error-http",
                err_payload.get("message"),
                exc.code,
            ) from exc
        except ValueError:  # JSONDecodeError is a ValueError subclass
            raise GofileError("error-http", str(exc), exc.code) from exc
    except urllib.error.URLError as exc:
        raise GofileError("error-network", str(exc.reason)) from exc


# ---------------- accounts ----------------


def create_account(
    email: str | None = None, *, token: str | None = None, timeout: float = 30.0
) -> Any:
    body: dict[str, Any] = {}
    if email:
        body["email"] = email
    data, _ = _request(
        "POST", "/accounts", token=token, json_body=body, timeout=timeout
    )
    return data


def get_account_id(*, token: str | None = None, timeout: float = 30.0) -> Any:
    data, _ = _request("GET", "/accounts/getid", token=token, timeout=timeout)
    return data


def get_account(
    account_id: str, *, token: str | None = None, timeout: float = 30.0
) -> Any:
    data, _ = _request("GET", f"/accounts/{account_id}", token=token, timeout=timeout)
    return data


def reset_token(
    account_id: str, *, token: str | None = None, timeout: float = 30.0
) -> Any:
    data, _ = _request(
        "POST", f"/accounts/{account_id}/resettoken", token=token, timeout=timeout
    )
    return data


# ---------------- contents ----------------


def create_folder(
    parent_folder_id: str,
    folder_name: str | None = None,
    public: bool | None = None,
    *,
    token: str | None = None,
    timeout: float = 30.0,
) -> Any:
    body: dict[str, Any] = {"parentFolderId": parent_folder_id}
    if folder_name is not None:
        body["folderName"] = folder_name
    if public is not None:
        body["public"] = public
    data, _ = _request(
        "POST", "/contents/createFolder", token=token, json_body=body, timeout=timeout
    )
    return data


def get_content(
    content_id: str,
    *,
    token: str | None = None,
    password: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    sort_field: str | None = None,
    sort_direction: int | None = None,
    content_filter: str | None = None,
    maxdepth: int | None = None,
    timeout: float = 30.0,
) -> tuple[Any, Any]:
    params = {
        "password": password,
        "page": page,
        "pageSize": page_size,
        "sortField": sort_field,
        "sortDirection": sort_direction,
        "contentFilter": content_filter,
        "maxdepth": maxdepth,
    }
    return _request(
        "GET", f"/contents/{content_id}", token=token, params=params, timeout=timeout
    )


def update_content(
    content_id: str,
    attribute: str,
    attribute_value: Any,
    *,
    delete_after_expiry: bool | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> Any:
    body: dict[str, Any] = {"attribute": attribute, "attributeValue": attribute_value}
    if delete_after_expiry is not None:
        body["deleteAfterExpiry"] = delete_after_expiry
    data, _ = _request(
        "PUT",
        f"/contents/{content_id}/update",
        token=token,
        json_body=body,
        timeout=timeout,
    )
    return data


def delete_contents(
    contents_ids: list[str],
    *,
    token: str | None = None,
    timeout: float = 30.0,
) -> Any:
    body = {"contentsId": ",".join(contents_ids)}
    data, _ = _request(
        "DELETE", "/contents", token=token, json_body=body, timeout=timeout
    )
    return data


def copy_contents(
    contents_ids: list[str],
    folder_id: str,
    *,
    password: str | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> Any:
    body: dict[str, Any] = {"contentsId": ",".join(contents_ids), "folderId": folder_id}
    if password:
        body["password"] = password
    data, _ = _request(
        "POST", "/contents/copy", token=token, json_body=body, timeout=timeout
    )
    return data


def move_contents(
    contents_ids: list[str],
    folder_id: str,
    *,
    token: str | None = None,
    timeout: float = 30.0,
) -> Any:
    body = {"contentsId": ",".join(contents_ids), "folderId": folder_id}
    data, _ = _request(
        "PUT", "/contents/move", token=token, json_body=body, timeout=timeout
    )
    return data


def import_contents(
    contents_ids: list[str],
    *,
    password: str | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> Any:
    body: dict[str, Any] = {"contentsId": ",".join(contents_ids)}
    if password:
        body["password"] = password
    data, _ = _request(
        "POST", "/contents/import", token=token, json_body=body, timeout=timeout
    )
    return data


def search_contents(
    content_id: str,
    searched_string: str,
    *,
    password: str | None = None,
    create_time_from: int | None = None,
    create_time_to: int | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> Any:
    params: dict[str, Any] = {
        "contentId": content_id,
        "searchedString": searched_string,
    }
    if password:
        params["password"] = password
    if create_time_from is not None:
        params["createTimeFrom"] = create_time_from
    if create_time_to is not None:
        params["createTimeTo"] = create_time_to
    data, _ = _request(
        "GET", "/contents/search", token=token, params=params, timeout=timeout
    )
    return data


# ---------------- direct links ----------------


def create_direct_link(
    content_id: str,
    *,
    expire_time: int | None = None,
    source_ips_allowed: list[str] | None = None,
    domains_allowed: list[str] | None = None,
    domains_blocked: list[str] | None = None,
    auth: list[str] | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> Any:
    body: dict[str, Any] = {}
    if expire_time is not None:
        body["expireTime"] = expire_time
    if source_ips_allowed:
        body["sourceIpsAllowed"] = source_ips_allowed
    if domains_allowed:
        body["domainsAllowed"] = domains_allowed
    if domains_blocked:
        body["domainsBlocked"] = domains_blocked
    if auth:
        body["auth"] = auth
    data, _ = _request(
        "POST",
        f"/contents/{content_id}/directlinks",
        token=token,
        json_body=body,
        timeout=timeout,
    )
    return data


def update_direct_link(
    content_id: str,
    direct_link_id: str,
    *,
    expire_time: int | None = None,
    source_ips_allowed: list[str] | None = None,
    domains_allowed: list[str] | None = None,
    domains_blocked: list[str] | None = None,
    auth: list[str] | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> Any:
    body: dict[str, Any] = {}
    if expire_time is not None:
        body["expireTime"] = expire_time
    if source_ips_allowed is not None:
        body["sourceIpsAllowed"] = source_ips_allowed
    if domains_allowed is not None:
        body["domainsAllowed"] = domains_allowed
    if domains_blocked is not None:
        body["domainsBlocked"] = domains_blocked
    if auth is not None:
        body["auth"] = auth
    data, _ = _request(
        "PUT",
        f"/contents/{content_id}/directlinks/{direct_link_id}",
        token=token,
        json_body=body,
        timeout=timeout,
    )
    return data


def delete_direct_link(
    content_id: str,
    direct_link_id: str,
    *,
    token: str | None = None,
    timeout: float = 30.0,
) -> Any:
    data, _ = _request(
        "DELETE",
        f"/contents/{content_id}/directlinks/{direct_link_id}",
        token=token,
        timeout=timeout,
    )
    return data


# ---------------- upload ----------------


def _escape_header_value(value: str) -> str:
    """Make a value safe to embed in a quoted multipart header.

    Strips CR/LF (header injection) and escapes embedded quotes/backslashes.
    Non-ASCII is passed through unchanged; the bytes are encoded as UTF-8 by
    the caller, matching how urllib encodes the request body.
    """
    cleaned = value.replace("\r", "").replace("\n", "")
    return cleaned.replace("\\", "\\\\").replace('"', '\\"')


def upload_file(
    path: str | Path,
    *,
    token: str | None = None,
    folder_id: str | None = None,
    timeout: float = 120.0,
) -> Any:
    path = Path(path)
    if not path.is_file():
        raise GofileError("error-file", f"not a file: {path}")
    boundary = "----gofile" + uuid.uuid4().hex
    parts: list[bytes] = []
    if folder_id:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="folderId"\r\n\r\n{_escape_header_value(folder_id)}\r\n'.encode()
        )
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{_escape_header_value(path.name)}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode()
    )
    parts.append(path.read_bytes())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    url = UPLOAD_BASE + "/uploadfile"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _parse_response(resp)[0]
    except urllib.error.HTTPError as exc:
        try:
            err_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            raise GofileError(
                err_payload.get("status") or "error-http",
                err_payload.get("message"),
                exc.code,
            ) from exc
        except ValueError:  # JSONDecodeError is a ValueError subclass
            raise GofileError("error-http", str(exc), exc.code) from exc
    except urllib.error.URLError as exc:
        raise GofileError("error-network", str(exc.reason)) from exc
