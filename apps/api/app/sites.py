"""Demo sites from fixtures/sites.yaml."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.models import SiteInfo


class SitesError(ValueError):
    """fixtures/sites.yaml exists but cannot be read."""


def load_sites(fixtures_dir: Path) -> list[SiteInfo]:
    """Real sites only: template entries (id starting with TODO) are skipped."""
    path = fixtures_dir / "sites.yaml"
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sites = []
        for entry in data.get("sites") or []:
            site_id = str(entry.get("id") or "")
            if not site_id or site_id.startswith("TODO"):
                continue
            has_trace = (fixtures_dir / "traces" / f"{site_id}.jsonl").is_file()
            sites.append(SiteInfo.model_validate({**entry, "has_trace": has_trace}))
        return sites
    except (yaml.YAMLError, ValidationError, AttributeError) as e:
        raise SitesError(f"fixtures/sites.yaml is invalid: {e}") from e


def find_site(fixtures_dir: Path, site_id: str | None) -> SiteInfo | None:
    if not site_id:
        return None
    try:
        return next((s for s in load_sites(fixtures_dir) if s.id == site_id), None)
    except SitesError:
        return None
