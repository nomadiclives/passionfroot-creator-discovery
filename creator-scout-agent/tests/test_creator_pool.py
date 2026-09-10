"""Tests for the bring-your-own-creator-list path.

`creator_pool.py` and the upload routes shipped verified by hand and untested,
which is the worst combination: the feature works, so nothing prompts you to
check it, and a refactor can break it silently.

The sharpest tests here are the ones asserting what must NEVER happen — a bad
upload quietly falling back to the bundled pool. That failure mode is dangerous
precisely because it looks like success: the screen renders a full, plausible
shortlist describing creators the operator never submitted.
"""

import io
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as flask_app
import config
import creator_pool
import scorer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def isolated_upload_dir(tmp_path, monkeypatch):
    """Park uploads under tmp_path so tests never touch data/uploads/."""
    target = tmp_path / "uploads"
    monkeypatch.setattr(config, "UPLOAD_DIR", str(target))
    return target


@pytest.fixture()
def client():
    flask_app.app.config.update(TESTING=True)
    return flask_app.app.test_client()


CSV_POOL = (
    "name,platform,followers,resonance_rate,audience_match_score,"
    "content_match_score,geo_match_score,commercial_maturity_score,"
    "readiness,readiness_category\n"
    "Ada Vance,TikTok,120000,9.1,4,4,5,4,adopted,Fintech apps\n"
    "Bo Lindqvist,Instagram,64000,7.2,3,4,4,3,exposed,Fintech apps\n"
    "Cy Okafor,YouTube,210000,11.4,5,4,4,5,unexposed,Fintech apps\n"
)

FINTECH_FORM = {
    "brand_name": "Ledgerly",
    "category": "Fintech apps",
    "campaign_goal": "awareness",
    "platforms": ["tiktok", "instagram", "youtube"],
    "cpm": "50",
    "follower_band": "all",
    "shortlist_size": "18",
}


def upload(body: str | bytes, filename: str = "creators.csv") -> dict:
    raw = body.encode("utf-8") if isinstance(body, str) else body
    return {"creator_file": (io.BytesIO(raw), filename)}


# ---------------------------------------------------------------------------
# parse()
# ---------------------------------------------------------------------------
def test_parse_reads_a_csv_into_creator_rows():
    rows = creator_pool.parse(CSV_POOL.encode("utf-8"), "creators.csv")
    assert [r["name"] for r in rows] == ["Ada Vance", "Bo Lindqvist", "Cy Okafor"]
    assert rows[0]["followers"] == 120000
    assert rows[0]["readiness"] == "adopted"


def test_parse_reads_a_bare_json_list():
    body = json.dumps(
        [{"name": "Ada Vance", "platform": "TikTok", "followers": 120000,
          "resonance_rate": 9.1}]
    )
    rows = creator_pool.parse(body.encode("utf-8"), "creators.json")
    assert len(rows) == 1 and rows[0]["name"] == "Ada Vance"


def test_parse_reads_the_wrapped_json_shape_the_bundled_file_uses():
    """data/creators.json is {"creators": [...]}, so an export of it must load."""
    body = json.dumps({"creators": [
        {"name": "Ada Vance", "platform": "TikTok", "followers": 120000,
         "resonance_rate": 9.1}
    ]})
    rows = creator_pool.parse(body.encode("utf-8"), "creators.json")
    assert [r["name"] for r in rows] == ["Ada Vance"]


def test_parse_survives_the_bom_excel_writes():
    rows = creator_pool.parse(b"\xef\xbb\xbf" + CSV_POOL.encode("utf-8"), "x.csv")
    assert rows[0]["name"] == "Ada Vance", "a BOM must not corrupt the first header"


def test_parse_normalises_rows_the_way_the_engine_expects():
    """parse() must hand back engine-shaped rows, not raw CSV strings."""
    rows = creator_pool.parse(CSV_POOL.encode("utf-8"))
    assert rows[0]["platforms"] == ["tiktok"]
    assert isinstance(rows[0]["followers"], float)


def test_parse_drops_nameless_rows_such_as_trailing_blank_lines():
    body = CSV_POOL + ",,,,,,,,,\n"
    rows = creator_pool.parse(body.encode("utf-8"))
    assert len(rows) == 3


@pytest.mark.parametrize(
    "body,filename,expected",
    [
        (b"", "empty.csv", "empty"),
        (b"   \n  ", "blank.csv", "empty"),
        (b"name,platform\n,\n", "nameless.csv", "no creators found"),
        (b"[{'name': broken", "broken.json", "invalid JSON"),
        (b"\xff\xfe\x00bad", "binary.xlsx", "not UTF-8"),
    ],
)
def test_parse_refuses_unreadable_files_with_an_actionable_message(
    body, filename, expected
):
    with pytest.raises(creator_pool.PoolError) as exc:
        creator_pool.parse(body, filename)
    assert expected.lower() in str(exc.value).lower()


