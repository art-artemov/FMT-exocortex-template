"""
Tests for horizons.py + plan_horizon().
Run: cd generator && pytest

guide-kit fork: ported from the original platform test suite,
the only existing coverage for the core selection logic. Comments translated
to English per repo convention; assertions and fixtures unchanged.
"""

import pytest
from planner import plan_horizon
from horizons import (
    RCSProfile,
    HorizonContext,
    OrchestratorTrigger,
    MonthThemes,
    PlanDay,
    DZItem,
    QualificationDegree,
    TACTICAL_TRIGGERS,
    STRATEGIC_TRIGGERS,
)


# ─────────────────────────────────────────────────────────────────────────────
# RCSProfile
# ─────────────────────────────────────────────────────────────────────────────

class TestRCSProfileFromDict:
    def test_compact_format(self):
        """Compact format used by render-pilot-guides.py."""
        d = {"stage": 2, "W": 2, "M1": 3, "M2": 1, "M4": 2, "bottleneck": "M2", "confidence": 0.7}
        rcs = RCSProfile.from_dict(d)
        assert rcs.W == 2
        assert rcs.M1 == 3
        assert rcs.M2 == 1
        assert rcs.M4 == 2
        assert rcs.M3 == 1       # default
        assert rcs.IT == 1       # default
        assert rcs.A == 1        # default
        assert rcs.bottleneck == "M2"
        assert rcs.stage_derived == 2
        assert abs(rcs.confidence - 0.7) < 1e-9

    def test_full_format_wp151(self):
        """Full format."""
        d = {
            "worldview": 3,
            "mastery": {"m1_focus": 4, "m2_iwe": 2, "m3_domain": 3, "m4_systems": 2},
            "it_level": 3,
            "agency": 2,
            "bottleneck": "m2_iwe",
            "stage_derived": 3,
            "source": "diagnostic_session",
            "confidence": 0.85,
        }
        rcs = RCSProfile.from_dict(d)
        assert rcs.W == 3
        assert rcs.M1 == 4
        assert rcs.M2 == 2
        assert rcs.M3 == 3
        assert rcs.M4 == 2
        assert rcs.IT == 3
        assert rcs.A == 2
        assert rcs.bottleneck == "m2_iwe"
        assert rcs.stage_derived == 3
        assert rcs.source == "diagnostic_session"

    def test_fallback_on_empty(self):
        """Empty dict → everything defaults to 1, no crash."""
        rcs = RCSProfile.from_dict({})
        assert rcs.stage_derived == 1
        assert all(getattr(rcs, s) == 1 for s in ("W", "M1", "M2", "M3", "M4", "IT", "A"))

    def test_weakest_slots(self):
        rcs = RCSProfile(W=1, M1=3, M2=2, M3=4, M4=5, IT=1, A=2)
        weakest = rcs.weakest_slots(2)
        assert set(weakest) == {"W", "IT"}

    def test_to_dict_roundtrip(self):
        rcs = RCSProfile(W=3, M1=4, M2=2, M3=2, M4=3, IT=3, A=2, bottleneck="M2", stage_derived=3)
        d = rcs.to_dict()
        rcs2 = RCSProfile.from_dict(d)
        assert rcs2.W == 3
        assert rcs2.M2 == 2
        assert rcs2.bottleneck == "M2"


# ─────────────────────────────────────────────────────────────────────────────
# OrchestratorTrigger
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestratorTrigger:
    def test_default_is_routine(self):
        t = OrchestratorTrigger()
        assert t.kind == "routine"
        assert t.is_tactical()
        assert not t.is_strategic()

    def test_slot_miss_tactical(self):
        t = OrchestratorTrigger(kind="slot_miss", detail="3 days without a session")
        assert t.is_tactical()
        assert not t.is_strategic()

    def test_blocker_strategic(self):
        t = OrchestratorTrigger(kind="blocker", detail="no artifacts for 2 weeks", severity=2)
        assert t.is_strategic()
        assert not t.is_tactical()

    def test_all_triggers_classified(self):
        all_kinds = {"routine", "slot_miss", "focus_shift", "metric_jump", "calendar_event", "blocker", "hypothesis_fail"}
        classified = TACTICAL_TRIGGERS | STRATEGIC_TRIGGERS
        assert all_kinds == classified


