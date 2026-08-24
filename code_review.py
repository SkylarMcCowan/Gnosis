"""Diff review domain logic: context collection from a folder/zip, a
two-pass (+ tie-break) LLM review against a fixed checklist, and persistence
of past reviews to disk."""

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime

import agent_dialogue
import sys_msgs
import webagent

CHECKLIST = [
    ("correctness", "Correctness"),
    ("style", "Style & Consistency"),
    ("tests", "Test Coverage"),
    ("security", "Security"),
    ("performance", "Performance"),
]

_ALLOWED_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".txt", ".json", ".yml",
    ".yaml", ".ini", ".cfg", ".toml", ".go", ".rs", ".java", ".c", ".cpp",
    ".h", ".hpp", ".rb", ".sh",
}
_MAX_TOTAL_BYTES = 400_000
_MAX_FILE_BYTES = 100_000
_MAX_FILES = 40

# Whole-folder review (no diff) walks the same tree but reviews the files
# themselves rather than using them as diff context, so it needs its own,
# much higher file cap plus batching - a real repo won't fit in one prompt.
_MAX_FOLDER_REVIEW_FILES = 300
_FOLDER_REVIEW_BATCH_SIZE = 6


def _walk_and_read(root, files, total_bytes):
    """Append (relpath, content) tuples from `root` into `files`, respecting
    the shared size budget. Returns the updated total_bytes and a skip count."""
    skipped = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for skip_dir in (".git", "venv", "__pycache__", "node_modules"):
            if skip_dir in dirnames:
                dirnames.remove(skip_dir)

        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _ALLOWED_EXTS:
                continue

            path = os.path.join(dirpath, filename)
            try:
                size = os.path.getsize(path)
                if size > _MAX_FILE_BYTES or total_bytes + size > _MAX_TOTAL_BYTES:
                    skipped += 1
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                relpath = os.path.relpath(path, root)
                files.append((relpath, content))
                total_bytes += len(content)
                if len(files) >= _MAX_FILES or total_bytes >= _MAX_TOTAL_BYTES:
                    return total_bytes, skipped
            except OSError:
                skipped += 1
                continue

        if len(files) >= _MAX_FILES or total_bytes >= _MAX_TOTAL_BYTES:
            break
    return total_bytes, skipped


def collect_context_files(folder=None, zip_path=None):
    """Scan an optional folder and/or zip for reference source files.

    Returns (context_text, manifest) where manifest is a list of relative
    paths actually included (for logging), or (None, []) if nothing usable
    was found.
    """
    files = []
    total_bytes = 0
    skipped = 0

    if folder:
        if not os.path.isdir(folder):
            raise ValueError(f"Folder does not exist: {folder}")
        total_bytes, s = _walk_and_read(folder, files, total_bytes)
        skipped += s

    if zip_path:
        if not os.path.isfile(zip_path):
            raise ValueError(f"Zip file does not exist: {zip_path}")
        extract_dir = tempfile.mkdtemp(prefix="codereview_")
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_dir)
            total_bytes, s = _walk_and_read(extract_dir, files, total_bytes)
            skipped += s
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    if not files:
        return None, []

    formatted = [
        "Reference files from the codebase, for context only (do not review these directly, "
        "only the diff below):",
        f"Total files included: {len(files)}",
        f"Total bytes included: {total_bytes}",
        "",
    ]
    for relpath, content in files:
        formatted.append(f"### {relpath}\n```\n{content}\n```\n")
    if skipped:
        formatted.append(f"NOTE: {skipped} additional files were skipped due to size limits.")

    return "\n".join(formatted), [relpath for relpath, _ in files]


def _enumerate_files(root, max_files):
    """Recursively list every reviewable file under `root` (no byte budget
    across files, unlike _walk_and_read - each file just has to fit
    individually). Returns (list of (relpath, content), skipped_count)."""
    entries = []
    skipped = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for skip_dir in (".git", "venv", "__pycache__", "node_modules"):
            if skip_dir in dirnames:
                dirnames.remove(skip_dir)

        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _ALLOWED_EXTS:
                continue

            path = os.path.join(dirpath, filename)
            try:
                if os.path.getsize(path) > _MAX_FILE_BYTES:
                    skipped += 1
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                entries.append((os.path.relpath(path, root), content))
                if len(entries) >= max_files:
                    return entries, skipped
            except OSError:
                skipped += 1
                continue
    return entries, skipped


def _format_file_batch(batch):
    return "\n".join(f"### {relpath}\n```\n{content}\n```\n" for relpath, content in batch)