def test_parse_refuses_a_file_over_the_size_cap(monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_MAX_BYTES", 64)
    with pytest.raises(creator_pool.PoolError) as exc:
        creator_pool.parse(CSV_POOL.encode("utf-8"), "big.csv")
    assert "larger than" in str(exc.value)


def test_the_size_cap_is_checked_before_the_body_is_decoded(monkeypatch):
    """A huge file must be rejected on length, not after building a str of it."""
    monkeypatch.setattr(config, "UPLOAD_MAX_BYTES", 10)
    with pytest.raises(creator_pool.PoolError) as exc:
        creator_pool.parse(b"\xff" * 5000, "big.bin")
    assert "larger than" in str(exc.value), "size must beat the UTF-8 check"


# ---------------------------------------------------------------------------
# save() / load() — the token round trip that keeps Export CSV honest
# ---------------------------------------------------------------------------
def test_a_saved_pool_round_trips_through_its_token():
    rows = creator_pool.parse(CSV_POOL.encode("utf-8"))
    token = creator_pool.save(rows, "creators.csv")
    loaded, filename = creator_pool.load(token)
    assert filename == "creators.csv"
    assert [r["name"] for r in loaded] == [r["name"] for r in rows]


def test_each_save_gets_its_own_token():
    rows = creator_pool.parse(CSV_POOL.encode("utf-8"))
    assert creator_pool.save(rows) != creator_pool.save(rows)


def test_an_unknown_token_is_refused_rather_than_serving_another_pool():
    with pytest.raises(creator_pool.PoolError) as exc:
        creator_pool.load("0" * 32)
    assert "no longer available" in str(exc.value)


@pytest.mark.parametrize(
    "token", ["", "nope", "../../etc/passwd", "a" * 31, "A" * 32, "../" + "a" * 29]
)
def test_a_malformed_token_never_reaches_the_filesystem(token):
    """The token is used to build a path, so it must be validated as a token."""
    with pytest.raises(creator_pool.PoolError) as exc:
        creator_pool.load(token)
    assert "bad pool reference" in str(exc.value)


def test_a_traversal_token_cannot_read_a_file_outside_the_upload_dir(tmp_path):
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"creators": [{"name": "leaked"}]}))
    with pytest.raises(creator_pool.PoolError):
        creator_pool.load("../secret")


# ---------------------------------------------------------------------------
# Retention sweep
# ---------------------------------------------------------------------------
def test_the_sweep_drops_pools_past_the_retention_window(isolated_upload_dir):
    rows = creator_pool.parse(CSV_POOL.encode("utf-8"))
    stale = creator_pool.save(rows)
    old = time.time() - (config.UPLOAD_RETENTION_HOURS + 1) * 3600
    path = os.path.join(str(isolated_upload_dir), f"{stale}.json")
    os.utime(path, (old, old))

    creator_pool.save(rows)  # any save sweeps first

    assert not os.path.exists(path)
    with pytest.raises(creator_pool.PoolError) as exc:
        creator_pool.load(stale)
    assert "upload it again" in str(exc.value)


def test_the_sweep_leaves_pools_inside_the_window_alone():
    rows = creator_pool.parse(CSV_POOL.encode("utf-8"))
    fresh = creator_pool.save(rows)
    creator_pool.save(rows)
    assert creator_pool.load(fresh)[0], "a fresh pool must survive a later upload"


# ---------------------------------------------------------------------------
# resolve() — precedence
# ---------------------------------------------------------------------------
class _Upload:
    def __init__(self, body: str, filename: str = "creators.csv"):
        self.filename = filename
        self._body = body.encode("utf-8")

    def read(self):
        return self._body


def test_resolve_falls_back_to_the_bundled_pool_when_nothing_is_supplied():
    source, provenance = creator_pool.resolve({}, None)
    assert source == config.CREATOR_DATA
    assert provenance["kind"] == "bundled"
    assert provenance["token"] == creator_pool.BUNDLED


def test_resolve_prefers_an_uploaded_file_over_everything():
    rows = creator_pool.parse(CSV_POOL.encode("utf-8"))
    token = creator_pool.save(rows, "earlier.csv")
    source, provenance = creator_pool.resolve(
        {creator_pool.TOKEN_FIELD: token}, {"creator_file": _Upload(CSV_POOL, "new.csv")}
    )
    assert provenance["filename"] == "new.csv"
    assert provenance["token"] != token, "a new upload must park under a new token"
    assert len(source) == 3


def test_resolve_uses_the_token_when_no_new_file_is_attached():
    rows = creator_pool.parse(CSV_POOL.encode("utf-8"))
    token = creator_pool.save(rows, "creators.csv")
    source, provenance = creator_pool.resolve({creator_pool.TOKEN_FIELD: token}, {})
    assert provenance == {
        "kind": "upload", "filename": "creators.csv", "count": 3, "token": token
    }
    assert [r["name"] for r in source] == ["Ada Vance", "Bo Lindqvist", "Cy Okafor"]


def test_an_empty_file_field_is_not_an_upload():
    """Browsers submit the field with an empty filename when nothing was picked."""
    source, provenance = creator_pool.resolve(
        {}, {"creator_file": _Upload("", filename="")}
    )
    assert provenance["kind"] == "bundled"
    assert source == config.CREATOR_DATA


