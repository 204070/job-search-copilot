"""The question bank: what forms ask, what was answered, and why.

    python3 -m db.tools.questions lookup "compensation"        # before you fill
    python3 -m db.tools.questions record --key <slug> \\
        --question "<the form's question>" --answer "<the answer>" \\
        --label "<this form's label>" --field-type text \\
        --application-id <id> --required                      # after you fill
    python3 -m db.tools.questions frequency                    # what recurs
    python3 -m db.tools.questions promotions                   # facts -> profile.jsonc
    python3 -m db.tools.questions retire --key <slug>           # never reuse this one
    python3 -m db.tools.questions digest --kind application    # regenerate the FAQ

Two layers, one source of truth:

- `questions` is the canonical, deduped row: the answer (or a pointer into
  `artifacts/profile.jsonc` for facts), the reasoning, and the aliases a form
  might use. No dates, no companies.
- `question_instances` is the append-only ledger of every time a form actually
  asked it, carrying the date, company and the option list that form showed.

"Frequently asked" is therefore a COUNT over instances, never a judgement
call: `lookup` finds what has been seen before, `frequency` ranks it, and a
lookup MISS is the signal that a question is new.

An answer's state is derived the same way, from the ledger, and is never
stored: `unsent` if no submitted application has carried it, `sent` if the
stored text is exactly what an employer received, `revised` if it went out and
has changed since (so the current wording is unread), and `retired` if it has
deliberately been set aside, the only state a human writes.

The FAQ markdown in `artifacts/faqs/` is a GENERATED view of this bank (see
`digest`) plus your own interview notes. Record here, then regenerate there;
never hand-maintain two copies of the same answer.

Everything in this bank is private (salary expectations, work authorization),
so it lives in the gitignored database and is never written to a migration or
a committed seed.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # repo root

from db import connect  # noqa: E402

KINDS = ("application", "technical")
FIELD_TYPES = ("text", "combobox", "textarea", "checkbox", "other")
#: The answer's state. Derived on read by `questions_with_frequency` from the
#: instance ledger, never stored, so nothing can set it from a command line.
STATES = ("unsent", "sent", "revised", "retired")

ROOT = Path(__file__).resolve().parent.parent.parent
FAQ_DIR = ROOT / "artifacts" / "faqs"
FAQ_PATHS = {
    "application": FAQ_DIR / "application-faq.md",
    "technical": FAQ_DIR / "technical-faq.md",
}


def now_iso() -> str:
    """Current time as ISO-8601 UTC text, matching the schema default."""
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    """A stable `question_key` slug: lowercase, non-alphanumerics to `_`.

    Long questions are cut at a word boundary rather than mid-word, so the
    derived key stays readable (agents can still pass an explicit `--key`).
    """
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    if len(slug) > 60 and "_" in slug[:60]:
        slug = slug[:60].rsplit("_", 1)[0]
    return slug[:60] or "question"


def _json_list(raw: str | list[str] | None) -> str:
    """Normalise a JSON array value, rejecting anything that is not a list."""
    if raw is None:
        return "[]"
    if isinstance(raw, list):
        return json.dumps([str(item) for item in raw])
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(value, list):
        raise SystemExit(f"expected a JSON array, got: {raw!r}")
    return json.dumps([str(item) for item in value])


def _dedupe(items: list[str]) -> list[str]:
    """Case-insensitive de-dupe that keeps first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def has_fts(conn: sqlite3.Connection) -> bool:
    """True when the FTS5 index is present (it is not required to function)."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'questions_fts'"
    ).fetchone()
    return row is not None


# --- record ----------------------------------------------------------------


def record(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Upsert the canonical question and append one instance ledger row."""
    for flag, table, value in (
        ("--job-id", "jobs", args.job_id),
        ("--application-id", "applications", args.application_id),
    ):
        if value is not None and not conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (value,)
        ).fetchone():
            raise SystemExit(
                f"{flag} {value} has no row in `{table}`; fix the id, or drop the"
                " flag if this question is not tied to a specific application."
            )

    if args.promotes_to is not None and args.clear_promotes_to:
        raise SystemExit("--promotes-to and --clear-promotes-to are mutually exclusive")
    # `--clear-promotes-to` is the inverse of `--promotes-to`: a question that
    # looked like a profile fact but turned out to be answered case by case
    # (compensation expectations) should go back to being bank-only.
    promotes_to = None if args.clear_promotes_to else args.promotes_to

    row: sqlite3.Row | None = None
    if args.key:
        row = conn.execute(
            "SELECT * FROM questions WHERE question_key = ?", (args.key,)
        ).fetchone()
    if row is None and args.question:
        row = conn.execute(
            "SELECT * FROM questions WHERE lower(canonical_text) = lower(?)",
            (args.question,),
        ).fetchone()

    aliases = list(args.alias)
    if args.label:
        aliases.append(args.label)

    if row is None:
        if not args.question:
            raise SystemExit("a new question needs --question (or an existing --key)")
        key = args.key or slugify(args.question)
        if conn.execute(
            "SELECT 1 FROM questions WHERE question_key = ?", (key,)
        ).fetchone():
            key = f"{key}_{now_iso()[:10].replace('-', '')}"
        aliases = _dedupe(aliases)
        cur = conn.execute(
            "INSERT INTO questions (question_key, kind, canonical_text, answer,"
            " reasoning, answer_source, aliases, promotes_to, metadata)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                args.kind,
                args.question,
                args.answer,
                args.reasoning,
                args.source or ("answer_bank" if args.answer else None),
                json.dumps(aliases),
                promotes_to,
                "{}",
            ),
        )
        qid = int(cur.lastrowid or 0)
        created = True
    else:
        qid = int(row["id"])
        key = row["question_key"]
        existing = json.loads(row["aliases"] or "[]")
        merged = _dedupe(existing + aliases)
        updates: dict[str, object] = {"aliases": json.dumps(merged)}
        if args.kind and args.kind != row["kind"]:
            updates["kind"] = args.kind
        if args.question and args.question != row["canonical_text"]:
            updates["canonical_text"] = args.question
        for field, value in (
            ("answer", args.answer),
            ("reasoning", args.reasoning),
            ("answer_source", args.source),
        ):
            if value is not None:
                updates[field] = value
        if args.promotes_to is not None or args.clear_promotes_to:
            updates["promotes_to"] = promotes_to
        assignments = ", ".join(f"{name} = ?" for name in updates)
        conn.execute(
            f"UPDATE questions SET {assignments}, updated_at = ? WHERE id = ?",
            [*updates.values(), now_iso(), qid],
        )
        created = False

    asked = any(
        [
            args.label,
            args.answer_given,
            args.field_type,
            args.option,
            args.job_id,
            args.application_id,
            args.required,
        ]
    )
    instance_id: int | None = None
    if asked:
        canonical = conn.execute(
            "SELECT answer FROM questions WHERE id = ?", (qid,)
        ).fetchone()
        answer_given = (
            args.answer_given
            if args.answer_given is not None
            else (args.answer or (canonical["answer"] if canonical else None))
        )
        cur = conn.execute(
            "INSERT INTO question_instances (question_id, application_id, job_id,"
            " field_label, field_type, required, options_seen, answer_given,"
            " asked_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')",
            (
                qid,
                args.application_id,
                args.job_id,
                args.label or args.question,
                args.field_type,
                1 if args.required else 0,
                _json_list(args.option),
                answer_given,
                args.asked_at or now_iso(),
            ),
        )
        instance_id = int(cur.lastrowid or 0)

    conn.commit()
    times = conn.execute(
        "SELECT times_asked FROM questions_with_frequency WHERE id = ?", (qid,)
    ).fetchone()["times_asked"]
    verb = "created" if created else "updated"
    print(f"{verb} question #{qid} `{key}` ({args.kind}) - asked {times}x")
    if instance_id is not None:
        print(f"  instance #{instance_id}: {args.label or args.question}")
    return 0


