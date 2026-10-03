"""okr_board.py - the 🔑OKRs board, read as Vex lays it out (HANDOFF_OKR
section 8, 2026-10-03).

Vex, 2026-10-03: "Mistake I made is that I tried planning my current
timeline of work and called it OKRs. What I will be doing instead is using
OKRs only as an inspo board kind of." So the list behind `okr_list_id`
(🔑OKRs, the list that used to be 🏆Goals Planning) is a KANBAN BOARD and
this module reads it the way the board shows it:

  * a COLUMN is a month - named "<keycaps> <year>": 1️⃣ 2027 ... 9️⃣ 2027,
    🔟 2027, 1️⃣1️⃣ 2027, 1️⃣2️⃣ 2027 - or a year's goals, "<year> Goals";
  * in a month column the CARD is an AREA (🏔️ Work 1️⃣ ... 🏔️ Manager 6️⃣),
    its subtasks are 🥅 objectives and theirs are 🔑 key results;
  * in a Goals column the area's children are 🏔️ year goals.

Scheduling IS the column, done by hand in the app; dates on a card mean
nothing here and are never read. A subtask mostly sits in "Not Sectioned"
on the server, so a card's month is its TOP card's column, never its own.
Same-named area cards in one column fold into one area and same-named
objectives under an area into one objective (he builds a month by pasting
blocks). Progress is the only number: ticked key results over all of them,
won't-do ones out of both.

READ-ONLY. Nothing here writes to TickTick; the one OKR write left in the
workflow is ⇧ Done on a key result, the ordinary complete road. The local
caches are written: the live loader keeps `project_data_<list>` (the open
cards and the columns, the hourly sync's own key) and `okr_done` (the
list's completed cards, which v1 never returns), so the periodic notes,
which may never touch the network inside a refresh, read the same board
the hub shows.

The old copy model (🏔️ Y • / 🥅 O • / 🔑 KR • - CODE, linked planning copies,
pace, ripple, auto-tick, countdowns) is history: HANDOFF_OKR sections 1-7.
Its naming is still parsed tolerantly so a card he never renamed reads
right.
"""
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date

try:
    import cache as cache_store
except Exception:            # pragma: no cover - a pure-model caller without the package
    cache_store = None

MONTH_NAMES = [None, "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
MONTH_ABBR = [None, "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

GLYPH_AREA = "🏔️"
GLYPH_GOAL = "🏔️"
GLYPH_O = "🥅"
GLYPH_KR = "🔑"
GLYPH_DONE = "✅"
GLYPH_WONTDO = "🚫"

_VS16 = "️"
_KEYCAP = "⃣"
_TEN = "\U0001F51F"               # 🔟

# the list's completed cards: the hub's live read and the hourly sync keep it
DONE_KEY = "okr_done"
COMPLETED_DAYS = 400
COMPLETED_LIMIT = 500

STATUS_OPEN, STATUS_DONE, STATUS_WONTDO = 0, 2, -1
_CLOSED = (STATUS_DONE, STATUS_WONTDO)


class BoardError(RuntimeError):
    """Neither the network nor the cache could say what is on the board.
    Raised rather than returning an empty board: "nothing planned" and
    "could not read" must never look the same."""


# ── column names ─────────────────────────────────────────────────────────────
def keycap(n):
    """1 -> 1️⃣, 10 -> 🔟, 11 -> 1️⃣1️⃣ - the way Vex names his month columns."""
    if n == 10:
        return _TEN
    return "".join(f"{d}{_VS16}{_KEYCAP}" for d in str(n))


def parse_keycaps(token):
    """"1️⃣1️⃣" -> 11, "🔟" -> 10, "3⃣" (no VS16) -> 3; None for anything else."""
    s = (token or "").replace(_VS16, "")
    if s == _TEN:
        return 10
    digits = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isdigit() and i + 1 < len(s) and s[i + 1] == _KEYCAP:
            digits.append(ch)
            i += 2
            continue
        return None
    return int("".join(digits)) if digits else None


_GOALS_COL_RE = re.compile(r"^\s*(\d{4})\s+Goals\s*$", re.I)
_MONTH_COL_RE = re.compile(r"^\s*(\S+)\s+(\d{4})\s*$")


def parse_column(name):
    """A column name -> ("goals", year, 0) | ("month", year, month) | None.
    Anything else ("Not Sectioned", a column he adds for something else)
    is not part of the board."""
    m = _GOALS_COL_RE.match(name or "")
    if m:
        return ("goals", int(m.group(1)), 0)
    m = _MONTH_COL_RE.match(name or "")
    if m:
        mo = parse_keycaps(m.group(1))
        if mo and 1 <= mo <= 12:
            return ("month", int(m.group(2)), mo)
    return None


def month_name(year, month):
    return f"{MONTH_NAMES[month]} {year}"


def month_bullet(year, month):
    """"🔟 October" - a month as the notes name it (the year is the note's)."""
    return f"{keycap(month)} {MONTH_NAMES[month]}"


def column_title(year, month):
    """The column name as Vex wrote it, rebuilt: "🔟 2026" / "2026 Goals"."""
    return f"{year} Goals" if not month else f"{keycap(month)} {year}"


# ── titles ───────────────────────────────────────────────────────────────────
_MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~<>•])")
_OLD_MARK_RE = re.compile(r"^(Y|O|KR)\s*[•·\-]\s+")
_CODE_TAIL_RE = re.compile(r"\s+-\s+[A-Za-z][A-Za-z0-9]{0,11}\s*$")
_LINK_RE = re.compile(r"^\[(?P<label>(?:[^\[\]]|\[[^\[\]]*\])*)\]\((?P<url>[^)\s]+)\)\s*(?P<rest>.*)$")
_AREA_NUM_RE = re.compile(r"\s*(\d)️?⃣\s*$")
_TT_TASK_RE = re.compile(r"#p/(?P<pid>[0-9a-f]{24}|inbox\d*)/tasks/(?P<tid>[0-9a-f]{24})")
_TT_LIST_RE = re.compile(r"#p/(?P<pid>[0-9a-f]{24}|inbox\d*)/tasks/?$")


