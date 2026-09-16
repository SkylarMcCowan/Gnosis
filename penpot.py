"""Connection to a self-hosted Penpot instance (https://penpot.app) - so a
model can build out a real design (projects, files, boards, shapes)
through Gnosis's Tool registry (tools/design/) instead of only describing
what one should look like.

Talks directly to Penpot's own backend RPC API - `<PENPOT_URL>/api/rpc/
command/<name>`, authenticated with a personal access token (Penpot's
Settings > Access tokens; a self-hosted instance must also set
`enable-access-tokens` in its own config) - the same API Penpot's own web
app and the `zcube/penpot-mcp-server` MCP server use, rather than the
browser-only Plugins API, which needs a live Penpot browser session and
can't be driven headlessly from here.

No fallback host/token - PENPOT_URL and PENPOT_ACCESS_TOKEN come from the
environment (see docs/penpot.md), and a missing one is a raised, explicit
PenpotError, never a guessed default instance or a silent no-op (see
MEMORY: "No silent fallbacks"). Gnosis is single-user, so team selection is
resolved automatically to the account's default team rather than exposed
as a parameter (see MEMORY: "Gnosis architecture").

`add_board`/`add_shape` mutate a file via `update-file`'s `changes` array -
an event-sourced format that isn't officially documented past Penpot's own
source; the `add-obj` shape used here (and the required `selrect`/
`points`/`transform` geometry every object carries) mirrors
penpot-mcp-server's verified implementation.
"""
import os
import uuid

import requests

_TIMEOUT = 15
_ROOT_FRAME_ID = "00000000-0000-0000-0000-000000000000"


class PenpotError(Exception):
    """Raised on any Penpot failure - missing PENPOT_URL/PENPOT_ACCESS_TOKEN,
    an HTTP/network error, or an application error Penpot itself reports
    (unknown id, malformed changes)."""


def _config():
    base_url = os.environ.get("PENPOT_URL", "").strip().rstrip("/")
    token = os.environ.get("PENPOT_ACCESS_TOKEN", "").strip()
    if not base_url:
        raise PenpotError(
            'No Penpot instance configured - set PENPOT_URL (e.g. "http://localhost:9001"). See docs/penpot.md.'
        )
    if not token:
        raise PenpotError(
            "No Penpot access token configured - set PENPOT_ACCESS_TOKEN. See docs/penpot.md."
        )
    return base_url, token


def _to_kebab_case(obj):
    """Penpot's backend expects kebab-case keys (`page-id`, not `page_id`)
    - this lets every function below build request bodies with ordinary
    Python snake_case and convert once, right before sending."""
    if isinstance(obj, list):
        return [_to_kebab_case(item) for item in obj]
    if isinstance(obj, dict):
        return {key.replace("_", "-"): _to_kebab_case(value) for key, value in obj.items()}
    return obj


