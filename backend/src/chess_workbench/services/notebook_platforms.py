"""Read public game exports. Remote URLs are constructed from validated identifiers."""

import asyncio
import calendar
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from chess_workbench.services import ServiceError

ACCOUNT = re.compile(r"[A-Za-z0-9_-]{1,40}")
LICHESS_ID = re.compile(r"[a-zA-Z0-9]{8}")
MONTH = re.compile(r"(20\d\d)/(0[1-9]|1[0-2])")
CHESSCOM = "https://api.chess.com/pub/player"
LICHESS = "https://lichess.org"
USER_AGENT = "ChessWorkbench/0.1 (+https://github.com/DrBit-64/chess-workbench)"
EXPORT_PAGE = 100


@dataclass(frozen=True)
class RemoteGame:
    external_id: str
    url: str
    pgn: str | None  # Never import moves from an unfinished game.
    abandoned: bool = False
    started_at: datetime | None = None


def platform_timestamp(value: object, divisor: int) -> datetime | None:
    if type(value) is not int or value < 0:
        return None
    try:
        return datetime.fromtimestamp(value / divisor, UTC)
    except (ValueError, OverflowError, OSError):
        return None


def client() -> httpx.AsyncClient:
    try:
        return httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(25, connect=7),
            follow_redirects=False,
        )
    except (ImportError, ValueError) as exc:
        raise platform_error(
            "代理设置无法使用，请检查代理地址并运行 make bootstrap 安装依赖。", 503
        ) from exc


def platform_error(message: str, status: int = 502) -> ServiceError:
    return ServiceError("game_platform_unavailable", status, message)


async def get(
    http: httpx.AsyncClient,
    url: str,
    *,
    accept: str = "application/json",
    params: dict[str, str | int] | None = None,
    ids: list[str] | None = None,
) -> httpx.Response:
    try:
        if ids is None:
            response = await http.get(url, headers={"Accept": accept}, params=params)
        else:
            response = await http.post(
                url,
                headers={"Accept": accept, "Content-Type": "text/plain"},
                content=",".join(ids),
                params=params,
            )
    except httpx.HTTPError as exc:
        raise platform_error("暂时无法连接棋谱平台。请稍后重试，或导入 PGN。") from exc
    if response.status_code == 429:
        raise platform_error("平台正在限制请求。请等至少一分钟再试，已完成的进度会保留。", 429)
    if response.status_code == 404:
        raise ServiceError("not_found", 404, "平台未找到这个公开账号或棋局。")
    if not response.is_success:
        raise platform_error(f"棋谱平台返回 HTTP {response.status_code}。可稍后重试或导入 PGN。")
    return response


def object_json(response: httpx.Response) -> dict[str, object]:
    try:
        value = response.json()
    except ValueError as exc:
        raise platform_error("平台返回的对局数据无法读取，请稍后再试。") from exc
    if not isinstance(value, dict):
        raise platform_error("平台返回的对局数据格式不正确。")
    return value


def chesscom_id(url: str) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
        "www.chess.com",
        "chess.com",
    }:
        return None
    parts = parsed.path.strip("/").split("/")
    if parts[:1] == ["analysis"]:
        parts.pop(0)
    if len(parts) == 4 and parts[-1] in {"analysis", "review"}:
        parts.pop()
    if len(parts) != 3:
        return None
    first, second, number = parts
    is_game = (first == "game" and second in {"live", "daily"}) or (
        second == "game" and first in {"live", "daily"}
    )
    if is_game and re.fullmatch(r"[0-9]{1,24}", number) and int(number) > 0:
        return (second if first == "game" else first, str(int(number)))
    return None


async def archive_months(http: httpx.AsyncClient, user: str) -> list[str]:
    data = object_json(await get(http, f"{CHESSCOM}/{user}/games/archives"))
    archives = data.get("archives")
    if not isinstance(archives, list):
        raise platform_error("无法读取 Chess.com 的月份目录。")
    months: set[str] = set()
    for item in archives:
        if isinstance(item, str):
            # Ignore supplied host/path; only extract a year/month and build our own URL.
            month = "/".join(item.rstrip("/").split("/")[-2:])
            if MONTH.fullmatch(month):
                months.add(month)
    return sorted(months)


async def archive_games(http: httpx.AsyncClient, user: str, month: str) -> list[dict[str, object]]:
    data = object_json(await get(http, f"{CHESSCOM}/{user}/games/{month}"))
    games = data.get("games")
    if not isinstance(games, list) or not all(isinstance(g, dict) for g in games):
        raise platform_error("无法读取 Chess.com 的月度对局清单。")
    return games