def unescape(text):
    text = text or ""
    for _ in range(4):
        out = _MD_ESCAPE_RE.sub(r"\1", text)
        if out == text:
            break
        text = out
    return text


def _glyph_of(s):
    """(glyph, rest): the leading 🏔️ / 🥅 / 🔑, VS16 or not."""
    if s.startswith("\U0001F3D4"):            # 🏔
        rest = s[1:]
        if rest.startswith(_VS16):
            rest = rest[1:]
        return GLYPH_AREA, rest.lstrip()
    for g in (GLYPH_O, GLYPH_KR):
        if s.startswith(g):
            return g, s[len(g):].lstrip()
    return "", s


def parse_title(title):
    """A card title -> (glyph, name, link, number).
        "🏔️ Work 1️⃣"                          -> ("🏔️", "Work", None, 1)
        "🥅 [TickAL](https://.../tasks/<id>)"  -> ("🥅", "TickAL", url, None)
        "🔑 KR • Audits - TT"  (the old naming) -> ("🔑", "Audits", None, None)
    Tolerant of the app's backslash escapes, the old Y • / O • / KR •
    markers (a KR's trailing " - CODE" goes with them) and a link label
    holding one level of brackets."""
    s = unescape(title or "").strip()
    glyph, s = _glyph_of(s)
    m = _OLD_MARK_RE.match(s)
    old_kr = False
    if m:
        old_kr = m.group(1) == "KR"
        s = s[m.end():]
    link = None
    m = _LINK_RE.match(s)
    if m:
        link = m.group("url")
        s = (m.group("label") + (" " + m.group("rest") if m.group("rest") else "")).strip()
    if old_kr:
        s = _CODE_TAIL_RE.sub("", s)
    number = None
    m = _AREA_NUM_RE.search(s)
    if m:
        number = int(m.group(1))
        s = s[:m.start()].rstrip()
    s = re.sub(r"\s+", " ", s).strip()
    return glyph, s, link, number


def link_target(url):
    """("task", pid, tid) | ("list", pid) | ("url",) | None for a card's link."""
    if not url:
        return None
    m = _TT_TASK_RE.search(url)
    if m:
        return ("task", m.group("pid"), m.group("tid"))
    m = _TT_LIST_RE.search(url)
    if m:
        return ("list", m.group("pid"))
    return ("url",)


def card_url(pid, tid):
    return f"ticktick:///webapp/#p/{pid}/tasks/{tid}"


def board_url(pid):
    return f"ticktick:///webapp/#p/{pid}/tasks"


def _key(name):
    return " ".join((name or "").split()).casefold()