def _rpc(command, body=None):
    base_url, token = _config()
    url = f"{base_url}/api/rpc/command/{command}"
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = requests.post(url, json=_to_kebab_case(body or {}), headers=headers, timeout=_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise PenpotError(f'Penpot request "{command}" failed: {exc}') from exc
    return response.json() if response.content else None


def _new_id():
    return str(uuid.uuid4())


def _default_team_id():
    teams = _rpc("get-teams") or []
    if not teams:
        raise PenpotError("No Penpot teams found for this account's access token.")
    for team in teams:
        if team.get("is-default"):
            return team["id"]
    return teams[0]["id"]


# ----------------------------------------------------------------------
# Projects & files
# ----------------------------------------------------------------------
def list_projects():
    """Every project in the connected account's default team."""
    return _rpc("get-projects", {"team_id": _default_team_id()})


def create_project(name):
    name = (name or "").strip()
    if not name:
        raise ValueError("A project needs a name.")
    return _rpc("create-project", {"team_id": _default_team_id(), "name": name})


def list_files(project_id):
    return _rpc("get-project-files", {"project_id": project_id})


def create_file(project_id, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("A file needs a name.")
    return _rpc("create-file", {"project_id": project_id, "name": name, "is_shared": False})


def _get_file_raw(file_id):
    return _rpc("get-file", {"id": file_id})


def get_file(file_id):
    """A file's pages (id, name, shape count) - use this to find a page_id
    (and, for a board, a shape id) before calling add_board/add_shape."""
    raw = _get_file_raw(file_id)
    data = raw.get("data") or {}
    pages_index = data.get("pages-index") or {}
    pages = []
    for page_id in data.get("pages") or []:
        page = pages_index.get(page_id) or {}
        pages.append({
            "id": page_id,
            "name": page.get("name"),
            "object_count": len(page.get("objects") or {}),
        })
    return {"id": raw.get("id"), "name": raw.get("name"), "revn": raw.get("revn"), "pages": pages}


# ----------------------------------------------------------------------
# Boards & shapes
# ----------------------------------------------------------------------
def _resolve_page_id(file_raw, page_id):
    if page_id:
        return page_id
    pages = (file_raw.get("data") or {}).get("pages") or []
    if not pages:
        raise PenpotError("This file has no pages yet.")
    return pages[0]


def _resolve_frame_id(file_raw, page_id, board_id=None):
    if board_id:
        return board_id
    pages_index = (file_raw.get("data") or {}).get("pages-index") or {}
    page = pages_index.get(page_id) or {}
    for obj_id, obj in (page.get("objects") or {}).items():
        if obj.get("type") == "frame" and not obj.get("parent-id"):
            return obj_id
    return _ROOT_FRAME_ID


def _shape_geometry(x, y, width, height):
    return {
        "selrect": {
            "x": x, "y": y, "width": width, "height": height,
            "x1": x, "y1": y, "x2": x + width, "y2": y + height,
        },
        "points": [
            {"x": x, "y": y}, {"x": x + width, "y": y},
            {"x": x + width, "y": y + height}, {"x": x, "y": y + height},
        ],
        "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "transform_inverse": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
    }


def _apply_changes(file_id, revn, changes):
    return _rpc("update-file", {
        "id": file_id, "session_id": _new_id(), "revn": revn, "vern": 0, "changes": changes,
    })


def add_board(file_id, name, x=0, y=0, width=1440, height=1024, page_id=None, fill_color=None):
    """Add a board (artboard/frame) to a page - a container to lay other
    shapes out on. Returns its new id, resolved page_id, and name."""
    name = (name or "").strip() or "Board"
    file_raw = _get_file_raw(file_id)
    page_id = _resolve_page_id(file_raw, page_id)
    parent_id = _resolve_frame_id(file_raw, page_id)
    board_id = _new_id()
    obj = {
        "id": board_id, "type": "frame", "name": name,
        "x": x, "y": y, "width": width, "height": height,
        "parent_id": parent_id, "frame_id": parent_id, "shapes": [],
        **_shape_geometry(x, y, width, height),
    }
    if fill_color:
        obj["fills"] = [{"fill_color": fill_color, "fill_opacity": 1}]
    change = {"type": "add-obj", "id": board_id, "page_id": page_id, "frame_id": parent_id, "obj": obj}
    _apply_changes(file_id, file_raw.get("revn"), [change])
    return {"id": board_id, "page_id": page_id, "name": name}


def add_shape(file_id, shape_type, page_id=None, board_id=None, x=0, y=0, width=100, height=100,
              fill_color=None, text=None, font_size=16, name=None):
    """Add a rect/circle/text shape to a page, or inside a specific board
    (board_id) rather than the page root. Returns its new id, page_id,
    frame_id, type, and name."""
    if shape_type not in ("rect", "circle", "text"):
        raise ValueError('shape_type must be "rect", "circle", or "text".')

    file_raw = _get_file_raw(file_id)
    page_id = _resolve_page_id(file_raw, page_id)
    frame_id = _resolve_frame_id(file_raw, page_id, board_id)
    shape_id = _new_id()
    shape_name = name or shape_type.capitalize()
    fills = [{"fill_color": fill_color, "fill_opacity": 1}] if fill_color else None

    obj = {
        "id": shape_id, "type": shape_type, "name": shape_name,
        "x": x, "y": y, "width": width, "height": height,
        "parent_id": frame_id, "frame_id": frame_id,
        **_shape_geometry(x, y, width, height),
    }
    if fills:
        obj["fills"] = fills

    if shape_type == "text":
        text_content = text if text is not None else "Text"
        text_fills = fills or [{"fill_color": "#000000", "fill_opacity": 1}]
        obj["fills"] = text_fills
        obj["font_size"] = str(font_size)
        obj["font_family"] = "Work Sans"
        obj["content"] = {
            "type": "root",
            "children": [{
                "type": "paragraph-set",
                "children": [{
                    "type": "paragraph",
                    "children": [{
                        "text": text_content, "fills": text_fills,
                        "font_size": str(font_size), "font_family": "Work Sans",
                        "font_weight": "normal", "font_style": "normal",
                    }],
                }],
            }],
        }

    change = {"type": "add-obj", "id": shape_id, "page_id": page_id, "frame_id": frame_id, "obj": obj}
    _apply_changes(file_id, file_raw.get("revn"), [change])
    return {"id": shape_id, "page_id": page_id, "frame_id": frame_id, "type": shape_type, "name": shape_name}
