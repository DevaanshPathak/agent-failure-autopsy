"""The prepared scenarios in fixtures/sites.yaml, and the lab test pages they point at."""

import re
from urllib.parse import urlsplit

import pytest

from app.config import REPO_ROOT
from app.models import FailureClass, SiteInfo
from app.sites import load_sites
from app.verify.verifier import RE_403, RE_ACCESS_DENIED, RE_CAPTCHA, RE_LOGIN, RE_POPUP

LAB_ORIGIN = "https://agent-failure-autopsy.vercel.app"
WEB = REPO_ROOT / "apps" / "web"

# Trigger words of each class (app/verify/verifier.py). A lab page must not contain another
# class's words: the rules check captcha, then login, then blocks, then popups, so a stray match
# would show the wrong class.
TRIGGERS: dict[str, list[re.Pattern[str]]] = {
    "captcha": [RE_CAPTCHA],
    "auth_wall": [RE_LOGIN],
    "bot_block": [RE_ACCESS_DENIED, RE_403],
    "popup_overlay": [RE_POPUP],
}


def _sites() -> list[SiteInfo]:
    return load_sites(REPO_ROOT / "fixtures")


def _lab_sites() -> list[SiteInfo]:
    return [s for s in _sites() if s.kind == "lab"]


def _lab_page(path: str) -> str:
    """The text a visitor of a lab URL path gets: a public/ file, a redirect target or a route."""
    config = (WEB / "next.config.ts").read_text(encoding="utf-8")
    redirect = re.search(rf'source: "{re.escape(path)}",\s*destination: "([^"?]+)', config)
    if redirect:
        path = redirect.group(1)
    public = WEB / "public" / path.lstrip("/")
    if public.is_file():
        return public.read_text(encoding="utf-8")
    route = WEB / "app" / path.lstrip("/") / "route.ts"
    assert route.is_file(), f"no lab page, redirect or route for {path}"
    return route.read_text(encoding="utf-8")


def _visible(html: str) -> str:
    return re.sub(r"<style>.*?</style>", " ", html, flags=re.S)


def test_card_fields_are_complete():
    titled = [s for s in _sites() if s.title]
    assert {s.kind for s in titled} == {"lab", "real"}
    for site in titled:
        assert site.summary and site.cost_hint and site.expected_class, site.id
    labs = _lab_sites()
    assert all(s.title for s in labs)
    assert {s.expected_class for s in labs} == set(FailureClass)  # one lab page per class


def test_indeed_has_no_one_click_card():
    # Its terms forbid scraping: keep it out of the public one-click cards.
    assert next(s for s in _sites() if s.id == "indeed-jobs").title is None


@pytest.mark.parametrize("site", _lab_sites(), ids=lambda s: s.id)
def test_lab_site_points_at_a_page_that_triggers_only_its_class(site: SiteInfo):
    url = urlsplit(site.url)
    assert f"{url.scheme}://{url.netloc}" == LAB_ORIGIN
    assert url.path.startswith("/lab/") and "v=" in url.query
    text = _visible(_lab_page(url.path))
    own = site.expected_class.value if site.expected_class else ""
    for cls, patterns in TRIGGERS.items():
        hits = [m.group(0) for p in patterns for m in [p.search(text)] if m]
        if cls == own:
            assert hits, f"{site.id}: the page never says anything that reads as {cls}"
        else:
            assert not hits, f"{site.id}: {hits} would read as {cls}"