# ── the model ────────────────────────────────────────────────────────────────
@dataclass
class Card:
    id: str
    pid: str
    title: str
    name: str
    link: str
    glyph: str
    parent: str
    column: str
    status: int
    sort: int
    number: int = None
    raw: dict = field(default_factory=dict, repr=False)
    kind: str = ""          # area | goal | objective | kr | other (build sets it)
    depth: int = 0

    @property
    def done(self):
        return self.status == STATUS_DONE

    @property
    def abandoned(self):
        return self.status == STATUS_WONTDO

    @property
    def closed(self):
        return self.status in _CLOSED

    @property
    def target(self):
        return link_target(self.link)

    @property
    def key(self):
        return _key(self.name)


@dataclass
class Objective:
    """One 🥅 objective of an area (or one 🏔️ year goal of a Goals column):
    the same-named cards folded together, their key results in one list."""
    name: str
    cards: list
    krs: list = field(default_factory=list)
    kind: str = "objective"          # objective | goal

    @property
    def id(self):
        return self.cards[0].id

    @property
    def card(self):
        return self.cards[0]

    @property
    def key(self):
        return _key(self.name)

    @property
    def link(self):
        return next((c.link for c in self.cards if c.link), None)

    @property
    def closed(self):
        return all(c.closed for c in self.cards)

    @property
    def done(self):
        return all(c.done for c in self.cards)

    @property
    def abandoned(self):
        return all(c.abandoned for c in self.cards)

    @property
    def progress(self):
        """(done, total): ticked key results over all of them, a won't-do
        one out of both."""
        live = [k for k in self.krs if not k.abandoned]
        return sum(1 for k in live if k.done), len(live)

    @property
    def open_krs(self):
        return [k for k in self.krs if not k.closed]


@dataclass
class Area:
    name: str
    number: int
    cards: list
    objectives: list = field(default_factory=list)
    loose_krs: list = field(default_factory=list)     # 🔑 straight under the card

    @property
    def label(self):
        """"🏔️ Work 1️⃣" - the card as Vex titled it."""
        return f"{GLYPH_AREA} {self.name}" + (f" {keycap(self.number)}" if self.number else "")

    @property
    def key(self):
        return (self.number or 99, _key(self.name))

    @property
    def progress(self):
        d = n = 0
        for o in self.objectives:
            od, on = o.progress
            d, n = d + od, n + on
        live = [k for k in self.loose_krs if not k.abandoned]
        return d + sum(1 for k in live if k.done), n + len(live)


@dataclass
class Column:
    id: str
    name: str
    year: int
    month: int                      # 0 = the year's Goals column
    areas: list = field(default_factory=list)
    strays: list = field(default_factory=list)   # 🥅 / 🔑 at card level, no area

    @property
    def is_goals(self):
        return self.month == 0

    @property
    def title(self):
        return self.name.strip() or column_title(self.year, self.month)

    @property
    def bullet(self):
        return (f"{GLYPH_GOAL} {self.year} Goals" if self.is_goals
                else month_bullet(self.year, self.month))

    @property
    def long_name(self):
        return f"{self.year} Goals" if self.is_goals else month_name(self.year, self.month)

    @property
    def empty(self):
        return not self.areas and not self.strays

    @property
    def objectives(self):
        return [o for a in self.areas for o in a.objectives]

    @property
    def krs(self):
        out = [k for o in self.objectives for k in o.krs]
        out += [k for a in self.areas for k in a.loose_krs]
        return out

    @property
    def open_krs(self):
        return [k for k in self.krs if not k.closed]

    @property
    def progress(self):
        d = n = 0
        for a in self.areas:
            ad, an = a.progress
            d, n = d + ad, n + an
        live = [k for k in self.strays if k.kind == "kr" and not k.abandoned]
        return d + sum(1 for k in live if k.done), n + len(live)

    @property
    def start(self):
        return date(self.year, self.month or 1, 1)