# --- lookup ----------------------------------------------------------------


#: Words too common in a form label to signal which question is being asked.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with",
    "is", "are", "was", "be", "do", "does", "did", "you", "your", "yours",
    "we", "us", "i", "my", "me", "our", "this", "that", "these", "those",
    "what", "which", "who", "whom", "how", "when", "where", "why", "please",
    "if", "it", "its", "as", "by", "from", "any", "all", "have", "has", "will",
    "would", "can", "could", "should", "there", "here", "about", "tell",
})


def _terms(text: str) -> list[str]:
    """Meaningful lower-case tokens: split on non-alphanumerics, drop stopwords."""
    return [
        token
        for token in re.split(r"[^A-Za-z0-9]+", text.lower())
        if token and token not in _STOPWORDS
    ]


def _fts_query(text: str) -> str:
    """Turn a form label into a safe FTS5 MATCH query (quoted OR'd tokens)."""
    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", text) if token]
    return " OR ".join(f'"{token}"' for token in tokens) or '""'


def _candidates(
    conn: sqlite3.Connection, text: str, kind: str | None, limit: int
) -> list:
    """Broad recall pass: FTS5 when available, else a LIKE scan."""
    if has_fts(conn):
        sql = (
            "SELECT f.*, bm25(questions_fts) AS rank"
            " FROM questions_fts JOIN questions_with_frequency f"
            " ON f.id = questions_fts.rowid"
            " WHERE questions_fts MATCH ? AND f.retired_at IS NULL"
        )
        params: list[object] = [_fts_query(text)]
        if kind:
            sql += " AND f.kind = ?"
            params.append(kind)
        sql += " ORDER BY rank, f.times_asked DESC LIMIT ?"
        params.append(limit)
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            pass  # malformed query for this index; fall through to LIKE

    pattern = f"%{text.lower()}%"
    sql = (
        "SELECT *, 0.0 AS rank FROM questions_with_frequency WHERE retired_at IS NULL"
        " AND (lower(canonical_text) LIKE ? OR lower(coalesce(answer, '')) LIKE ?"
        " OR lower(aliases) LIKE ?)"
    )
    params = [pattern, pattern, pattern]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY times_asked DESC, question_key LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def _overlap(row, terms: list[str]) -> int:
    """How many query terms actually appear in this question's wording."""
    haystack = " ".join(
        part for part in (row["canonical_text"], row["answer"], row["aliases"]) if part
    ).lower()
    words = set(re.split(r"[^a-z0-9]+", haystack))
    return sum(1 for term in terms if term in words)