def _chat_fn(messages):
    response = webagent.ollama.chat(model=webagent.MODELS["coding"], messages=messages)
    return response.get("message", {}).get("content", "")


def _empty_result(note):
    return {
        "items": {key: {"status": "concern", "comment": note} for key, _ in CHECKLIST},
        "verdict": "NEEDS_INFO",
        "summary": note,
    }


def run_review_pass(review_text, context_text, pass_label, mode="diff"):
    if mode == "files":
        prompt_parts = [f"## Files to review (review these directly, they are the review subject)\n{review_text}"]
    else:
        prompt_parts = [f"## Diff to review\n```diff\n{review_text}\n```"]
    if context_text:
        prompt_parts.append(f"\n## Reference context\n{context_text}")
    user_prompt = "\n".join(prompt_parts)

    result = agent_dialogue.call_agent_json(
        _chat_fn,
        sys_msgs.diff_review_msg,
        extra_messages=[{"role": "user", "content": user_prompt}],
    )
    if not isinstance(result, dict) or "verdict" not in result:
        return {**_empty_result(f"Pass '{pass_label}' returned an unparseable response."), "pass_label": pass_label}
    result["pass_label"] = pass_label
    return result


_CAUTION_ORDER = {"REJECT": 0, "NEEDS_INFO": 1, "APPROVE": 2}


def _majority_verdict(verdicts):
    counts = {}
    for v in verdicts:
        counts[v] = counts.get(v, 0) + 1
    best = max(counts.items(), key=lambda kv: kv[1])
    if best[1] > 1:
        return best[0]
    # Genuine 3-way split: fall back to the most cautious verdict present.
    return min(verdicts, key=lambda v: _CAUTION_ORDER.get(v, 1))


def review_diff(diff_text, folder=None, zip_path=None):
    diff_text = (diff_text or "").strip()
    if not diff_text:
        raise ValueError("No diff text provided.")

    context_text, manifest = collect_context_files(folder=folder, zip_path=zip_path)

    pass_1 = run_review_pass(diff_text, context_text, "pass_1")
    pass_2 = run_review_pass(diff_text, context_text, "pass_2")

    passes = [pass_1, pass_2]
    tie_break = None
    if pass_1["verdict"] != pass_2["verdict"]:
        tie_break = run_review_pass(diff_text, context_text, "tie_break")
        passes.append(tie_break)

    final_verdict = _majority_verdict([p["verdict"] for p in passes])
    final_pass = next((p for p in passes if p["verdict"] == final_verdict), passes[-1])

    record = {
        "timestamp": None,  # filled in by save_review
        "mode": "diff",
        "diff_text": diff_text,
        "context_manifest": manifest,
        "folder": folder,
        "zip_path": zip_path,
        "passes": passes,
        "verdict": final_verdict,
        "items": final_pass["items"],
        "summary": final_pass["summary"],
        "waived": [],
    }
    return record


_ITEM_SEVERITY = {"pass": 0, "waived": 0, "concern": 1, "fail": 2}


def _aggregate_items(items_list):
    aggregated = {}
    for key, _ in CHECKLIST:
        worst_status = "pass"
        comments = []
        for items in items_list:
            item = items.get(key, {})
            status = item.get("status", "pass")
            if _ITEM_SEVERITY.get(status, 0) > _ITEM_SEVERITY.get(worst_status, 0):
                worst_status = status
            if status not in ("pass", "waived") and item.get("comment"):
                comments.append(item["comment"])
        aggregated[key] = {
            "status": worst_status,
            "comment": "; ".join(comments[:5]) if comments else "No issues found across reviewed files.",
        }
    return aggregated


def _aggregate_verdict(verdicts):
    if "REJECT" in verdicts:
        return "REJECT"
    if "NEEDS_INFO" in verdicts:
        return "NEEDS_INFO"
    return "APPROVE"


