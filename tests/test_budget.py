import pytest
from arma.budget import Budget,BudgetExceeded

def test_reserve_then_actual_and_restart(tmp_path):
    p=tmp_path/'budget.sqlite';b=Budget(p,api_limit=0.1)
    key=b.reserve(.08)
    with pytest.raises(BudgetExceeded):b.reserve(.03)
    b.settle(key,.01)
    assert Budget(p,api_limit=.1).remaining()==pytest.approx(.09)
    b.settle(key,.01)
    with pytest.raises(ValueError):b.settle(key,.02)

def test_ambiguous_call_keeps_reserve(tmp_path):
    b=Budget(tmp_path/'b',api_limit=.05);b.reserve(.05)
    with pytest.raises(BudgetExceeded):b.reserve(.00001)

def test_categories_cannot_borrow_reserve(tmp_path):
    b=Budget(tmp_path/'b');b.reserve(4)
    with pytest.raises(BudgetExceeded):b.reserve(.01)
    b.reserve(5,'compute')
    assert sum(b.totals().values())==9