# ─────────────────────────────────────────────────────────────────────────────
# HorizonContext
# ─────────────────────────────────────────────────────────────────────────────

class TestHorizonContext:
    def test_from_render_context_basic(self):
        rcs_dict = {"W": 2, "M1": 2, "M2": 1, "M4": 2, "stage": 2, "bottleneck": "M2"}
        ctx = HorizonContext.from_render_context(rcs_dict, events_summary="X: 3", monthly_theme_md="Theme: ORZ")
        assert ctx.rcs.M2 == 1
        assert ctx.rcs.stage_derived == 2
        assert ctx.summary_events == "X: 3"
        assert ctx.month.label == "Theme: ORZ"
        # Horizons empty (before the Orchestrator)
        assert ctx.quarter.theme == ""
        assert ctx.week.label == ""

    def test_effective_bottleneck_uses_rcs(self):
        rcs = RCSProfile(M2=1, bottleneck="M2")
        ctx = HorizonContext(rcs=rcs)
        assert ctx.effective_bottleneck() == "M2"

    def test_effective_bottleneck_uses_quarter_if_set(self):
        from horizons import QuarterFocus
        rcs = RCSProfile(bottleneck="M2")
        ctx = HorizonContext(rcs=rcs, quarter=QuarterFocus(bottleneck_slot="M4"))
        assert ctx.effective_bottleneck() == "M4"

    def test_energy_defaults_to_3(self):
        ctx = HorizonContext(rcs=RCSProfile())
        assert ctx.energy() == 3

    def test_energy_override(self):
        from horizons import DayEvents
        ctx = HorizonContext(rcs=RCSProfile(), day=DayEvents(energy_override=2))
        assert ctx.energy() == 2

    def test_energy_override_zero_not_replaced_by_default(self):
        """energy_override=0 is a genuinely very low energy value, not replaced by the default."""
        from horizons import DayEvents
        ctx = HorizonContext(rcs=RCSProfile(), day=DayEvents(energy_override=0))
        assert ctx.energy() == 0

    def test_monthly_theme_truncated(self):
        long_theme = "A" * 1000
        ctx = HorizonContext.from_render_context({}, monthly_theme_md=long_theme)
        assert len(ctx.month.label) == 500

    def test_qualification_degree_defaults_empty(self):
        """No degree source at all (offline, no council record known) → empty,
        not a guessed default level (DP.D.252 — degree is never assumed)."""
        ctx = HorizonContext(rcs=RCSProfile())
        assert ctx.qualification_degree.degree == ""

    def test_qualification_degree_from_dict_roundtrip(self):
        d = QualificationDegree.from_dict(
            {"degree": "DEG.Worker", "source": "platform", "certified_at": "2026-01-15"}
        )
        assert d.degree == "DEG.Worker"
        assert d.to_dict() == {"degree": "DEG.Worker", "source": "platform", "certified_at": "2026-01-15"}


# ─────────────────────────────────────────────────────────────────────────────
# PlanDay
# ─────────────────────────────────────────────────────────────────────────────

class TestPlanDay:
    def _make_plan(self) -> PlanDay:
        items = [
            DZItem("CAT.001.M001", "worldview", 1, 2, tomatoes=2, label="A meme about time"),
            DZItem("CAT.003.METHOD.001", "mastery", 2, 1, tomatoes=1, label="Time investment"),
        ]
        return PlanDay(items=items, narrative="Today's focus is worldview", week_label="2026-W19")

    def test_total_tomatoes(self):
        plan = self._make_plan()
        assert plan.total_tomatoes() == 3

    def test_to_dict_structure(self):
        plan = self._make_plan()
        d = plan.to_dict()
        assert d["total_tomatoes"] == 3
        assert d["week_label"] == "2026-W19"
        assert len(d["items"]) == 2
        assert d["items"][0]["element_id"] == "CAT.001.M001"
        assert "decision_log" in d


# ─────────────────────────────────────────────────────────────────────────────
# plan_horizon()
# ─────────────────────────────────────────────────────────────────────────────