@dataclass
class Board:
    list_id: str
    name: str
    columns: list                    # chronological: a year's Goals, then its months
    cards: dict
    source: str = "live"             # live | cache
    detail: str = ""
    unsorted: list = field(default_factory=list)    # cards in no board column

    def month(self, year, month):
        return next((c for c in self.columns if c.year == year and c.month == month), None)

    def goals(self, year):
        return self.month(year, 0)

    def months(self):
        return [c for c in self.columns if not c.is_goals]

    def years(self):
        return sorted({c.year for c in self.columns})

    def column_of(self, card_id):
        c = self.cards.get(card_id)
        while c is not None and c.parent in self.cards:
            c = self.cards[c.parent]
        if c is None:
            return None
        return next((col for col in self.columns if col.id == c.column), None)

    def rollup(self, goal):
        """A year goal's progress off the same-named objectives in its
        year's months -> (done, total, months with one). (0, 0, 0) when no
        month plans an objective by that name - a goal reads plain then."""
        d = n = m = 0
        for col in self.columns:
            if col.is_goals or col.year != goal.card_year(self):
                continue
            hit = [o for o in col.objectives if o.key == goal.key]
            if not hit:
                continue
            m += 1
            for o in hit:
                od, on = o.progress
                d, n = d + od, n + on
        return d, n, m

    def search(self, text):
        """Every objective and key result whose name holds `text`, with its
        column and area -> [(Column, Area, Objective, Card | None)]."""
        q = _key(text)
        out = []
        if not q:
            return out
        for col in self.columns:
            for a in col.areas:
                for o in a.objectives:
                    if q in o.key:
                        out.append((col, a, o, None))
                    for k in o.krs:
                        if q in k.key:
                            out.append((col, a, o, k))
        return out


def _goal_year(self, board):
    col = board.column_of(self.id)
    return col.year if col else None


Objective.card_year = _goal_year


# ── building ─────────────────────────────────────────────────────────────────
def _card(t):
    glyph, name, link, number = parse_title(t.get("title") or "")
    return Card(id=t.get("id") or "", pid=t.get("projectId") or t.get("_projectId") or "",
                title=t.get("title") or "", name=name, link=link, glyph=glyph,
                parent=t.get("parentId") or "", column=t.get("columnId") or "",
                status=int(t.get("status") or 0), sort=int(t.get("sortOrder") or 0),
                number=number, raw=t)


def _sorted(cards):
    return sorted(cards, key=lambda c: (c.sort, c.title))


def build(list_id, name, columns, tasks):
    """The board from raw rows: `columns` = the list's column rows ({id,
    name, sortOrder}), `tasks` = every card, open and completed. PURE."""
    cards = {}
    for t in tasks or []:
        if isinstance(t, dict) and t.get("id") and (t.get("title") or "").strip():
            cards[t["id"]] = _card(t)
    kids = {}
    for c in cards.values():
        if c.parent in cards:
            kids.setdefault(c.parent, []).append(c)
    for v in kids.values():
        v.sort(key=lambda c: (c.sort, c.title))

    # depth, with a guard against a parent cycle the server should never send
    def depth_of(c):
        d, seen = 0, set()
        while c.parent in cards and c.id not in seen:
            seen.add(c.id)
            c = cards[c.parent]
            d += 1
        return d
    for c in cards.values():
        c.depth = depth_of(c)

    cols = []
    for raw in columns or []:
        parsed = parse_column((raw or {}).get("name") or "")
        if parsed is None:
            continue
        _k, y, m = parsed
        cols.append(Column(id=raw.get("id") or "", name=raw.get("name") or "", year=y, month=m))
    cols.sort(key=lambda c: (c.year, c.month))
    by_col = {c.id: c for c in cols}

    unsorted = []
    tops = [c for c in cards.values() if c.depth == 0]
    for top in _sorted(tops):
        col = by_col.get(top.column)
        if col is None:
            top.kind = "other"
            unsorted.append(top)
            continue
        _place(top, col, kids)
    for col in cols:
        col.areas.sort(key=lambda a: a.key)
    return Board(list_id=list_id, name=name or "", columns=cols, cards=cards,
                 unsorted=unsorted)


def _place(top, col, kids):
    """One top card into its column: an area with its objectives (or goals)
    and their key results; a 🥅 or 🔑 at card level is a stray."""
    children = kids.get(top.id, [])
    if top.glyph == GLYPH_O:
        top.kind = "objective"
        col.strays.append(top)
        _mark_krs(children, kids)
        return
    if top.glyph == GLYPH_KR:
        top.kind = "kr"
        col.strays.append(top)
        return
    top.kind = "area"
    area = next((a for a in col.areas if a.key == (top.number or 99, top.key)), None)
    if area is None:
        area = Area(name=top.name, number=top.number, cards=[])
        col.areas.append(area)
    area.cards.append(top)
    for ch in children:
        if ch.glyph == GLYPH_KR and not col.is_goals:
            ch.kind = "kr"
            area.loose_krs.append(ch)
            continue
        ch.kind = "goal" if col.is_goals else "objective"
        obj = next((o for o in area.objectives if o.key == ch.key), None)
        if obj is None:
            obj = Objective(name=ch.name, cards=[], kind=ch.kind)
            area.objectives.append(obj)
        obj.cards.append(ch)
        grand = kids.get(ch.id, [])
        _mark_krs(grand, kids)
        obj.krs.extend(grand)
    area.objectives.sort(key=lambda o: (min(c.sort for c in o.cards), o.name))


