"""Verified fields from synthetic provider score documents."""

import pytest

from custom_components.roomba_home.core.clean_scores import read_clean_scores
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind

FLOOR = PersistentMap(
    "floor",
    "current",
    "Example floor",
    (
        CleaningRegion("office", RegionKind.ROOM, "Office"),
        CleaningRegion("zone-a", RegionKind.ZONE, "Desk"),
    ),
)
SCORING_ROOM = {
    "region_id": "office",
    "clean_score": 0.0,
    "high_traffic_enum": "normal",
    "updated_ts": 1700000050,
    "mission_last_cleaned": {"startTime": 1700000000, "missionId": "private-earlier-mission"},
    "mission_last_unfinished": {"startTime": 0, "missionId": "private-unfinished"},
    "last_updated_by": "private-source",
    "smart_clean_prefs": {
        "operatingMode": 6,
        "suctionLevel": 1,
        "padWetness": {"padPlate": 1},
        "swScrub": 0,
        "twoPass": False,
        "carpetBoost": False,
    },
}
SCORING_FLOOR = {
    "p2map_id": "floor",
    "active_p2mapv_id": "current",
    "smart_clean_id": "private-score-id",
    "mission_last_processed": {"startTime": 1700000100, "missionId": "private-latest-mission"},
    "regions": [SCORING_ROOM],
}


def test_exact_room_scores_include_zero_provenance_and_known_preferences():
    document = {
        "clean_score_ranges": [0.7, False, float("nan"), -1, "invalid"],
        "clean_scores": [
            SCORING_FLOOR | {"p2map_id": "different"},
            SCORING_FLOOR | {"active_p2mapv_id": "old"},
            None,
            SCORING_FLOOR
            | {"regions": [None, {"region_id": []}, {"region_id": "zone-a"}, SCORING_ROOM]},
        ],
    }
    result = read_clean_scores(document, FLOOR)
    assert result["map"] == {"id": "floor", "version": "current", "name": "Example floor"}
    assert result["last_processed_mission_started_at"] == "2023-11-14T22:15:00+00:00"
    assert result["ranges"] == (0.7,)
    assert result["rooms"] == [
        {
            "id": "floor:rid:office",
            "name": "Office",
            "score": 0.0,
            "traffic": "normal",
            "score_updated_at": "2023-11-14T22:14:10+00:00",
            "last_cleaned_mission_started_at": "2023-11-14T22:13:20+00:00",
            "last_unfinished_mission_started_at": None,
            "preferences": {
                "mode": "vacuum_mop",
                "suction_level": 1,
                "wetness_level": 1,
                "smart_scrub": False,
                "two_pass": False,
                "carpet_boost": False,
            },
        }
    ]
    assert "private-" not in repr(result)


def test_missing_or_bad_optional_values_preserve_the_room():
    document = {
        "clean_score_ranges": None,
        "clean_scores": [
            SCORING_FLOOR
            | {
                "mission_last_processed": [],
                "regions": [
                    SCORING_ROOM
                    | {
                        "clean_score": True,
                        "high_traffic_enum": "future-code",
                        "mission_last_cleaned": None,
                        "updated_ts": False,
                        "smart_clean_prefs": {"operatingMode": "unknown"},
                    }
                ],
            }
        ],
    }
    result = read_clean_scores(document, FLOOR)
    assert result["ranges"] == ()
    assert result["last_processed_mission_started_at"] is None
    assert result["rooms"][0]["id"] == "floor:rid:office"
    for key in (
        "score",
        "traffic",
        "last_cleaned_mission_started_at",
        "score_updated_at",
        "preferences",
    ):
        assert result["rooms"][0][key] is None


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [SCORING_FLOOR | {"active_p2mapv_id": "previous"}],
        [SCORING_FLOOR | {"error": {"description": "private detail"}}],
    ],
)
def test_no_current_score_records_return_an_empty_result(rows):
    result = read_clean_scores({"clean_scores": rows, "clean_score_ranges": [0.7]}, FLOOR)
    assert result["rooms"] == [] and result["ranges"] == ()


@pytest.mark.parametrize(
    "document",
    [
        [],
        {},
        {"clean_scores": [SCORING_FLOOR, SCORING_FLOOR]},
        {"clean_scores": [SCORING_FLOOR | {"regions": False}]},
        {"clean_scores": [SCORING_FLOOR | {"regions": [SCORING_ROOM, SCORING_ROOM]}]},
    ],
)
def test_bad_documents_and_duplicate_readings_are_rejected(document):
    with pytest.raises(ProtocolError):
        read_clean_scores(document, FLOOR)
