from __future__ import annotations

import pytest

from apl.composition import VerdictComposer
from apl.composition.strategies import (
    AllowOverridesStrategy,
    DenyOverridesStrategy,
    FirstApplicableStrategy,
    UnanimousStrategy,
    WeightedStrategy,
    get_strategy,
)
from apl.types import CompositionConfig, CompositionMode, Decision, Verdict


class TestDenyOverridesStrategy:

    def setup_method(self):
        self.strategy = DenyOverridesStrategy()

    def test_empty_verdicts_returns_allow(self):
        result = self.strategy.compose([])
        assert result.decision == Decision.ALLOW

    def test_single_allow(self):
        result = self.strategy.compose([Verdict.allow()])
        assert result.decision == Decision.ALLOW

    def test_single_deny_wins(self):
        result = self.strategy.compose([Verdict.deny("no")])
        assert result.decision == Decision.DENY

    def test_deny_overrides_allow(self):
        verdicts = [Verdict.allow(), Verdict.deny("blocked"), Verdict.allow()]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.DENY

    def test_escalate_before_modify(self):
        verdicts = [
            Verdict.modify(target="output", operation="replace", value="x"),
            Verdict.escalate(type="human_confirm"),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.ESCALATE

    def test_modify_before_allow(self):
        verdicts = [
            Verdict.allow(),
            Verdict.modify(target="output", operation="replace", value="x"),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.MODIFY

    def test_all_allow_returns_allow(self):
        verdicts = [Verdict.allow(), Verdict.allow(), Verdict.allow()]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.ALLOW


class TestUnanimousStrategy:

    def setup_method(self):
        self.strategy = UnanimousStrategy()

    def test_empty_verdicts_returns_allow(self):
        assert self.strategy.compose([]).decision == Decision.ALLOW

    def test_same_logic_as_deny_overrides(self):
        verdicts = [Verdict.allow(), Verdict.deny("no")]
        assert self.strategy.compose(verdicts).decision == Decision.DENY

    def test_all_allow_has_unanimous_reasoning(self):
        result = self.strategy.compose([Verdict.allow()])
        assert "agreed" in result.reasoning


class TestAllowOverridesStrategy:

    def setup_method(self):
        self.strategy = AllowOverridesStrategy()

    def test_empty_verdicts_returns_deny(self):
        result = self.strategy.compose([])
        assert result.decision == Decision.DENY

    def test_allow_overrides_deny(self):
        verdicts = [Verdict.deny("no"), Verdict.allow(), Verdict.deny("also no")]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.ALLOW

    def test_all_deny_returns_deny(self):
        verdicts = [Verdict.deny("a"), Verdict.deny("b")]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.DENY


class TestFirstApplicableStrategy:

    def setup_method(self):
        self.strategy = FirstApplicableStrategy()

    def test_empty_verdicts_returns_allow(self):
        assert self.strategy.compose([]).decision == Decision.ALLOW

    def test_first_non_observe_wins(self):
        verdicts = [
            Verdict.observe(),
            Verdict.observe(),
            Verdict.deny("found it"),
            Verdict.allow(),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.DENY

    def test_all_observe_returns_allow(self):
        verdicts = [Verdict.observe(), Verdict.observe()]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.ALLOW


class TestWeightedStrategy:

    def setup_method(self):
        self.strategy = WeightedStrategy()

    def test_empty_verdicts_returns_allow(self):
        assert self.strategy.compose([]).decision == Decision.ALLOW

    def test_high_deny_confidence_wins(self):
        verdicts = [
            Verdict.allow(confidence=0.3),
            Verdict.deny("risky", confidence=0.9),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.DENY

    def test_high_allow_confidence_wins(self):
        verdicts = [
            Verdict.allow(confidence=0.9),
            Verdict.deny("maybe", confidence=0.1),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.ALLOW

    def test_equal_scores_allow_wins(self):
        verdicts = [
            Verdict.allow(confidence=0.5),
            Verdict.deny("tie", confidence=0.5),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.ALLOW


class TestGetStrategy:

    def test_all_modes_resolve(self):
        for mode in CompositionMode:
            strategy = get_strategy(mode)
            assert hasattr(strategy, "compose")

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown composition mode"):
            get_strategy("nonexistent")


class TestVerdictComposer:

    def test_default_mode_is_deny_overrides(self):
        composer = VerdictComposer()
        assert composer.config.mode == CompositionMode.DENY_OVERRIDES

    def test_compose_delegates_to_strategy(self):
        composer = VerdictComposer()
        verdicts = [Verdict.allow(), Verdict.deny("x")]
        result = composer.compose(verdicts)
        assert result.decision == Decision.DENY

    def test_custom_mode(self):
        config = CompositionConfig(mode=CompositionMode.ALLOW_OVERRIDES)
        composer = VerdictComposer(config)
        verdicts = [Verdict.deny("x"), Verdict.allow()]
        result = composer.compose(verdicts)
        assert result.decision == Decision.ALLOW