def test_the_bundled_sentinel_token_means_the_bundled_pool():
    _, provenance = creator_pool.resolve(
        {creator_pool.TOKEN_FIELD: creator_pool.BUNDLED}, {}
    )
    assert provenance["kind"] == "bundled"


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------
def test_an_uploaded_list_scores_those_creators_and_only_those(client):
    body = client.post(
        "/shortlist",
        data={**FINTECH_FORM, **upload(CSV_POOL)},
        content_type="multipart/form-data",
    ).get_data(as_text=True)

    for name in ("Ada Vance", "Bo Lindqvist", "Cy Okafor"):
        assert name in body
    assert "Joshua La Rosa" not in body, "the bundled pool must not leak in"
    assert "Riley Brown" not in body


def test_screen_two_names_the_uploaded_file_so_the_pool_is_never_ambiguous(client):
    body = client.post(
        "/shortlist",
        data={**FINTECH_FORM, **upload(CSV_POOL, "fintech-sourcing.csv")},
        content_type="multipart/form-data",
    ).get_data(as_text=True)
    assert "fintech-sourcing.csv" in body


def test_a_brief_with_no_upload_still_scores_the_bundled_pool(client):
    body = client.post("/shortlist", data=FINTECH_FORM).get_data(as_text=True)
    assert "Ada Vance" not in body


def test_a_bad_upload_returns_400_and_never_falls_back_to_the_bundled_pool(client):
    response = client.post(
        "/shortlist",
        data={**FINTECH_FORM, **upload("not,a,creator,list\n", "junk.csv")},
        content_type="multipart/form-data",
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "no creators found" in body
    assert "Joshua La Rosa" not in body, "a failed upload must not score the bundle"
    assert 'name="brand_name"' in body, "the operator lands back on the brief form"


def test_a_bad_upload_keeps_the_brief_the_operator_typed(client):
    body = client.post(
        "/shortlist",
        data={**FINTECH_FORM, "brand_name": "Ledgerly", **upload("", "empty.csv")},
        content_type="multipart/form-data",
    ).get_data(as_text=True)
    assert "Ledgerly" in body, "a parse error must not discard the typed brief"


def test_the_export_re_runs_against_the_uploaded_rows_not_the_bundle(client):
    screen = client.post(
        "/shortlist",
        data={**FINTECH_FORM, **upload(CSV_POOL)},
        content_type="multipart/form-data",
    ).get_data(as_text=True)
    token = _token_from(screen)

    export = client.post(
        "/export.csv", data={**FINTECH_FORM, creator_pool.TOKEN_FIELD: token}
    )
    text = export.get_data(as_text=True)
    assert export.status_code == 200
    assert "Ada Vance" in text and "Joshua La Rosa" not in text


def test_the_export_row_count_matches_the_screen_for_an_uploaded_pool(client):
    screen = client.post(
        "/shortlist",
        data={**FINTECH_FORM, **upload(CSV_POOL)},
        content_type="multipart/form-data",
    ).get_data(as_text=True)
    token = _token_from(screen)

    text = client.post(
        "/export.csv", data={**FINTECH_FORM, creator_pool.TOKEN_FIELD: token}
    ).get_data(as_text=True)
    rows = [line for line in text.strip().splitlines() if line]
    assert len(rows) == 4, "1 header + the 3 uploaded creators"


def test_an_expired_token_fails_the_export_loudly_rather_than_exporting_the_bundle(
    client,
):
    response = client.post(
        "/export.csv", data={**FINTECH_FORM, creator_pool.TOKEN_FIELD: "0" * 32}
    )
    assert response.status_code == 400
    body = response.get_data(as_text=True)
    assert "no longer available" in body
    assert "Joshua La Rosa" not in body


def test_the_template_csv_carries_every_column_the_engine_reads(client):
    response = client.get("/creator-template.csv")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    header = response.get_data(as_text=True).splitlines()[0].split(",")

    for field in scorer.REQUIRED_FIELDS:
        assert field in header, f"{field} is required but missing from the template"
    for field in scorer.JUDGED_FIELDS:
        assert field in header, f"{field} is judged but missing from the template"
    assert "readiness" in header and "readiness_category" in header


def test_the_template_csv_actually_parses_as_a_pool():
    """The template is only useful if a filled-in copy of it loads."""
    flask_app.app.config.update(TESTING=True)
    body = flask_app.app.test_client().get("/creator-template.csv").get_data()
    rows = creator_pool.parse(body, "creator-template.csv")
    assert rows[0]["name"] == "Example Creator"
    assert rows[0]["platforms"] == ["tiktok", "instagram"]


def test_screen_one_offers_the_upload_field_and_says_it_is_optional(client):
    body = client.get("/").get_data(as_text=True)
    assert 'name="creator_file"' in body
    assert "multipart/form-data" in body


def _token_from(html: str) -> str:
    """Pull the pool token Screen 2 carries for the export re-run."""
    import re

    match = re.search(
        rf'name="{creator_pool.TOKEN_FIELD}"[^>]*value="([0-9a-f]{{32}})"', html
    )
    assert match, "Screen 2 must carry the pool token for Export CSV"
    return match.group(1)
