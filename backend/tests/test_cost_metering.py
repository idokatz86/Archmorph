"""Tests for cost_metering.py — token cost tracking and budget management."""

from cost_metering import (
    CostMeter,
    calculate_cost,
    BudgetCreateRequest,
    BudgetPeriod,
)


class TestCalculateCost:
    def test_known_model(self):
        cost = calculate_cost("gpt-4o", prompt_tokens=1000, completion_tokens=500)
        assert cost > 0

    def test_unknown_model_uses_default(self):
        cost = calculate_cost("unknown-model", prompt_tokens=1000, completion_tokens=500)
        assert cost > 0

    def test_zero_tokens(self):
        cost = calculate_cost("gpt-4o", prompt_tokens=0, completion_tokens=0)
        assert cost == 0.0


class TestCostMeter:
    def setup_method(self):
        CostMeter.reset()
        self.meter = CostMeter.instance()

    def test_singleton(self):
        m1 = CostMeter.instance()
        m2 = CostMeter.instance()
        assert m1 is m2

    def test_reset_creates_new_instance(self):
        m1 = CostMeter.instance()
        CostMeter.reset()
        m2 = CostMeter.instance()
        assert m1 is not m2

    def test_record_creates_cost_record(self):
        rec = self.meter.record(
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            agent_id="test-agent",
        )
        assert rec.model == "gpt-4o"
        assert rec.prompt_tokens == 100
        assert rec.completion_tokens == 50
        assert rec.cost_usd > 0

    def test_get_overview_empty(self):
        overview = self.meter.get_overview()
        assert overview.total_spend_usd == 0.0
        assert overview.total_records == 0

    def test_get_overview_with_records(self):
        self.meter.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        self.meter.record(model="gpt-4o", prompt_tokens=200, completion_tokens=100)
        overview = self.meter.get_overview()
        assert overview.total_records == 2
        assert overview.total_spend_usd > 0

    def test_get_agent_cost(self):
        self.meter.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50, agent_id="a1")
        self.meter.record(model="gpt-4o", prompt_tokens=200, completion_tokens=100, agent_id="a2")
        agent_cost = self.meter.get_agent_cost("a1")
        assert agent_cost.total_executions == 1

    def test_get_model_breakdown(self):
        self.meter.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        self.meter.record(model="gpt-4o-mini", prompt_tokens=200, completion_tokens=100)
        breakdown = self.meter.get_model_breakdown()
        assert len(breakdown) == 2

    def test_get_timeseries(self):
        self.meter.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        ts = self.meter.get_timeseries(granularity="hourly")
        assert isinstance(ts, list)

    def test_get_top_consumers(self):
        self.meter.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50, agent_id="a1")
        top = self.meter.get_top_consumers(limit=5)
        assert isinstance(top, list)

    def test_export_csv(self):
        self.meter.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        csv = self.meter.export_csv()
        assert "model" in csv
        assert "gpt-4o" in csv

    def test_budget_lifecycle(self):
        budget = self.meter.create_budget(BudgetCreateRequest(
            agent_id="test-agent",
            amount_usd=100.0,
            period=BudgetPeriod.MONTHLY,
        ))
        assert budget.agent_id == "test-agent"

        budgets = self.meter.list_budgets()
        assert len(budgets) >= 1

    def test_is_budget_exceeded_false(self):
        self.meter.create_budget(BudgetCreateRequest(
            agent_id="test-agent",
            amount_usd=100.0,
            period=BudgetPeriod.MONTHLY,
        ))
        assert self.meter.is_budget_exceeded("test-agent") is False

    def test_get_alerts_empty(self):
        alerts = self.meter.get_alerts()
        assert isinstance(alerts, list)