def _mark_krs(cards, kids):
    for k in cards:
        k.kind = "kr"
        for g in kids.get(k.id, []):
            g.kind = "kr"


# ── loading ──────────────────────────────────────────────────────────────────
def _why(e):
    return f"{type(e).__name__}: {e}"


def _pd_key(list_id):
    return f"project_data_{list_id}"


def _list_id(list_id):
    if list_id:
        return list_id
    import config as cfg
    return (cfg.get_okr_list_id() or "").strip()


def refresh_done(list_id=None, v2=None):
    """Keep `okr_done` = the list's completed cards (v2 project_completed,
    the only road that returns them). The hourly sync calls it beside the
    project_data it already stores; the hub's live read calls it too.
    Returns the row count, or None when v2 could not answer (the cache is
    then left as it was - a transport blip is not an empty board)."""
    pid = _list_id(list_id)
    if not pid or cache_store is None:
        return None
    try:
        if v2 is None:
            from api_v2 import TickTickV2
            v2 = TickTickV2()
        rows = v2.project_completed(pid, days=COMPLETED_DAYS, limit=COMPLETED_LIMIT)
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    rows = [t for t in rows if isinstance(t, dict) and t.get("id") and not t.get("deleted")]
    try:
        cache_store.set(DONE_KEY, {"list_id": pid, "ts": time.time(), "rows": rows})
    except Exception:
        pass
    return len(rows)


def _done_rows(pid):
    """The cached completed cards of the list: okr_done when it is this
    list's, else what the account-wide completed feed still holds."""
    if cache_store is None:
        return []
    c = cache_store.get(DONE_KEY)
    if isinstance(c, dict) and c.get("list_id") == pid and isinstance(c.get("rows"), list):
        return [t for t in c["rows"] if isinstance(t, dict)]
    feed = cache_store.get("completed_tasks")
    if isinstance(feed, list):
        return [t for t in feed if isinstance(t, dict) and t.get("projectId") == pid]
    return []


def _merge(open_rows, done_rows):
    seen = {t.get("id") for t in open_rows}
    return list(open_rows) + [t for t in done_rows
                              if t.get("id") not in seen and not t.get("deleted")]


def cached(list_id=None):
    """The board from the CACHES only - the periodic notes' road (a refresh
    never touches the network) and every typed keystroke's. None when the
    cache holds no project_data of the list (the open cards AND the
    columns live there; the all_tasks rows carry no column list, so a
    board cannot be built from them)."""
    pid = _list_id(list_id)
    if not pid or cache_store is None:
        return None
    pd = cache_store.get(_pd_key(pid))
    if not (isinstance(pd, dict) and isinstance(pd.get("tasks"), list)):
        return None
    name = ((pd.get("project") or {}).get("name") or "")
    b = build(pid, name, pd.get("columns") or [], _merge(pd["tasks"], _done_rows(pid)))
    b.source, b.detail = "cache", "local cache"
    return b


def load(list_id=None, api=None, v2=None):
    """The board LIVE: v1 project data (the open cards + the columns) and v2
    project_completed (the completed ones). Both caches are refreshed on
    the way so the notes and the next keystroke read this same board. v1
    failing = the cache (source "cache", the detail says why); nothing
    readable = BoardError."""
    pid = _list_id(list_id)
    if not pid:
        raise BoardError("no OKR list - okr_list_id is blank (⚙️ Settings → OKR List)")
    try:
        if api is None:
            import config as cfg
            from api import TickTickAPI
            api = TickTickAPI(cfg.get_token())
        data = api.get_project_data(pid)
    except Exception as e:
        b = cached(pid)
        if b is None:
            raise BoardError(f"live read failed ({_why(e)}) and nothing of list {pid} is cached")
        b.detail = f"live read failed ({_why(e)}); the cache"
        return b
    if data == {}:
        raise BoardError(f"list {pid} not found (v1 answered {{}}) - check okr_list_id")
    if not (isinstance(data, dict) and isinstance(data.get("tasks"), list)):
        raise BoardError(f"v1 answered a {type(data).__name__} for list {pid}")
    if cache_store is not None:
        try:
            cache_store.set(_pd_key(pid), data)
        except Exception:
            pass
    n = refresh_done(pid, v2=v2)
    detail = f"v1 open {len(data['tasks'])}" + (
        f"; v2 completed {n}" if n is not None else "; v2 completed unavailable, the cache's")
    name = ((data.get("project") or {}).get("name") or "")
    b = build(pid, name, data.get("columns") or [], _merge(data["tasks"], _done_rows(pid)))
    b.source, b.detail = "live", detail
    return b


