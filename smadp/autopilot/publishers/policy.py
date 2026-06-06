"""PolicyPublisher: route verdicts to verdicts/ or pending/ by evidence tier."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class PolicyPublisher:
    def __init__(self, *, catalog_root: Path, auto_publish: dict[str, bool]) -> None:
        self.catalog_root = catalog_root
        self.auto_publish = auto_publish

    def commit(self, verdict: dict) -> Path:
        tier = verdict.get("evidence_level", "docs-only")
        publish = self.auto_publish.get(tier, False)
        target_dir = self.catalog_root / ("verdicts" if publish else "pending")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{verdict['verdict_id']}.json"

        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", dir=target_dir)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(verdict, f, indent=2)
                f.write("\n")
            os.replace(tmp, target)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        return target