def lookup(conn: sqlite3.Connection, text: str, kind: str | None, limit: int) -> list:
    """Questions a form label plausibly refers to, best match first.

    Broad recall (OR over tokens) would otherwise match on any shared common
    word, so candidates must clear a token-overlap floor. A query with no
    candidate above the floor is a MISS, which is the signal that the question
    is new. Overlap is deliberately crude; aliases are the lever when a form's
    wording shares no words with the canonical text.
    """
    terms = _terms(text)
    candidates = _candidates(conn, text, kind, max(limit * 5, 25))
    if not terms:
        return candidates[:limit]
    floor = 1 if len(terms) <= 2 else max(2, math.ceil(len(terms) * 0.5))
    scored = [(overlap, row) for row in candidates if (overlap := _overlap(row, terms)) >= floor]
    scored.sort(key=lambda pair: (-pair[0], -(pair[1]["times_asked"] or 0)))
    return [row for _, row in scored][:limit]


def print_matches(rows: list, index: int | None = None) -> None:
    """Render lookup results readably: answer, state, reasoning, frequency."""
    for i, row in enumerate(rows, 1):
        prefix = f"{index}. " if index is not None else ""
        label = f"{prefix}{row['canonical_text']}" if prefix else row["canonical_text"]
        print(f"{label}")
        print(
            f"   `{row['question_key']}` | {row['kind']} | {row['state']} |"
            f" asked {row['times_asked']}x | last {row['last_asked_at'] or 'never'}"
        )
        if row["state"] == "revised":
            print("   NOTE    sent as older text; the answer below has not been"
                  " read in this form and differs from what went out:")
            print(f"           sent: {_indent(row['last_sent_text'] or '')}")
        if row["answer_source"] and row["answer_source"].startswith("profile:"):
            print(f"   ANSWER  {row['answer_source']} (single source of truth)")
            if row["answer"]:
                print(f"           bank copy: {_indent(row['answer'])}")
        elif row["answer"]:
            print(f"   ANSWER  {_indent(row['answer'])}")
        elif row["state"] != "unsent":
            print("   ANSWER  (none stored; filled per application, see WHY)")
        if row["reasoning"]:
            print(f"   WHY     {_indent(row['reasoning'])}")
        if row["promotes_to"] and not (
            row["answer_source"] or ""
        ).startswith("profile:"):
            print(f"   PROMOTE {row['promotes_to']} (pending profile.jsonc)")
        aliases = json.loads(row["aliases"] or "[]")
        if aliases:
            print(f"   also    {'; '.join(aliases)}")
        for inst in row["_instances"] if "_instances" in row.keys() else []:
            print(f"   seen    {inst}")
        print()


def _indent(text: str, pad: str = "           ") -> str:
    """Indent every line of a multi-line value to sit under its label."""
    lines = text.splitlines() or [""]
    return ("\n" + pad).join(lines)