class PageMetadata(HTMLParser):
    """Public share-page metadata provides optional hints, never the PGN itself."""

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            fields = dict(attrs)
            key = fields.get("property") or fields.get("name")
            value = fields.get("content")
            if key and value:
                self.values[key] = value


def game_hints(html: str) -> tuple[str | None, str | None]:
    page = PageMetadata()
    page.feed(html)
    title = page.values.get("og:title", "") + " " + page.values.get("description", "")
    player = re.search(r"\b([A-Za-z0-9_-]{2,40})\s+(?:vs\.?|versus)\s+", title, re.I)
    month = re.search(r"\b(20\d\d)[.-](0[1-9]|1[0-2])[.-]\d\d\b", " ".join(page.values.values()))
    return (player[1] if player else None, f"{month[1]}/{month[2]}" if month else None)


async def fetch_chesscom_export(
    url: str, username: str | None = None, month: str | None = None
) -> tuple[str, datetime | None]:
    try:
        async with asyncio.timeout(40):
            return await _resolve_chesscom_game(url, username, month)
    except TimeoutError as exc:
        raise platform_error(
            "查找 Chess.com 棋谱超时。请补充棋手用户名和结束月份后再试。", 504
        ) from exc


async def _resolve_chesscom_game(
    url: str, username: str | None, month: str | None
) -> tuple[str, datetime | None]:
    identity = chesscom_id(url)
    if identity is None:
        raise ServiceError("validation_error", 422, "请粘贴 Chess.com 的 live 或 daily 对局链接。")
    user = (username or "").strip().lower()
    archive = (month or "").strip().replace("-", "/")
    if user and not ACCOUNT.fullmatch(user):
        raise ServiceError("validation_error", 422, "请输入参赛一方的 Chess.com 用户名。")
    if archive and not MONTH.fullmatch(archive):
        raise ServiceError("validation_error", 422, "请填写对局结束的月份，格式为 YYYY-MM。")
    kind, game_id = identity
    async with client() as http:
        if not user:
            try:
                response = await get(
                    http, f"https://www.chess.com/game/{kind}/{game_id}", accept="text/html"
                )
            except ServiceError as exc:
                if exc.status == 429:
                    raise
                response = None
            hint, month_hint = game_hints(response.text) if response is not None else (None, None)
            if not hint:
                raise ServiceError(
                    "validation_error",
                    422,
                    "请补充任一棋手的用户名和对局结束月份，以从 Chess.com 的公开档案读取原谱。",
                )
            user = hint.lower()
            archive = archive or month_hint or ""
        months = [archive] if archive else await archive_months(http, user)
        # IDs describe creation order, while archives use completion dates. Use
        # IDs to prioritize, never to identify a game or exclude another month.
        # Try the newest first for the common "just played" flow.
        ranges = [(0, len(months) - 1)] if months else []
        probed = 0
        while ranges and probed < 12:
            low, high = ranges.pop()
            index = high if probed == 0 else (low + high) // 2
            probed += 1
            numbers: list[int] = []
            for game in await archive_games(http, user, months[index]):
                entry_url = game.get("url")
                key = chesscom_id(entry_url) if isinstance(entry_url, str) else None
                if key and key[0] == kind:
                    numbers.append(int(key[1]))
                if key != identity:
                    continue
                pgn = game.get("pgn")
                if game.get("rules") not in {None, "chess"}:
                    raise ServiceError(
                        "invalid_pgn", 422, "这盘棋是变体，本工作台收录标准国际象棋。"
                    )
                if isinstance(pgn, str) and pgn.strip():
                    return pgn, platform_timestamp(game.get("start_time"), 1)
                raise platform_error("Chess.com 尚未提供这盘棋的完整 PGN，可稍后重试。")
            halves = [(low, index - 1), (index + 1, high)]
            if numbers and int(game_id) < sorted(numbers)[len(numbers) // 2]:
                halves.reverse()
            ranges.extend(pair for pair in halves if pair[0] <= pair[1])
        if ranges:
            raise ServiceError(
                "validation_error",
                422,
                "该账号的历史对局较多。请补充对局结束月份，直接定位到相应的公开档案。",
            )
        raise ServiceError(
            "not_found",
            404,
            "所查月份的公开档案中未找到这盘棋。请检查参赛用户名与结束月份。"
            "新棋谱可能尚未发布，也可直接导入 PGN。",
        )


def utc_month(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y/%m")


async def chesscom_page(
    http: httpx.AsyncClient, user: str, since: int, until: int
) -> tuple[list[RemoteGame], int]:
    months = await archive_months(http, user)
    first = next((m for m in months if utc_month(since) <= m <= utc_month(until - 1)), None)
    if first is None:
        return [], until
    year, month = map(int, first.split("/"))
    next_month = (
        int(
            datetime(year, month, calendar.monthrange(year, month)[1], tzinfo=UTC).timestamp()
            + 86400
        )
        * 1000
    )
    boundary = min(next_month, until)
    result: list[RemoteGame] = []
    for game in await archive_games(http, user, first):
        ended = game.get("end_time")
        if not isinstance(ended, int) or not since <= ended * 1000 < boundary:
            continue
        url, pgn = game.get("url"), game.get("pgn")
        if game.get("rules") != "chess":
            continue
        key = chesscom_id(url) if isinstance(url, str) else None
        if not key or not isinstance(pgn, str) or not pgn.strip():
            raise platform_error("Chess.com 的已结束对局缺少标识或 PGN，同步进度已保留。")
        kind, number = key
        result.append(
            RemoteGame(
                f"{kind}:{number}",
                f"https://www.chess.com/game/{kind}/{number}",
                pgn,
                started_at=platform_timestamp(game.get("start_time"), 1),
            )
        )
    return result, boundary


def ndjson(response: httpx.Response) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in response.text.splitlines():
        if line.strip():
            try:
                value = json.loads(line)
            except ValueError as exc:
                raise platform_error("Lichess 返回的数据不完整，请重试。") from exc
            if not isinstance(value, dict):
                raise platform_error("无法读取 Lichess 对局。")
            rows.append(value)
    return rows


def lichess_game(item: dict[str, object]) -> RemoteGame | None:
    if item.get("variant") not in {"standard", "fromPosition"} or item.get("status") in {
        "aborted",
        "noStart",
    }:
        return None
    external_id = item.get("id")
    if not isinstance(external_id, str) or not LICHESS_ID.fullmatch(external_id):
        raise platform_error("Lichess 对局缺少标识。")
    unfinished = item.get("status") in {"created", "started"}
    pgn = item.get("pgn")
    if not unfinished and (not isinstance(pgn, str) or not pgn.strip()):
        raise platform_error("Lichess 已结束对局缺少 PGN，可稍后继续同步。")
    return RemoteGame(
        external_id,
        f"{LICHESS}/{external_id}",
        pgn if isinstance(pgn, str) and not unfinished else None,
        started_at=platform_timestamp(item.get("createdAt"), 1000),
    )


async def lichess_page(
    http: httpx.AsyncClient, user: str, since: int, until: int
) -> tuple[list[RemoteGame], int]:
    params: dict[str, str | int] = {
        "since": since,
        "until": until - 1,
        "max": EXPORT_PAGE + 1,
        "sort": "dateAsc",
        "ongoing": "true",
        "finished": "true",
        "pgnInJson": "true",
        "clocks": "true",
        "opening": "true",
        "evals": "true",
    }
    url = f"{LICHESS}/api/games/user/{user}"
    rows = ndjson(await get(http, url, accept="application/x-ndjson", params=params))
    boundary = until
    if len(rows) > EXPORT_PAGE:
        final_date = rows[-1].get("createdAt")
        if not isinstance(final_date, int) or not since <= final_date < until:
            raise platform_error("Lichess 返回了无效的分页日期。")
        if final_date == since:
            # Handle simultaneous starts without losing the remainder of this millisecond.
            del params["max"]
            params["until"] = since
            rows = ndjson(await get(http, url, accept="application/x-ndjson", params=params))
            boundary = since + 1
        else:
            boundary = final_date
            rows = [row for row in rows if row.get("createdAt") != final_date]
    return [game for row in rows if (game := lichess_game(row))], boundary


async def refresh_waiting(http: httpx.AsyncClient, ids: list[str]) -> list[RemoteGame]:
    response = await get(
        http,
        f"{LICHESS}/api/games/export/_ids",
        accept="application/x-ndjson",
        params={"pgnInJson": "true", "clocks": "true", "opening": "true", "evals": "true"},
        ids=ids,
    )
    games: list[RemoteGame] = []
    for row in ndjson(response):
        if game := lichess_game(row):
            games.append(game)
        elif (key := row.get("id")) in ids and isinstance(key, str):
            games.append(RemoteGame(key, f"{LICHESS}/{key}", None, abandoned=True))
    return games