def review_folder(folder=None, zip_path=None, on_progress=None):
    """Review every reviewable file under a folder and/or zip directly - no
    diff needed. Files are batched (small local models can't take a whole
    repo in one prompt); each batch runs the same two-pass (+ tie-break)
    checklist review as review_diff, and results are aggregated to an
    overall verdict.

    on_progress, if given, is called as on_progress(batch_index, batch_count,
    file_list) before each batch runs.
    """
    if not folder and not zip_path:
        raise ValueError("Provide a folder or zip to review.")

    extract_dir = None
    root = folder
    if zip_path:
        if not os.path.isfile(zip_path):
            raise ValueError(f"Zip file does not exist: {zip_path}")
        extract_dir = tempfile.mkdtemp(prefix="codereview_")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        root = extract_dir
    elif not os.path.isdir(root):
        raise ValueError(f"Folder does not exist: {root}")

    try:
        entries, skipped = _enumerate_files(root, max_files=_MAX_FOLDER_REVIEW_FILES)
    finally:
        if extract_dir:
            shutil.rmtree(extract_dir, ignore_errors=True)

    if not entries:
        raise ValueError("No reviewable files found in that folder/zip.")

    batches = [
        entries[i:i + _FOLDER_REVIEW_BATCH_SIZE]
        for i in range(0, len(entries), _FOLDER_REVIEW_BATCH_SIZE)
    ]

    batch_records = []
    for i, batch in enumerate(batches, start=1):
        file_names = [relpath for relpath, _ in batch]
        if on_progress:
            on_progress(i, len(batches), file_names)

        review_text = _format_file_batch(batch)
        pass_1 = run_review_pass(review_text, None, f"batch_{i}_pass_1", mode="files")
        pass_2 = run_review_pass(review_text, None, f"batch_{i}_pass_2", mode="files")
        passes = [pass_1, pass_2]
        if pass_1["verdict"] != pass_2["verdict"]:
            passes.append(run_review_pass(review_text, None, f"batch_{i}_tie_break", mode="files"))

        verdict = _majority_verdict([p["verdict"] for p in passes])
        final_pass = next((p for p in passes if p["verdict"] == verdict), passes[-1])
        batch_records.append({
            "files": file_names,
            "passes": passes,
            "verdict": verdict,
            "items": final_pass["items"],
            "summary": final_pass["summary"],
        })

    overall_items = _aggregate_items([b["items"] for b in batch_records])
    overall_verdict = _aggregate_verdict([b["verdict"] for b in batch_records])

    record = {
        "timestamp": None,
        "mode": "folder",
        "diff_text": "",
        "folder": folder,
        "zip_path": zip_path,
        "file_count": len(entries),
        "skipped_count": skipped,
        "batches": batch_records,
        "passes": [p for b in batch_records for p in b["passes"]],
        "verdict": overall_verdict,
        "items": overall_items,
        "summary": f"Reviewed {len(entries)} file(s) across {len(batches)} batch(es)"
                   + (f", {skipped} file(s) skipped (too large)." if skipped else "."),
        "waived": [],
    }
    return record


def resolve_open_item(record, item_key, waived=False, answer_text=None):
    """Mark an open checklist item as user-waived, or feed a free-text answer
    that triggers one re-review pass incorporating it."""
    if waived:
        if item_key not in record["waived"]:
            record["waived"].append(item_key)
        item = record["items"].get(item_key)
        if item and item["status"] != "pass":
            item["status"] = "waived"
        open_items = [
            key for key, _ in CHECKLIST
            if record["items"].get(key, {}).get("status") not in ("pass", "waived")
        ]
        if not open_items:
            record["verdict"] = "APPROVE"
        return record

    if answer_text:
        if record.get("mode") == "folder":
            # Re-running the whole batched folder review per follow-up note
            # would be expensive (many model calls per repo); just attach the
            # note to the item so it's visible, and let the user Waive it
            # once satisfied.
            item = record["items"].setdefault(item_key, {"status": "concern", "comment": ""})
            note = f"User note: {answer_text}"
            item["comment"] = f"{item['comment']} | {note}".strip(" |") if item.get("comment") else note
            return record

        context_text, _ = collect_context_files(folder=record.get("folder"), zip_path=record.get("zip_path"))
        followup_prompt = (
            f"Additional information from the user regarding the '{item_key}' concern:\n{answer_text}\n\n"
            "Re-evaluate the full checklist with this new information."
        )
        result = run_review_pass(record["diff_text"] + f"\n\n[User follow-up]\n{followup_prompt}", context_text, "follow_up")
        record["passes"].append(result)
        record["items"] = result["items"]
        record["verdict"] = result["verdict"]
        record["summary"] = result["summary"]
    return record


def _reviews_dir():
    path = os.path.join(os.path.dirname(__file__), "code_reviews")
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    return path


def save_review(record):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    record["timestamp"] = timestamp
    path = os.path.join(_reviews_dir(), f"review_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return path


def list_reviews():
    d = _reviews_dir()
    return sorted([f for f in os.listdir(d) if f.endswith(".json")], reverse=True)


def load_review(filename):
    path = os.path.join(_reviews_dir(), filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