class TestPlanHorizon:
    def _make_ctx(self, bottleneck="M2", stage=2, trigger_kind="routine"):
        from horizons import OrchestratorTrigger
        rcs = RCSProfile.from_dict({"W": 2, "M1": 3, "M2": 1, "M4": 2, "stage": stage, "bottleneck": bottleneck})
        ctx = HorizonContext.from_render_context(rcs.to_dict(), events_summary="X: 3")
        ctx.trigger = OrchestratorTrigger(kind=trigger_kind, detail="test")
        return ctx

    def test_returns_mode_horizon(self):
        ctx = self._make_ctx()
        result = plan_horizon(ctx, seed=0)
        assert result["mode"] == "horizon"

    def test_has_required_keys(self):
        ctx = self._make_ctx()
        result = plan_horizon(ctx, seed=0)
        assert "plan_skeleton" in result
        assert "horizon_context" in result
        assert "context_for_llm" in result
        assert "decision_log" in result

    def test_context_for_llm_omits_degree_when_unset(self):
        """No council record known → key absent, not a guessed default (DP.D.252) —
        the LLM must not see a fabricated qualification_degree."""
        ctx = self._make_ctx()
        result = plan_horizon(ctx, seed=0)
        assert "qualification_degree" not in result["context_for_llm"]

    def test_context_for_llm_includes_degree_when_set(self):
        ctx = self._make_ctx()
        ctx.qualification_degree = QualificationDegree(degree="DEG.Worker", source="platform")
        result = plan_horizon(ctx, seed=0)
        assert result["context_for_llm"]["qualification_degree"] == "DEG.Worker"

    def test_m2_bottleneck_selects_tools_area(self):
        ctx = self._make_ctx(bottleneck="M2")
        result = plan_horizon(ctx, seed=0)
        assert result["plan_skeleton"]["area"] == 2
        assert result["plan_skeleton"]["element_type"] == "mastery"

    def test_w_bottleneck_selects_worldview(self):
        """Portable core has no bundled curriculum (GUIDE_KIT_CURRICULUM_PATH unset in
        tests, honest empty index by design — see planner._load_cat001). Patch the CAT.001
        accessor with a minimal fixture so the worldview branch has something to pick,
        matching what the platform-side curriculum would provide."""
        from unittest.mock import patch
        ctx = self._make_ctx(bottleneck="W")
        fake_cat001 = {
            "CAT.001.TEST1": {"area": 1, "entry_stage": 1, "max_depth": 3, "context": 1, "name": "test meme"},
        }
        with patch("planner._get_cat001", return_value=fake_cat001):
            result = plan_horizon(ctx, seed=0)
        assert result["plan_skeleton"]["element_type"] == "worldview"
        assert result["plan_skeleton"]["area"] == 1

    def test_slot_miss_reduces_tomatoes(self):
        ctx = self._make_ctx(trigger_kind="slot_miss")
        result = plan_horizon(ctx, seed=0)
        assert result["plan_skeleton"]["tomatoes"] == 1

    def test_routine_has_2_tomatoes(self):
        ctx = self._make_ctx(trigger_kind="routine")
        result = plan_horizon(ctx, seed=0)
        assert result["plan_skeleton"]["tomatoes"] == 2

    def test_context_for_llm_has_rcs(self):
        ctx = self._make_ctx()
        result = plan_horizon(ctx, seed=0)
        rcs_out = result["context_for_llm"]["rcs"]
        assert rcs_out["M2"] == 1
        assert rcs_out["bottleneck"] == "M2"

    def test_bottleneck_label_in_context(self):
        """SLOT_LABELS values are user-facing lesson content, deliberately kept in
        Russian (guide-kit i18n convention: functional strings != code comments)."""
        ctx = self._make_ctx(bottleneck="M2")
        result = plan_horizon(ctx, seed=0)
        assert result["context_for_llm"]["bottleneck_label"] == "IWE / ОРЗ"

    def test_month_memes_as_worldview_gaps(self):
        from horizons import MonthThemes
        ctx = self._make_ctx(bottleneck="W")
        ctx.month = MonthThemes(memes=["CAT.001.M001", "CAT.001.M002"])
        result = plan_horizon(ctx, seed=0)
        # element_id must come from month.memes (GAP takes priority)
        assert result["plan_skeleton"]["element_id"] in {"CAT.001.M001", "CAT.001.M002"}

    def test_deterministic_with_seed(self):
        ctx = self._make_ctx()
        r1 = plan_horizon(ctx, seed=99)
        r2 = plan_horizon(ctx, seed=99)
        assert r1["plan_skeleton"]["element_id"] == r2["plan_skeleton"]["element_id"]

    def test_week_focus_area_overrides_bottleneck(self):
        from horizons import WeekHypothesis
        ctx = self._make_ctx(bottleneck="M2")  # M2 → area=2
        ctx.week = WeekHypothesis(focus_area=5)  # override to organism
        result = plan_horizon(ctx, seed=0)
        assert result["plan_skeleton"]["area"] == 5

    def test_reflection_fields_in_output(self):
        """P9 fix: reflection_learned and tomorrow_intention propagate into horizon_context."""
        ctx = self._make_ctx()
        ctx.reflection_learned = ["2026-05-13 Learned about Pomodoro", "2026-05-12 Understood gap analysis"]
        ctx.tomorrow_intention = "Tomorrow I want to do the first ORZ slot"
        result = plan_horizon(ctx, seed=0)
        hc = result["horizon_context"]
        assert hc["reflection_learned"] == ctx.reflection_learned
        assert hc["tomorrow_intention"] == ctx.tomorrow_intention

    def test_mastery_gate_with_empty_history_blocks_depth(self):
        """P5 fix: with no history, _mastery_gate does not raise depth (conservative fallback)."""
        ctx = self._make_ctx(bottleneck="M2", stage=3)
        # No recent_history → mastery_gate must return depth=1 for a new element
        result = plan_horizon(ctx, seed=0)
        skeleton = result["plan_skeleton"]
        # For a new element with empty history, the gate returns 1
        assert skeleton["target_depth"] == 1
        # decision_log must contain the depth rationale
        assert "depth=1" in result["decision_log"]["depth_rationale"]

    def test_mastery_gate_allows_depth_with_mocked_history(self):
        """P5 fix: with a passed history, the gate allows raising the depth."""
        from unittest.mock import patch
        ctx = self._make_ctx(bottleneck="M2", stage=3)
        # Mock _mastery_gate to simulate a passed history
        with patch("planner._mastery_gate", return_value=(3, "mastery-gate ok: depth 2 passed → raising to 3")):
            result = plan_horizon(ctx, seed=0)
        assert result["plan_skeleton"]["target_depth"] == 3
        assert "mastery-gate ok" in result["decision_log"]["depth_rationale"]

    def test_bidirectional_fallback_worldview_to_mastery(self):
        """P6 fix: if worldview finds no element → fallback to mastery → if mastery is also empty → back to worldview."""
        from unittest.mock import patch
        ctx = self._make_ctx(bottleneck="W", stage=0)  # W → worldview
        # Mock: worldview always None, mastery also None (no elements for stage=0)
        with patch("planner._choose_element_worldview", return_value=(None, 1, "no elements")), \
             patch("planner._choose_element_mastery", return_value=(None, 1, "no elements")):
            result = plan_horizon(ctx, seed=0)
        # Must stay element_id=None but not crash
        assert result["plan_skeleton"]["element_id"] is None
        # target_depth = 1 (fallback)
        assert result["plan_skeleton"]["target_depth"] == 1

    def test_bidirectional_fallback_mastery_to_worldview(self):
        """P6 fix: if mastery finds no element → fallback to worldview → if worldview is also empty → back to mastery."""
        from unittest.mock import patch
        ctx = self._make_ctx(bottleneck="M2", stage=0)  # M2 → mastery
        with patch("planner._choose_element_mastery", return_value=(None, 1, "no elements")), \
             patch("planner._choose_element_worldview", return_value=(None, 1, "no elements")):
            result = plan_horizon(ctx, seed=0)
        assert result["plan_skeleton"]["element_id"] is None
        assert result["plan_skeleton"]["target_depth"] == 1
