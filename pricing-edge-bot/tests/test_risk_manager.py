import json
import os

import pytest

import config
import risk_manager


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point risk_manager at a throwaway state file so tests don't touch
    (or depend on) the real state/risk_state.json."""
    state_file = tmp_path / "risk_state.json"
    monkeypatch.setattr(risk_manager, "STATE_PATH", str(state_file))
    yield state_file


def test_fresh_state_uses_starting_bankroll():
    rm = risk_manager.RiskManager()
    assert rm.state.bankroll == config.STARTING_BANKROLL


def test_check_passes_with_no_prior_activity():
    rm = risk_manager.RiskManager()
    assert rm.check("match-x|PlayerA", stake_usd=5.0) is None


def test_rejects_stake_larger_than_bankroll():
    rm = risk_manager.RiskManager()
    assert rm.check("match-x|PlayerA", stake_usd=rm.state.bankroll * 2) is not None


def test_cooldown_blocks_repeat_bet_on_same_market():
    rm = risk_manager.RiskManager()
    rm.record_bet_placed("match-x|PlayerA", stake_usd=5.0)
    reason = rm.check("match-x|PlayerA", stake_usd=5.0)
    assert reason is not None
    assert "cooldown" in reason or "already open" in reason


def test_max_open_positions_enforced():
    rm = risk_manager.RiskManager()
    for i in range(config.MAX_OPEN_POSITIONS):
        rm.record_bet_placed(f"match-{i}|PlayerA", stake_usd=1.0)
    reason = rm.check("match-new|PlayerA", stake_usd=1.0)
    assert reason is not None
    assert "max open positions" in reason


def test_max_bets_per_day_enforced():
    rm = risk_manager.RiskManager()
    for i in range(config.MAX_BETS_PER_DAY):
        rm.record_bet_placed(f"match-{i}|PlayerA", stake_usd=1.0)
        rm.record_result(f"match-{i}|PlayerA", won=True, pnl=1.0)
    reason = rm.check("match-final|PlayerA", stake_usd=1.0)
    assert reason is not None
    assert "max bets/day" in reason


def test_loss_streak_pauses_bot():
    rm = risk_manager.RiskManager()
    for i in range(config.LOSS_STREAK_PAUSE):
        rm.record_bet_placed(f"match-{i}|PlayerA", stake_usd=1.0)
        rm.record_result(f"match-{i}|PlayerA", won=False, pnl=-1.0)
    assert rm.state.paused is True
    reason = rm.check("match-new|PlayerA", stake_usd=1.0)
    assert "paused" in reason


def test_daily_loss_cap_enforced():
    rm = risk_manager.RiskManager()
    cap = config.DAILY_LOSS_CAP_FRACTION * rm.state.bankroll
    rm.record_bet_placed("match-x|PlayerA", stake_usd=cap)
    rm.record_result("match-x|PlayerA", won=False, pnl=-cap)
    reason = rm.check("match-y|PlayerB", stake_usd=1.0)
    assert reason is not None
    assert "daily loss cap" in reason


def test_state_persists_across_instances(isolated_state):
    rm1 = risk_manager.RiskManager()
    rm1.record_bet_placed("match-x|PlayerA", stake_usd=5.0)

    rm2 = risk_manager.RiskManager()
    assert "match-x|PlayerA" in rm2.state.open_positions
