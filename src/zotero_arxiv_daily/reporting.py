"""Write a recoverable email and a compact status, without credentials or library text."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from loguru import logger


def record_delivery(directory, html, status, papers, notices):
    data = {"updated_utc": datetime.now(timezone.utc).isoformat(), "status": status,
            "papers": len(papers), "generated": sum(p.generation_status == "generated" for p in papers),
            "abstract_fallbacks": sum(p.generation_status == "abstract_fallback" for p in papers),
            "abstract_only": sum(p.evidence_scope == "abstract_only" for p in papers), "notices": notices}
    if directory:
        try:
            root = Path(directory)
            root.mkdir(parents=True, exist_ok=True)
            (root / "daily-email.html").write_text(html, encoding="utf-8")
            (root / "status.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            logger.warning("Could not save the delivery report")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        try:
            with Path(summary).open("a", encoding="utf-8") as stream:
                stream.write(f"\n### Daily digest: {status}\n\nPapers: {data['papers']}; generated: {data['generated']}; "
                             f"abstract fallbacks: {data['abstract_fallbacks']}; abstract-only evidence: {data['abstract_only']}.\n")
                for notice in notices:
                    stream.write(f"\n- {notice}\n")
        except OSError:
            logger.warning("Could not update the Actions summary")
