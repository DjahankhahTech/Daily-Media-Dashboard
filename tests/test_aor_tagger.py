"""AOR tagger behavior tests + eval-set regression thresholds.

The eval thresholds are deliberately forgiving because the prototype runs
with either en_core_web_trf or en_core_web_sm depending on what's
installed, and the keyword lists err toward recall. Raise these numbers
after tuning in step 9.
"""

from pathlib import Path

from ccmd_dashboard.classify.aor_tagger import tag_article
from ccmd_dashboard.classify.eval_harness import evaluate, load_eval_set

EVAL_PATH = Path(__file__).parent / "aor_eval.jsonl"


def test_pla_navy_story_tags_indopacom() -> None:
    matches = tag_article(
        "PLA Navy conducts exercises in Taiwan Strait",
        "The PLA Navy Shandong carrier group transited the Taiwan Strait.",
    )
    codes = [m.ccmd_code for m in matches]
    assert "INDOPACOM" in codes


def test_red_sea_story_tags_centcom() -> None:
    matches = tag_article(
        "Houthi missile strikes commercial vessel in Red Sea",
        "CENTCOM released imagery of the strike; the Bab-el-Mandeb is under heightened risk.",
    )
    assert "CENTCOM" in [m.ccmd_code for m in matches]


def test_multi_aor_story() -> None:
    matches = tag_article(
        "Wagner successor Africa Corps expands in Mali",
        "Russia's Africa Corps (Wagner successor) is active in Mali and the broader Sahel.",
    )
    codes = {m.ccmd_code for m in matches}
    assert {"AFRICOM", "EUCOM"}.issubset(codes)


def test_unrelated_story_is_unassigned() -> None:
    matches = tag_article(
        "Premier League clubs approve spending cap",
        "Clubs voted in favor of a new squad spending cap.",
    )
    assert matches == []


def test_matched_terms_populated() -> None:
    matches = tag_article(
        "Volt Typhoon pre-positioning in U.S. critical infrastructure",
        "JFHQ-DoDIN issued a Volt Typhoon advisory.",
    )
    cyber = next(m for m in matches if m.ccmd_code == "CYBERCOM")
    assert any("volt typhoon" in t.lower() for t in cyber.matched_terms)


def test_eval_set_regression_thresholds() -> None:
    """Runs the whole hand-labeled eval set and prints the report; asserts
    forgiving thresholds so CI doesn't flake on model availability."""
    report = evaluate(load_eval_set(EVAL_PATH))
    print("\n" + report.as_table())
    assert report.n_records == 30
    assert report.macro_f1() >= 0.50, f"macro-F1 regressed: {report.macro_f1():.3f}"
    # Unassigned articles should not be over-tagged.
    assert report.unassigned_correct >= 2