# ── what the screens and notes ask ───────────────────────────────────────────
def current_month(board, today=None):
    today = today or date.today()
    return board.month(today.year, today.month)


def home_columns(board, today=None):
    """The hub root's order (Vex 2026-10-03: "current month should be up
    top and rest of the months should be below"): this month (its row
    stays even when the column is missing: None marks that), this year's
    Goals, the months after this one, then each later year's Goals and
    months, and LAST the earlier months that still hold an open key result
    (a leftover he has not dragged on). Empty columns are left out except
    the current month. -> [(Column | None, "now" | "ahead" | "goals" |
    "past")]."""
    today = today or date.today()
    y0, m0 = today.year, today.month
    out = [(board.month(y0, m0), "now")]
    g = board.goals(y0)
    if g is not None and not g.empty:
        out.append((g, "goals"))
    for col in board.columns:
        if col.empty or col.is_goals and col.year <= y0:
            continue
        if col.is_goals:
            out.append((col, "goals"))
        elif (col.year, col.month) > (y0, m0):
            out.append((col, "ahead"))
    past = [c for c in board.months() if (c.year, c.month) < (y0, m0) and c.open_krs]
    out += [(c, "past") for c in past]
    return out


def month_for(kind, p):
    """Which month a `kind` note reads (its 🥅 OKRs section's first bullet):
    its own for a day or a month, the month of its Thursday for a week (the
    ISO rule), the first month for a quarter or a year."""
    if kind == "weekly":
        from datetime import timedelta
        d = p.start + timedelta(days=3)
        return d.year, d.month
    return p.start.year, p.start.month


def quarter_months(p):
    """The three (year, month) of the quarter holding period p's start."""
    q = (p.start.month - 1) // 3
    return [(p.start.year, q * 3 + i) for i in (1, 2, 3)]


def year_months(p):
    return [(p.start.year, m) for m in range(1, 13)]


# ── the report (python3 src/okr_board.py) ────────────────────────────────────
def report(board, today=None):
    out = [f"{board.name or '🔑OKRs'} ({board.list_id}) · {board.source} · {board.detail}",
           f"{len(board.columns)} board columns · {len(board.cards)} cards"
           + (f" · {len(board.unsorted)} in no board column" if board.unsorted else "")]
    for col, why in home_columns(board, today):
        if col is None:
            out.append(f"\n{why}: no column for this month")
            continue
        d, n = col.progress
        out.append(f"\n{col.title}  ({col.long_name}, {why}) · {d}/{n} KRs")
        for a in col.areas:
            ad, an = a.progress
            out.append(f"  {a.label} · {ad}/{an}")
            for o in a.objectives:
                od, on = o.progress
                state = GLYPH_DONE if o.done else (GLYPH_WONTDO if o.abandoned else
                                                   (GLYPH_GOAL if o.kind == "goal" else GLYPH_O))
                extra = ""
                if o.kind == "goal":
                    rd, rn, rm = board.rollup(o)
                    extra = f" · {rd}/{rn} over {rm} month(s)" if rm else " · no objectives"
                out.append(f"    {state} {o.name} {od}/{on}{extra}" + (" 🔗" if o.link else ""))
                for k in o.krs:
                    st = GLYPH_DONE if k.done else (GLYPH_WONTDO if k.abandoned else GLYPH_KR)
                    out.append(f"      {st} {k.name}" + (" 🔗" if k.link else ""))
            for k in a.loose_krs:
                out.append(f"    (loose) {GLYPH_KR} {k.name}")
        for s in col.strays:
            out.append(f"  (stray) {s.glyph} {s.name}")
    return "\n".join(out)


def main():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        b = load()
    except BoardError as e:
        print(f"board unreadable: {e}")
        return 1
    print(report(b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
