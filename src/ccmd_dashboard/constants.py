"""Shared constants used across ingest, classify, and web modules."""

BANNER_TEXT = (
    "UNCLASSIFIED // PROTOTYPE — Open-source aggregation. "
    "Automated assessments are decision-support signals, not analytic product. "
    "Not for operational use."
)

# NATO / STANAG 2022 admiralty code alphabets.
SOURCE_RELIABILITY_CODES = ["A", "B", "C", "D", "E", "F"]
INFO_CREDIBILITY_CODES = ["1", "2", "3", "4", "5", "6"]

# MDM concern_score -> category thresholds. Keep in sync with scoring.py.
MDM_CATEGORY_BANDS = [
    (0, 25, "likely_reliable"),
    (26, 50, "requires_verification"),
    (51, 75, "significant_concerns"),
    (76, 100, "high_concern"),
]
INSUFFICIENT_DATA = "insufficient_data"
