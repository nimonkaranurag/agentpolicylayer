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
from apl.types import (
    CompositionConfig,
    CompositionMode,
    Decision,
    Verdict,
)


def _named(verdict: Verdict, name: str) -> Verdict:
    """
    Attach a ``policy_name`` to a verdict.

    The ``Verdict`` factories don't take one, but weighted/priority composition keys on
    it, so the config-driven tests set it explicitly.
    """
    verdict.policy_name = name
    return verdict


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
        verdicts = [
            Verdict.allow(),
            Verdict.deny("blocked"),
            Verdict.allow(),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.DENY

    def test_escalate_before_modify(self):
        verdicts = [
            Verdict.modify(
                target="output",
                operation="replace",
                value="x",
            ),
            Verdict.escalate(type="human_confirm"),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.ESCALATE

    def test_modify_before_allow(self):
        verdicts = [
            Verdict.allow(),
            Verdict.modify(
                target="output",
                operation="replace",
                value="x",
            ),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.MODIFY

    def test_all_allow_returns_allow(self):
        verdicts = [
            Verdict.allow(),
            Verdict.allow(),
            Verdict.allow(),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.ALLOW


class TestUnanimousStrategy:
    """
    Real unanimity: every non-observe verdict must ALLOW, else deny.

    These replace ``test_same_logic_as_deny_overrides``, which encoded the bug by
    asserting Unanimous == DenyOverrides.
    """

    def setup_method(self):
        self.strategy = UnanimousStrategy()

    def test_empty_verdicts_returns_allow(self):
        assert self.strategy.compose([]).decision == Decision.ALLOW

    def test_all_allow_is_allow(self):
        verdicts = [Verdict.allow(), Verdict.allow()]
        assert self.strategy.compose(verdicts).decision == Decision.ALLOW

    def test_any_deny_breaks_unanimity(self):
        verdicts = [Verdict.allow(), Verdict.deny("no")]
        assert self.strategy.compose(verdicts).decision == Decision.DENY

    def test_modify_breaks_unanimity(self):
        # The old deny-overrides impl carried the lone MODIFY through; real
        # unanimity denies. Fails against pre-fix code.
        verdicts = [
            Verdict.allow(),
            Verdict.modify(target="output", operation="replace", value="x"),
        ]
        assert self.strategy.compose(verdicts).decision == Decision.DENY

    def test_escalate_breaks_unanimity(self):
        # The old impl surfaced the ESCALATE; real unanimity denies.
        verdicts = [
            Verdict.allow(),
            Verdict.escalate(type="human_confirm"),
        ]
        assert self.strategy.compose(verdicts).decision == Decision.DENY

    def test_observe_abstains(self):
        verdicts = [Verdict.allow(), Verdict.observe()]
        assert self.strategy.compose(verdicts).decision == Decision.ALLOW

    def test_all_observe_is_allow(self):
        verdicts = [Verdict.observe(), Verdict.observe()]
        assert self.strategy.compose(verdicts).decision == Decision.ALLOW

    def test_all_allow_has_unanimous_reasoning(self):
        result = self.strategy.compose([Verdict.allow()])
        assert "agreed" in result.reasoning

    def test_deny_reason_records_dissent(self):
        verdicts = [Verdict.allow(), Verdict.deny("PII detected")]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.DENY
        assert "PII detected" in result.reasoning


class TestAllowOverridesStrategy:
    def setup_method(self):
        self.strategy = AllowOverridesStrategy()

    def test_empty_verdicts_returns_allow(self):
        # LSP fix: every strategy treats "no policy had an
        # opinion" as allow. This used to deny — an empty-input surprise when
        # swapping strategies. Fails against pre-fix code.
        result = self.strategy.compose([])
        assert result.decision == Decision.ALLOW

    def test_allow_overrides_deny(self):
        verdicts = [
            Verdict.deny("no"),
            Verdict.allow(),
            Verdict.deny("also no"),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.ALLOW

    def test_all_deny_returns_deny(self):
        verdicts = [
            Verdict.deny("a"),
            Verdict.deny("b"),
        ]
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
        verdicts = [
            Verdict.observe(),
            Verdict.observe(),
        ]
        result = self.strategy.compose(verdicts)
        assert result.decision == Decision.ALLOW

    def test_priority_reorders_selection(self):
        # Arrival order would pick the allow first; priority elevates "high"
        # so its deny wins. Fails against pre-fix code (priority ignored).
        config = CompositionConfig(
            mode=CompositionMode.FIRST_APPLICABLE,
            priority=["high"],
        )
        strategy = FirstApplicableStrategy(config)
        verdicts = [
            _named(Verdict.allow(), "low"),
            _named(Verdict.deny("blocked"), "high"),
        ]
        assert strategy.compose(verdicts).decision == Decision.DENY

    def test_no_priority_uses_arrival_order(self):
        strategy = FirstApplicableStrategy()
        verdicts = [
            _named(Verdict.deny("first"), "a"),
            _named(Verdict.allow(), "b"),
        ]
        assert strategy.compose(verdicts).decision == Decision.DENY

    def test_unranked_policies_keep_relative_order(self):
        # priority names nothing in this set; arrival order must be preserved.
        config = CompositionConfig(
            mode=CompositionMode.FIRST_APPLICABLE,
            priority=["absent"],
        )
        strategy = FirstApplicableStrategy(config)
        verdicts = [
            _named(Verdict.deny("first"), "a"),
            _named(Verdict.allow(), "b"),
        ]
        assert strategy.compose(verdicts).decision == Decision.DENY


class TestWeightedStrategy:
    """
    Weighted voting.

    The no-config cases below document the default-weight (1.0) fallback, where the
    score reduces to a sum of confidences. The ``test_*_weight_*`` cases exercise
    ``CompositionConfig.weights`` and fail against pre-fix code, which ignored the
    weights map entirely.
    """

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

    def test_configured_weight_overrides_confidence(self):
        # A heavily-weighted, modest-confidence deny beats a default-weight,
        # high-confidence allow: allow=1.0*0.9=0.9 vs deny=10.0*0.5=5.0.
        config = CompositionConfig(
            mode=CompositionMode.WEIGHTED,
            weights={"strict": 10.0},
        )
        strategy = WeightedStrategy(config)
        verdicts = [
            _named(Verdict.allow(confidence=0.9), "lenient"),
            _named(Verdict.deny("risky", confidence=0.5), "strict"),
        ]
        assert strategy.compose(verdicts).decision == Decision.DENY

    def test_zero_weight_silences_policy(self):
        # A zero-weighted deny cannot block: allow=1.0*0.4=0.4 vs deny=0.0.
        config = CompositionConfig(
            mode=CompositionMode.WEIGHTED,
            weights={"noisy": 0.0},
        )
        strategy = WeightedStrategy(config)
        verdicts = [
            _named(Verdict.allow(confidence=0.4), "trusted"),
            _named(Verdict.deny("spurious", confidence=1.0), "noisy"),
        ]
        assert strategy.compose(verdicts).decision == Decision.ALLOW


class TestGetStrategy:
    def test_each_mode_composes_to_documented_decision(self):
        # Replaces a hasattr() tautology with a real behavioural check per mode
        # over the same mixed input, and guards that every mode is covered.
        verdicts = [Verdict.allow(), Verdict.deny("no")]
        expected = {
            CompositionMode.DENY_OVERRIDES: Decision.DENY,
            CompositionMode.ALLOW_OVERRIDES: Decision.ALLOW,
            CompositionMode.UNANIMOUS: Decision.DENY,
            CompositionMode.FIRST_APPLICABLE: Decision.ALLOW,
            CompositionMode.WEIGHTED: Decision.ALLOW,  # 1.0 vs 1.0 tie -> allow
        }
        assert set(expected) == set(CompositionMode)
        for mode, decision in expected.items():
            assert get_strategy(mode).compose(verdicts).decision == decision, mode

    def test_unknown_mode_raises(self):
        with pytest.raises(
            ValueError,
            match="Unknown composition mode",
        ):
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

    def test_composer_threads_config_into_strategy(self):
        # End-to-end proof that config flows composer -> get_strategy ->
        # strategy: the weights map must reach WeightedStrategy. Pre-fix the
        # strategy was constructed without config, so weights had no effect.
        config = CompositionConfig(
            mode=CompositionMode.WEIGHTED,
            weights={"strict": 10.0},
        )
        composer = VerdictComposer(config)
        verdicts = [
            _named(Verdict.allow(confidence=0.9), "lenient"),
            _named(Verdict.deny("risky", confidence=0.5), "strict"),
        ]
        assert composer.compose(verdicts).decision == Decision.DENY
