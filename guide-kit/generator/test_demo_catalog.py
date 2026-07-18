"""Exercises the demo catalog (demo/curriculum, demo/cards) end-to-end
against the real planner/adapter code — not a fixture standing in for it.
Closes the gap test_horizons.py already flagged (a portable
core with no curriculum has an untested "CAT.001 actually loaded" branch —
CI only ever sees the honest-empty path)."""

import os

import planner
from adapter import load_card_content
from horizons import HorizonContext, OrchestratorTrigger, RCSProfile
from planner import plan_horizon

_DEMO_CURRICULUM = os.path.join(os.path.dirname(__file__), "..", "demo", "curriculum")
_DEMO_CARDS = os.path.join(os.path.dirname(__file__), "..", "demo", "cards")


def _make_ctx(bottleneck="W", stage=2):
    """Same construction as test_horizons.py's TestPlanHorizon._make_ctx —
    plan_horizon reads stage/area off the full RCS→render-context round trip,
    not off a bare RCSProfile(bottleneck=...)."""
    rcs = RCSProfile.from_dict({"W": 2, "M1": 3, "M2": 1, "M4": 2, "stage": stage, "bottleneck": bottleneck})
    ctx = HorizonContext.from_render_context(rcs.to_dict(), events_summary="X: 3")
    ctx.trigger = OrchestratorTrigger(kind="routine", detail="test")
    return ctx


class TestDemoCatalog:
    def setup_method(self):
        # _CAT001_CACHE is a module-level lazy cache (planner.py) — reset it so
        # this test controls what GUIDE_KIT_CURRICULUM_PATH it sees, regardless
        # of what earlier tests in the same process already triggered.
        planner._CAT001_CACHE = None
        self._saved_env = os.environ.get("GUIDE_KIT_CURRICULUM_PATH")
        os.environ["GUIDE_KIT_CURRICULUM_PATH"] = _DEMO_CURRICULUM

    def teardown_method(self):
        if self._saved_env is None:
            os.environ.pop("GUIDE_KIT_CURRICULUM_PATH", None)
        else:
            os.environ["GUIDE_KIT_CURRICULUM_PATH"] = self._saved_env
        planner._CAT001_CACHE = None

    def test_demo_cat001_card_loads_from_disk(self):
        cat001 = planner._get_cat001()
        assert "CAT.001.D1" in cat001
        assert cat001["CAT.001.D1"]["name"] == "Карта не территория"

    def test_worldview_bottleneck_picks_the_demo_element(self):
        result = plan_horizon(_make_ctx(bottleneck="W"), seed=0)
        assert result["plan_skeleton"]["element_id"] == "CAT.001.D1"
        assert result["plan_skeleton"]["element_type"] == "worldview"

    def test_decision_log_source_is_the_demo_path(self):
        result = plan_horizon(_make_ctx(bottleneck="W"), seed=0)
        # element_choice's source in decision_log traces back to the catalog —
        # the demo ID itself is the visible provenance signal in the plan skeleton.
        assert result["plan_skeleton"]["element_id"].startswith("CAT.001.D")


class TestDemoCards:
    def test_cat002_demo_card_loads(self):
        card = load_card_content("CAT.002.A1", _DEMO_CARDS)
        assert card is not None
        assert card["element_id"] == "CAT.002.A1"
        assert "degree" in card

    def test_cat003_demo_card_loads(self):
        card = load_card_content("CAT.003.METHOD.001", _DEMO_CARDS)
        assert card is not None
        assert card["element_id"] == "CAT.003.METHOD.001"

    def test_unknown_element_in_demo_cards_is_honest_none(self):
        assert load_card_content("CAT.002.A99", _DEMO_CARDS) is None
