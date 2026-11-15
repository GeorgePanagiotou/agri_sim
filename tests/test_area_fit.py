"""Köppen–Geiger classes for textbook stations (approximate 1991–2020 normals) and the rule-fit verdicts."""
import pytest

from agrisim.features import area_fit as af

STATIONS = {   # name: (lat, monthly T °C, monthly P mm, expected)
    "Athens": (37.9, [10, 10.5, 12.5, 16, 21, 26, 28.5, 28, 24, 19, 15, 11.5],
               [55, 45, 45, 30, 20, 8, 6, 6, 15, 45, 60, 70], "Csa"),
    "Des Moines": (41.6, [-6, -3, 4, 11, 17, 22, 25, 24, 19, 12, 4, -3],
                   [25, 30, 55, 90, 115, 125, 110, 105, 80, 65, 50, 35], "Dfa"),
    "London": (51.5, [5, 5, 7, 9, 13, 16, 18, 18, 15, 12, 8, 5],
               [55, 40, 42, 44, 49, 45, 45, 50, 49, 69, 59, 55], "Cfb"),
    "Cairo": (30.0, [14, 15, 18, 21, 25, 27, 28, 28, 26, 24, 19, 15], [5, 4, 4, 1, 0, 0, 0, 0, 0, 1, 3, 5], "BWh"),
    "Buenos Aires": (-34.6, [24, 23, 21, 17, 14, 11, 10, 12, 14, 17, 20, 23],
                     [120, 120, 140, 110, 90, 60, 60, 65, 80, 120, 110, 105], "Cfa"),
    "Singapore": (1.3, [26.5, 27, 27.5, 28, 28.3, 28.3, 28, 28, 27.8, 27.6, 27, 26.5],
                  [240, 160, 180, 180, 170, 130, 150, 150, 140, 160, 260, 290], "Af"),
}


@pytest.mark.parametrize("name", STATIONS)
def test_koppen_textbook_stations(name):
    lat, t, p, expected = STATIONS[name]
    assert af.koppen(t, p, lat) == expected


def test_rule_fit_levels():
    assert af.rule_fit("Csa", 38.8, 0.8)[0] == "calibrated"
    assert af.rule_fit("BSk", 38.0, 0.7)[0] == "partly"
    assert af.rule_fit("BSk", 38.0, 0.3)[0] == "not calibrated"
    assert af.rule_fit("Dfa", 42.0, 0.3)[0] == "not calibrated"
    assert af.rule_fit("Dsa", 37.9, 0.67)[0] == "partly"            # central Anatolia: winter wheat, cold winters
    level, text = af.rule_fit("Csb", -33.9, 0.7)       # Cape Town: Mediterranean, but reversed seasons
    assert level == "not calibrated" and "Southern Hemisphere" in text


def test_gaez_sample_if_rasters_present():
    if not (af.GAEZ_DIR / af.GAEZ["wheat"]).exists():
        pytest.skip("GAEZ reference rasters not present")
    s = af.gaez_suitability(23.43232, 38.7592, (23.32, 23.50, 38.75, 38.95))   # Evia pilot
    assert s["wheat"]["pilot"] == 8070 and s["maize"]["pilot"] == 5943      # matches the recorded Evia values
    assert s["wheat"]["box_max"] >= s["wheat"]["pilot"]
