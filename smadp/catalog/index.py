"""SQLite FTS5 search index over profiles + verdicts.

The index lives at `<catalog_dir>/_index.sqlite` (gitignored) and is rebuilt
from the JSON sources of truth. Reads use FTS5 ranking; if FTS5 is unavailable
in the local SQLite build, a LIKE-based fallback is used so search still works
in CI and on minimal containers.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from smadp.catalog.repo import CatalogRepo
from smadp.config import Config, load_config


@dataclass(frozen=True)
class SearchHit:
    kind: str  # "profile" | "verdict"
    ref: str  # slug for profiles, "a__b" for verdicts
    title: str
    snippet: str
    score: float


class CatalogIndex:
    """SQLite FTS5 index over the catalog."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self._repo = CatalogRepo(self.config)

    @property
    def db_path(self) -> Path:
        return self.config.catalog_dir / "_index.sqlite"

    # ----------------------------------------------------------------- schema
    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _has_fts5(self, conn: sqlite3.Connection) -> bool:
        try:
            with closing(conn.cursor()) as cur:
                cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x);")
                cur.execute("DROP TABLE _fts5_probe;")
            return True
        except sqlite3.OperationalError:
            return False

    # ------------------------------------------------------------------ build
    def rebuild(self) -> int:
        """Drop and rebuild the entire index. Returns the number of rows indexed."""
        if self.db_path.exists():
            self.db_path.unlink()
        conn = self._connect()
        try:
            fts5 = self._has_fts5(conn)
            with closing(conn.cursor()) as cur:
                if fts5:
                    cur.execute(
                        """
                        CREATE VIRTUAL TABLE docs USING fts5(
                            kind UNINDEXED,
                            ref UNINDEXED,
                            title,
                            body,
                            tokenize = 'porter unicode61'
                        );
                        """
                    )
                else:
                    cur.execute(
                        """
                        CREATE TABLE docs (
                            kind TEXT NOT NULL,
                            ref TEXT NOT NULL,
                            title TEXT NOT NULL,
                            body TEXT NOT NULL
                        );
                        """
                    )
                    cur.execute("CREATE INDEX docs_ref ON docs(ref);")

            count = 0
            with conn:
                # Iterate ALL profile JSONs — including ONEXUS stubs that don't
                # satisfy the strict Profile schema. Stubs get a slim body
                # derived from whatever fields they do carry; fully-validated
                # profiles get the rich body. Either way, one row per file.
                for slug, profile, raw in self._repo.iter_profile_entries():
                    # The FTS5 sanitizer strips hyphens from query terms ("claude-code"
                    # → "claudecode") because `-` is an FTS5 operator. Mirror that
                    # in the body so a slug-based query still matches. Also include
                    # the hyphen-split form so multi-word queries like "claude code"
                    # match.
                    slug_variants = " ".join({slug, slug.replace("-", ""), slug.replace("-", " ")})
                    if profile is not None:
                        title = profile.name
                        body_parts = [
                            slug_variants,
                            profile.name,
                            profile.tagline or "",
                            profile.vendor.handle,
                            profile.category,
                            " ".join(profile.io_surfaces.calls_apis or []),
                            " ".join(profile.data_classes_touched or []),
                        ]
                        cap_terms = [
                            name
                            for name, on in profile.capabilities.model_dump().items()
                            if isinstance(on, bool) and on
                        ]
                        body_parts.append(" ".join(cap_terms))
                    else:
                        title = str(raw.get("name", slug))
                        body_parts = [
                            slug_variants,
                            title,
                            str(raw.get("category", "")),
                            str(raw.get("tagline", "")),
                        ]
                    body = " ".join(p for p in body_parts if p).strip()
                    conn.execute(
                        "INSERT INTO docs (kind, ref, title, body) VALUES (?, ?, ?, ?)",
                        ("profile", slug, title, body),
                    )
                    count += 1

                for verdict in self._repo.list_verdicts():
                    a, b = verdict.pair
                    ref = f"{a}__{b}"
                    title = verdict.headline
                    body_parts = [verdict.headline]
                    for sv_name in (
                        "A_prompt_injection",
                        "B_data_leakage",
                        "C_capability_conflict",
                        "D_cascading_error",
                        "E_compliance",
                    ):
                        sv = getattr(verdict.sub_verdicts, sv_name)
                        body_parts.append(sv.rationale)
                    body = " ".join(body_parts).strip()
                    conn.execute(
                        "INSERT INTO docs (kind, ref, title, body) VALUES (?, ?, ?, ?)",
                        ("verdict", ref, title, body),
                    )
                    count += 1
            return count
        finally:
            conn.close()

    # ----------------------------------------------------------------- search
    def search(self, query: str, *, limit: int = 50) -> list[SearchHit]:
        if not self.db_path.exists():
            self.rebuild()
        if not query.strip():
            return []
        conn = self._connect()
        try:
            fts5 = self._has_fts5(conn)
            hits: list[SearchHit] = []
            with closing(conn.cursor()) as cur:
                if fts5:
                    try:
                        # Exact-ref boost: rows whose `ref` matches the bare
                        # query string (the slug, e.g. "claude-code") rank
                        # FIRST regardless of bm25. Substring/partial bm25
                        # matches follow. Without this, a query for a known
                        # slug gets out-ranked by dozens of look-alike slugs
                        # in the long-tail ONEXUS catalog.
                        cur.execute(
                            """
                            SELECT kind, ref, title,
                                   snippet(docs, 3, '<mark>', '</mark>', '...', 16) AS snip,
                                   bm25(docs) AS rank,
                                   CASE WHEN ref = ? THEN 0 ELSE 1 END AS exact_rank
                            FROM docs
                            WHERE docs MATCH ?
                            ORDER BY exact_rank, rank
                            LIMIT ?;
                            """,
                            (query.strip(), _sanitize_fts5(query), limit),
                        )
                    except sqlite3.OperationalError:
                        # malformed FTS5 query — fall back to LIKE
                        return self._like_search(conn, query, limit)
                    for row in cur.fetchall():
                        hits.append(
                            SearchHit(
                                kind=row["kind"],
                                ref=row["ref"],
                                title=row["title"],
                                snippet=row["snip"],
                                # bm25 returns lower-is-better; invert so
                                # higher-is-better for downstream consumers.
                                score=-float(row["rank"]),
                            )
                        )
                    return hits
                return self._like_search(conn, query, limit)
        finally:
            conn.close()

    def _like_search(
        self,
        conn: sqlite3.Connection,
        query: str,
        limit: int,
    ) -> list[SearchHit]:
        like = f"%{query.lower()}%"
        with closing(conn.cursor()) as cur:
            cur.execute(
                """
                SELECT kind, ref, title, body
                FROM docs
                WHERE LOWER(title) LIKE ? OR LOWER(body) LIKE ?
                LIMIT ?;
                """,
                (like, like, limit),
            )
            return [
                SearchHit(
                    kind=row["kind"],
                    ref=row["ref"],
                    title=row["title"],
                    snippet=_make_snippet(row["body"], query),
                    score=1.0,
                )
                for row in cur.fetchall()
            ]


_FTS5_SPECIALS = set("\"'(){}[]:!*+-")


def _sanitize_fts5(query: str) -> str:
    """Quote each whitespace-separated term to defang FTS5 operators."""
    out: list[str] = []
    for term in query.split():
        cleaned = "".join(c for c in term if c not in _FTS5_SPECIALS)
        if not cleaned:
            continue
        out.append(f'"{cleaned}"')
    if not out:
        return f'"{query.replace(chr(34), "")}"'
    return " ".join(out)


def _make_snippet(body: str, query: str, *, width: int = 80) -> str:
    lower = body.lower()
    idx = lower.find(query.lower())
    if idx == -1:
        return body[: width * 2]
    start = max(0, idx - width // 2)
    end = min(len(body), idx + len(query) + width // 2)
    snippet = body[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(body):
        snippet = snippet + "..."
    return snippet