def _evidence(conn: sqlite3.Connection, question_id: int) -> list[str]:
    """One compact line per instance: when, for whom, the exact label, options."""
    rows = conn.execute(
        "SELECT i.asked_at, i.field_label, i.field_type, i.required, i.options_seen,"
        " j.title, j.company"
        " FROM question_instances i LEFT JOIN jobs j ON j.id = i.job_id"
        " WHERE i.question_id = ? ORDER BY i.asked_at DESC, i.id DESC",
        (question_id,),
    ).fetchall()
    out = []
    for row in rows:
        where = " - ".join(x for x in (row["company"], row["title"]) if x)
        detail = row["field_type"] or "?"
        if row["required"]:
            detail += ", required"
        options = json.loads(row["options_seen"] or "[]")
        if options:
            detail += ": " + " / ".join(options[:6])
            if len(options) > 6:
                detail += f" (+{len(options) - 6} more)"
        line = f"{row['asked_at'][:10]} {row['field_label']!r} ({detail})"
        out.append(f"{line} [{where}]" if where else line)
    return out


def cmd_lookup(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    rows = lookup(conn, args.query, args.kind, args.limit)
    if not rows:
        print(f"no canonical question matches {args.query!r} ({args.kind or 'any kind'}).")
        print("Novel question: answer it, then `record` it so the next form finds it.")
        return 1
    print(f"{len(rows)} match(es) for {args.query!r}:\n")
    for row in rows:
        as_dict = dict(row)
        as_dict["_instances"] = _evidence(conn, row["id"]) if args.evidence else []
        print_matches([as_dict])
    return 0


# --- retire ----------------------------------------------------------------


def cmd_retire(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Set an answer aside, or bring it back into use.

    The only state a human sets in this bank. Whether an answer has ever
    reached an employer, and whether the stored text still matches what did, is
    derived from the instance ledger, so submitting an application is the whole
    of that bookkeeping. Retirement is different: it is a decision never to
    reuse text, and nothing in the ledger implies one.
    """
    changed = 0
    for key in args.key:
        row = conn.execute(
            "SELECT id, retired_at FROM questions WHERE question_key = ?", (key,)
        ).fetchone()
        if row is None:
            print(f"no question with key {key!r}")
            continue
        if args.undo:
            if row["retired_at"] is None:
                print(f"{key}: not retired, nothing to undo")
                continue
            conn.execute(
                "UPDATE questions SET retired_at = NULL, updated_at = ? WHERE id = ?",
                (now_iso(), row["id"]))
            print(f"{key}: back in use")
        else:
            if row["retired_at"] is not None:
                print(f"{key}: already retired ({row['retired_at'][:10]})")
                continue
            conn.execute(
                "UPDATE questions SET retired_at = ?, updated_at = ? WHERE id = ?",
                (now_iso(), now_iso(), row["id"]))
            print(f"{key}: retired; a lookup will no longer offer it")
        changed += 1
    conn.commit()
    if not changed:
        print("nothing changed. Pass --key KEY (repeatable), and --undo to reverse.")
        return 1
    return 0


# --- frequency / promotions ------------------------------------------------


def cmd_frequency(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    sql = "SELECT * FROM questions_with_frequency WHERE retired_at IS NULL"
    params: list[object] = []
    if args.kind:
        sql += " AND kind = ?"
        params.append(args.kind)
    if args.min_count > 1:
        sql += " AND times_asked >= ?"
        params.append(args.min_count)
    sql += " ORDER BY times_asked DESC, last_asked_at DESC, question_key"
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        print("question bank is empty; record answers as you fill forms")
        return 0
    width = max(len(row["question_key"]) for row in rows)
    print(f"{'key':<{width}}  {'kind':<11} {'asked':>5}  last         question")
    for row in rows:
        print(
            f"{row['question_key']:<{width}}  {row['kind']:<11}"
            f" {row['times_asked']:>5}  {(row['last_asked_at'] or '-')[:10]:<12}"
            f" {row['canonical_text']}"
        )
    return 0


def _pending_promotions(
    conn: sqlite3.Connection, kind: str | None = None
) -> list[sqlite3.Row]:
    """Questions whose answer should move into profile.jsonc but has not yet."""
    sql = (
        "SELECT * FROM questions_with_frequency WHERE promotes_to IS NOT NULL"
        " AND (answer_source IS NULL OR answer_source NOT LIKE 'profile:%')"
    )
    params: list[object] = []
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY times_asked DESC, question_key"
    return conn.execute(sql, params).fetchall()


def cmd_promotions(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    rows = _pending_promotions(conn, args.kind)
    if not rows:
        print("no pending profile promotions")
        return 0
    print(f"{len(rows)} fact(s) waiting to move into artifacts/profile.jsonc:\n")
    for row in rows:
        print(f"- {row['promotes_to']}  <- {row['canonical_text']}")
        if row["answer"]:
            print(f"    answer: {_indent(row['answer'], '            ')}")
        print(f"    (asked {row['times_asked']}x, `{row['question_key']}`)")
    print("\nAdd each to profile.jsonc, then re-record with")
    print("  --source 'profile:<path>' so the bank stops holding a second copy.")
    return 0


# --- digest (regenerate the FAQ docs) --------------------------------------


def _block(label: str, value: str) -> list[str]:
    """Render a labelled field: inline when short, as a paragraph when multi-line."""
    value = (value or "").strip()
    if not value:
        return []
    if "\n" in value:
        return [f"**{label}:**", "", value, ""]
    return [f"**{label}:** {value}", ""]


def render_digest(conn: sqlite3.Connection, kind: str) -> str:
    """Render the human-facing FAQ for one kind from the bank."""
    title = {
        "application": "Non-Technical Application Questions & Answers",
        "technical": "Technical Interview Questions & Answers",
    }[kind]
    lines = [
        f"# {title}",
        "",
        "> Generated from the question bank; do not hand-edit this file. Record",
        "> answers with `record`, then regenerate:",
        f"> `python3 -m db.tools.questions digest --kind {kind}"
        f" --out artifacts/faqs/{FAQ_PATHS[kind].name}`.",
        ">",
        "> The state on each entry is derived from the instance ledger, not",
        "> maintained by hand: `unsent` means no submitted application has ever",
        "> carried this question, `sent` that the answer listed is exactly what an",
        "> employer received, and `revised` that it went out and the text has",
        "> changed since, so the current wording has not been read in this form.",
        "",
    ]

    pending = _pending_promotions(conn, kind)
    if pending:
        lines += ["## Pending profile promotions", ""]
        for row in pending:
            lines.append(f"- `{row['promotes_to']}` from {row['canonical_text']}")
        lines.append("")

    rows = conn.execute(
        "SELECT * FROM questions_with_frequency WHERE kind = ? AND retired_at IS NULL"
        " ORDER BY times_asked DESC, last_asked_at DESC, question_key",
        (kind,),
    ).fetchall()
    if not rows:
        lines.append("_No questions recorded yet._")
        return "\n".join(lines) + "\n"

    for row in rows:
        meta = f"`{row['question_key']}` - {row['state']} - asked {row['times_asked']}x"
        if row["last_asked_at"]:
            meta += f" - last {row['last_asked_at'][:10]}"
        lines += [f"## {row['canonical_text']}", "", meta, ""]

        if row["state"] == "revised":
            lines += [
                "> **Sent as older text.** The answer below is not what the form"
                " actually received, so nobody has read it in this form. It was:",
                f"> {row['last_sent_text']}",
                "",
            ]

        if (row["answer_source"] or "").startswith("profile:"):
            lines += [f"**Answer:** from `{row['answer_source']}` (profile.jsonc).", ""]
            if row["answer"]:
                lines += [f"_Bank copy: {row['answer']}_", ""]
        elif row["answer"]:
            lines += _block("Answer", row["answer"])

        metadata = json.loads(row["metadata"] or "{}")
        if metadata.get("original_answer"):
            lines += _block("Earlier answer", metadata["original_answer"])

        if row["reasoning"]:
            lines += _block("Reasoning", row["reasoning"])

        aliases = json.loads(row["aliases"] or "[]")
        if aliases:
            lines += [f"**Also asked as:** {'; '.join(aliases)}", ""]

        evidence = _evidence(conn, row["id"])
        if evidence:
            lines.append("**Evidence:**")
            lines += [f"- {item}" for item in evidence]
            lines.append("")

        lines += ["---", ""]

    return "\n".join(lines).rstrip() + "\n"


def cmd_digest(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    text = render_digest(conn, args.kind)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


# --- import (one-off migration from the pre-bank FAQ files) ----------------

_FIELD_RE = re.compile(r"^\*\*(?P<name>[^*]+?):\*\*\s?(?P<inline>.*)$")

#: Canonical keys for the questions the first two FAQ files happened to use.
#: Only applies to this one-off import; new questions get a slugified key.
_IMPORT_KEYS = {
    "what are your compensation expectations": "compensation_expectation",
    "are you currently authorized to work in the us for any employer":
        "us_work_authorization",
    "do you now or in the future require sponsorship for a us based role":
        "us_sponsorship_required",
    "do you have a non compete clause with your current employer": "non_compete",
    "where are you currently located city": "current_city",
    "where are you currently located state": "current_state",
    "i understand that to qualify for green card sponsorship i must be employed "
    "for at least one year and remain in good standing":
        "green_card_sponsorship_acknowledgement",
    "in go concurrency everyone has trade offs they prefer to make which "
    "concurrency tools or patterns in go do you tend to favor and why":
        "go_concurrency_patterns",
}

#: Questions the bank already knows are facts profile.jsonc owns, so their
#: answer points there instead of being a second copy. Only entries whose
#: profile value was verified are listed.
_IMPORT_SOURCES = {
    "current_city": "profile:$.location.city",
}


def _split_fields(body: str) -> dict[str, str]:
    """Split a block body into {label: text} on `**Label:**` lines."""
    fields: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        match = _FIELD_RE.match(line)
        if match:
            if current is not None:
                fields[current] = "\n".join(buf).strip()
            current = match.group("name").strip()
            inline = match.group("inline").strip()
            buf = [inline] if inline else []
        elif current is not None:
            buf.append(line)
    if current is not None:
        fields[current] = "\n".join(buf).strip()
    return fields


def _unquote(text: str) -> str:
    """Strip `> ` blockquote markers so an answer reads as plain text."""
    lines = [re.sub(r"^>\s?", "", line).rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def _reasoning(context: str | None, reflection: str | None, action: str | None) -> str | None:
    parts = []
    if context:
        parts.append(f"Context: {context}")
    if reflection:
        parts.append(f"Reflection: {reflection}")
    if action:
        parts.append(f"Action: {action}")
    return "\n".join(parts) or None


def _promotes_to(action: str | None) -> str | None:
    """Pull a profile JSON path out of an Action line's backticked `key:`."""
    match = re.search(r"`([A-Za-z_][A-Za-z0-9_]*)\s*:", action or "")
    return f"$.{match.group(1)}" if match else None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def parse_application_faq(text: str) -> list[dict]:
    """Parse the application FAQ's `### "Question" (attrs)` blocks."""
    body = text.split("\n## ")[0]
    entries: list[dict] = []
    for part in re.split(r"^### ", body, flags=re.M)[1:]:
        heading, _, rest = part.partition("\n")
        match = re.match(r'^"(?P<q>.+?)"\s*(?:\((?P<attrs>.*)\))?\s*$', heading.strip())
        if not match:
            continue
        question = match.group("q").strip()
        attrs = (match.group("attrs") or "").lower()
        fields = _split_fields(re.split(r"^\s*---\s*$", rest, flags=re.M)[0])
        field_type = next((t for t in FIELD_TYPES if t in attrs), None)
        action = fields.get("Action")
        key = _IMPORT_KEYS.get(_norm(question), slugify(question))
        answer = fields.get("Answer given") or None
        entries.append(
            {
                "question_key": key,
                "kind": "application",
                "canonical_text": question,
                "answer": answer,
                "answer_source": _IMPORT_SOURCES.get(key)
                or ("answer_bank" if answer else None),
                "reasoning": _reasoning(
                    fields.get("Context"), fields.get("Reflection"), action
                ),
                "promotes_to": _promotes_to(action),
                "aliases": [],
                "required": "required" in attrs,
                "field_type": field_type,
                "metadata": {},
            }
        )
    return entries


def parse_technical_faq(text: str) -> list[dict]:
    """Parse the technical FAQ's `**Question:**` blocks."""
    body = text.split("\n## ")[0]
    entries: list[dict] = []
    for part in re.split(r"^\*\*Question:\*\*", body, flags=re.M)[1:]:
        question_line, _, rest = part.partition("\n")
        raw_question = question_line.strip()
        question = raw_question.strip('"').strip()
        if not question:
            continue
        fields = _split_fields(re.split(r"^\s*---\s*$", rest, flags=re.M)[0])
        given = _unquote(fields.get("Answer given", ""))
        improved = _unquote(fields.get("Improved answer for next time", ""))
        answer = improved or given or None
        metadata = {}
        if improved and given:
            metadata["original_answer"] = given
        key = _IMPORT_KEYS.get(_norm(question), slugify(question))
        entries.append(
            {
                "question_key": key,
                "kind": "technical",
                "canonical_text": question,
                "answer": answer,
                "answer_source": "answer_bank" if answer else None,
                "reasoning": _reasoning(fields.get("Context"), fields.get("Reflection"), None),
                "promotes_to": None,
                "aliases": [],
                "required": True,
                "field_type": "textarea",
                "metadata": metadata,
            }
        )
    return entries


def _insert_entry(conn: sqlite3.Connection, entry: dict, asked_at: str) -> str:
    """Insert one parsed FAQ entry; returns 'created' or 'updated'."""
    key = entry["question_key"]
    row = conn.execute(
        "SELECT id FROM questions WHERE question_key = ?", (key,)
    ).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO questions (question_key, kind, canonical_text, answer,"
            " reasoning, answer_source, aliases, promotes_to, metadata,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                entry["kind"],
                entry["canonical_text"],
                entry["answer"],
                entry["reasoning"],
                entry.get("answer_source"),
                json.dumps(entry["aliases"]),
                entry["promotes_to"],
                json.dumps(entry["metadata"]),
                asked_at,
                asked_at,
            ),
        )
        qid = int(cur.lastrowid or 0)
        outcome = "created"
    else:
        qid = int(row["id"])
        conn.execute(
            "UPDATE questions SET answer = coalesce(?, answer),"
            " reasoning = coalesce(?, reasoning), promotes_to = coalesce(?, promotes_to),"
            " answer_source = coalesce(?, answer_source),"
            " metadata = ?, updated_at = ? WHERE id = ?",
            (
                entry["answer"],
                entry["reasoning"],
                entry["promotes_to"],
                entry.get("answer_source"),
                json.dumps(entry["metadata"]),
                asked_at,
                qid,
            ),
        )
        outcome = "updated"
    # Idempotent for re-runs: one imported instance per question, but the
    # canonical row above still updates.
    already = conn.execute(
        "SELECT 1 FROM question_instances WHERE question_id = ?"
        " AND json_extract(metadata, '$.via') = 'import-faq'",
        (qid,),
    ).fetchone()
    if already:
        return f"{outcome} `{key}` (instance already imported)"
    conn.execute(
        "INSERT INTO question_instances (question_id, field_label, field_type,"
        " required, options_seen, answer_given, asked_at, metadata)"
        " VALUES (?, ?, ?, ?, '[]', ?, ?, '{\"via\": \"import-faq\"}')",
        (
            qid,
            entry["canonical_text"],
            entry["field_type"],
            1 if entry["required"] else 0,
            entry["answer"],
            asked_at,
        ),
    )
    return f"{outcome} `{key}`"

def cmd_import_faq(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    paths = [args.path] if args.path else list(FAQ_PATHS.values())
    parsers = {
        "application": parse_application_faq,
        "technical": parse_technical_faq,
    }
    asked_at = now_iso()
    total = 0
    for path in paths:
        if not path.is_file():
            print(f"skip {path} (not found)")
            continue
        text = path.read_text(encoding="utf-8")
        # A file with `**Question:**` blocks is technical, otherwise application.
        kind = "technical" if "**Question:**" in text else "application"
        entries = parsers[kind](text)
        print(f"{path.name}: {len(entries)} {kind} entr(ies)")
        for entry in entries:
            if args.dry_run:
                print(f"  would import `{entry['question_key']}`: {entry['canonical_text']}")
                continue
            print(f"  {_insert_entry(conn, entry, asked_at)}")
        total += len(entries)
    if not args.dry_run:
        conn.commit()
        print(f"imported {total} question(s)")
    return 0


# --- self-test --------------------------------------------------------------


def cmd_selftest() -> int:
    """Drive one answer through every derived state on a throwaway database.

    The state is a CASE arm inside a view, which is the place a bug hides best:
    a wrong arm still returns a row, it just mislabels it. This runs the
    committed migrations against an empty database and moves one question
    through all four states, including the two cases that are easy to get
    wrong: an application that was never submitted must not count as an
    employer having received the text, and one that did go out must keep
    counting after it is later withdrawn.
    """
    from db.migrate import run_migrations

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "selftest.db"
        run_migrations(db_path=db_path)
        conn = connect(db_path)
        try:
            conn.execute(
                "INSERT INTO jobs (title, company) VALUES ('Test Role', 'Northwind')")
            job_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            conn.execute(
                "INSERT INTO applications (job_id, status, applied_at)"
                " VALUES (?, 'applied', '2026-10-18T00:00:00Z')", (job_id,))
            sent_app = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            conn.execute(
                "INSERT INTO applications (job_id, status) VALUES (?, 'ready_to_apply')",
                (job_id,))
            draft_app = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            conn.execute(
                "INSERT INTO questions (question_key, canonical_text, answer)"
                " VALUES ('k', 'What is your answer?', 'A')")
            qid = conn.execute(
                "SELECT id FROM questions WHERE question_key = 'k'").fetchone()["id"]

            def state() -> str:
                return conn.execute(
                    "SELECT state FROM questions_with_frequency"
                    " WHERE question_key = 'k'").fetchone()["state"]

            def asked(application_id: int, given: str) -> None:
                conn.execute(
                    "INSERT INTO question_instances (question_id, application_id,"
                    " field_label, answer_given) VALUES (?, ?, 'Your answer?', ?)",
                    (qid, application_id, given))

            def check(desc: str, want: str) -> None:
                nonlocal failures
                got = state()
                if got == want:
                    print(f"ok   {desc:<48} -> {got}")
                else:
                    failures += 1
                    print(f"FAIL {desc:<48} -> {got}, wanted {want}")

            check("no form has ever asked it", "unsent")
            asked(draft_app, "A")
            check("asked on an application never submitted", "unsent")
            asked(sent_app, "A")
            check("that exact text reached an employer", "sent")
            conn.execute("UPDATE questions SET answer = 'B' WHERE id = ?", (qid,))
            check("stored text changed after it went out", "revised")
            conn.execute(
                "UPDATE question_instances SET answer_given = 'B'"
                " WHERE application_id = ?", (sent_app,))
            check("a later form carried the new text", "sent")
            conn.execute(
                "UPDATE applications SET status = 'withdrawn' WHERE id = ?", (sent_app,))
            check("withdrawn after it had been sent", "sent")
            conn.execute(
                "UPDATE questions SET retired_at = '2026-10-18T00:00:00Z' WHERE id = ?",
                (qid,))
            check("retired", "retired")
            conn.execute("UPDATE questions SET retired_at = NULL WHERE id = ?", (qid,))
            check("retirement undone", "sent")

            produced = {
                row["state"]
                for row in conn.execute("SELECT state FROM questions_with_frequency")
            }
            unknown = produced - set(STATES)
            if unknown:
                failures += 1
                print(f"FAIL view produced unknown state(s): {sorted(unknown)}")
            else:
                print(f"ok   {'every state the view produced is known':<48} "
                      f"-> {'/'.join(sorted(produced))}")
        finally:
            conn.close()

    total = 9
    print(f"{total - failures}/{total} cases pass")
    return 1 if failures else 0


# --- CLI -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m db.tools.questions",
        description="The application/interview question bank.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("record", help="upsert a question and append an instance")
    p.add_argument("--key", help="stable question_key; derived from --question if omitted")
    p.add_argument("--question", help="canonical wording (required for a new question)")
    p.add_argument("--kind", choices=KINDS, default="application")
    p.add_argument("--answer", help="the reusable answer text")
    p.add_argument("--reasoning", help="why this answer; the part to not lose")
    p.add_argument("--source", help="answer_source, e.g. 'profile:$.compensation_expectation'")
    p.add_argument("--promotes-to", dest="promotes_to", help="profile.jsonc path to promote to")
    p.add_argument(
        "--clear-promotes-to", dest="clear_promotes_to", action="store_true",
        help="drop a promotion that turned out to be answered case by case",
    )
    p.add_argument("--alias", action="append", default=[], help="alternative wording (repeatable)")
    p.add_argument("--label", help="this form's exact field label (added as an alias)")
    p.add_argument("--field-type", dest="field_type", choices=FIELD_TYPES)
    p.add_argument("--option", action="append", default=[], help="option seen on this form (repeatable)")
    p.add_argument("--required", action="store_true", help="the form marked it required")
    p.add_argument("--answer-given", dest="answer_given", help="what was actually entered this time")
    p.add_argument("--job-id", dest="job_id", type=int)
    p.add_argument("--application-id", dest="application_id", type=int)
    p.add_argument("--asked-at", dest="asked_at", help="ISO-8601 UTC (default: now)")
    p.set_defaults(func=record)

    p = sub.add_parser("lookup", help="find canonical answers for a form label")
    p.add_argument("query", help="the field label or its key words")
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--evidence", action="store_true", help="include every instance seen")
    p.set_defaults(func=cmd_lookup)

    p = sub.add_parser("retire", help="set an answer aside, or bring it back")
    p.add_argument("--key", action="append", required=True, help="question_key (repeatable)")
    p.add_argument("--undo", action="store_true", help="reverse a retirement")
    p.set_defaults(func=cmd_retire)

    p = sub.add_parser("frequency", help="every canonical question by times asked")
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--min-count", dest="min_count", type=int, default=1)
    p.set_defaults(func=cmd_frequency)

    p = sub.add_parser("promotions", help="facts waiting to move into profile.jsonc")
    p.add_argument("--kind", choices=KINDS)
    p.set_defaults(func=cmd_promotions)

    p = sub.add_parser("digest", help="regenerate a FAQ doc from the bank")
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--out", type=Path, help="write here (default: stdout)")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("import-faq", help="one-off: load the pre-bank FAQ markdown")
    p.add_argument("--path", type=Path, help="a FAQ file (default: both standard paths)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_import_faq)

    p = sub.add_parser("selftest", help="check the derived answer state on fixed cases")
    p.set_defaults(func=lambda conn, args: cmd_selftest())

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    conn = connect()
    try:
        return args.func(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
