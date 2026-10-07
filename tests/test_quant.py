from app.quant.metrics import find_metric, weighted_score


def test_find_metric_nested_data():
    data = {"result": {"roe": 18.5, "pe": 11.2}}
    assert find_metric(data, "roe") == 18.5
    assert find_metric(data, "pe", "per") == 11.2


def test_weighted_score_ignores_missing_categories():
    score = weighted_score({"valuation": 80, "quality": None, "growth": 60, "momentum": None, "risk": None})
    assert score == 71.1


def test_weighted_score_none_when_no_data():
    assert weighted_score({"valuation": None, "quality": None}) is None
