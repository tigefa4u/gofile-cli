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
UPLOAD_HOST = "upload.gofile.io"


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
        # The API often has no message, or repeats the status as the message.
        # Printing both yields "error-notPremium: error-notPremium".
        detail = status if not message or message == status else f"{status}: {message}"
        super().__init__(detail)


def _read_payload(resp) -> dict[str, Any]:
    raw = resp.read()
    http = getattr(resp, "status", None)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise GofileError(
            "error-parse",
            raw.decode("utf-8", errors="replace"),
            http,
        ) from exc
    if not isinstance(payload, dict):
        raise GofileError("error-parse", "response was not a JSON object", http)
    status = payload.get("status")
    if status != "ok":
        raise GofileError(status or "error", payload.get("message"), http)
    return payload


def _parse_response(resp) -> tuple[Any, Any]:
    payload = _read_payload(resp)
    return payload.get("data"), payload.get("metadata")


def _from_transport(exc: urllib.error.HTTPError | urllib.error.URLError) -> GofileError:
    """Map a urllib failure to GofileError. HTTPError is a URLError subclass."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            err_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except ValueError:
            return GofileError("error-http", str(exc), exc.code)
        if not isinstance(err_payload, dict):
            return GofileError("error-http", str(exc), exc.code)
        return GofileError(
            err_payload.get("status") or "error-http",
            err_payload.get("message"),
            exc.code,
        )
    return GofileError("error-network", str(exc.reason))


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
        raise _from_transport(exc) from exc
    except urllib.error.URLError as exc:
        raise _from_transport(exc) from exc


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

# Region id → hostname. The id is looked up, never concatenated into a URL,
# so a crafted value cannot redirect the token to another host.
UPLOAD_REGIONS: dict[str, str] = {
    "eu-par": "upload-eu-par.gofile.io",
    "na-phx": "upload-na-phx.gofile.io",
    "na-nyc": "upload-na-nyc.gofile.io",
    "ap-sgp": "upload-ap-sgp.gofile.io",
    "ap-hkg": "upload-ap-hkg.gofile.io",
    "ap-tyo": "upload-ap-tyo.gofile.io",
    "ap-syd": "upload-ap-syd.gofile.io",
    "sa-sao": "upload-sa-sao.gofile.io",
}


def upload_host(region: str | None = None) -> str:
    """Map a region id to an upload hostname. None and 'auto' use the global host."""
    if region is None or region.lower() == "auto":
        return UPLOAD_HOST
    host = UPLOAD_REGIONS.get(region.lower())
    if host is None:
        known = ", ".join(["auto", *UPLOAD_REGIONS])
        raise GofileError(
            "error-region",
            f"unknown upload region {region!r} (choose {known})",
        )
    return host


def _multipart_text(value: str) -> str:
    """Drop CR/LF so a field cannot break out of its multipart part."""
    return value.replace("\r", "").replace("\n", "")


def _escape_header_value(value: str) -> str:
    """Make a value safe to embed in a quoted multipart header.

    Strips CR/LF (header injection) and escapes embedded quotes/backslashes.
    Non-ASCII is passed through unchanged; the bytes are encoded as UTF-8 by
    the caller, matching how urllib encodes the request body.
    """
    cleaned = _multipart_text(value)
    return cleaned.replace("\\", "\\\\").replace('"', '\\"')


def _multipart_body(
    *,
    boundary: str,
    filename: str,
    content: bytes,
    content_type: str,
    folder_id: str | None,
) -> bytes:
    parts: list[bytes] = []
    if folder_id:
        # folderId is body text, not a quoted header parameter: escaping
        # quotes here would corrupt the id. CR/LF stripping is enough.
        field = _multipart_text(folder_id)
        parts.append(
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="folderId"\r\n\r\n'
                f"{field}\r\n"
            ).encode()
        )
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; '
        f'filename="{_escape_header_value(filename)}"\r\n'
        f"Content-Type: {_multipart_text(content_type)}\r\n\r\n"
    )
    parts.append(header.encode())
    parts.append(content)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def _with_guest_token(payload: dict[str, Any], data: Any) -> Any:
    """Keep a top-level guestToken on the data object the CLI already reads."""
    if not isinstance(data, dict) or data.get("guestToken"):
        return data
    guest = payload.get("guestToken")
    if isinstance(guest, str) and guest:
        return {**data, "guestToken": guest}
    return data


def upload_file(
    path: str | Path,
    *,
    token: str | None = None,
    folder_id: str | None = None,
    region: str | None = None,
    timeout: float = 120.0,
) -> Any:
    path = Path(path)
    if not path.is_file():
        raise GofileError("error-file", f"not a file: {path}")
    # Reject a bad region before reading the file into memory.
    host = upload_host(region)
    boundary = "----gofile" + uuid.uuid4().hex
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = _multipart_body(
        boundary=boundary,
        filename=path.name,
        content=path.read_bytes(),
        content_type=mime,
        folder_id=folder_id,
    )

    url = f"https://{host}/uploadfile"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = _read_payload(resp)
    except urllib.error.HTTPError as exc:
        raise _from_transport(exc) from exc
    except urllib.error.URLError as exc:
        raise _from_transport(exc) from exc
    return _with_guest_token(payload, payload.get("data"))
