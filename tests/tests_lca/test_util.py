"""Tests for eflips.lca.util (ImpactVector / DefaultImpactVector)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from eflips.impact.lca.util import DefaultImpactVector, ImpactVector


@dataclass
class _OtherVector(ImpactVector):
    """A different concrete ImpactVector subclass used to test type guards."""

    x: float = 0.0


_A = DefaultImpactVector(gwp=1.0, pm=2.0, pocp=3.0, ap=4.0)
_B = DefaultImpactVector(gwp=10.0, pm=20.0, pocp=30.0, ap=40.0)


def test_add() -> None:
    result = _A + _B
    assert result.gwp == pytest.approx(11.0)
    assert result.pm == pytest.approx(22.0)


def test_sub() -> None:
    result = _B - _A
    assert result.gwp == pytest.approx(9.0)
    assert result.pm == pytest.approx(18.0)


def test_mul_scalar() -> None:
    result = _A * 3.0
    assert result.gwp == pytest.approx(3.0)
    assert result.pm == pytest.approx(6.0)


def test_rmul_scalar() -> None:
    result = 3.0 * _A
    assert result.gwp == pytest.approx(3.0)


def test_div_scalar() -> None:
    result = _B / 10.0
    assert result.gwp == pytest.approx(1.0)
    assert result.pm == pytest.approx(2.0)


def test_neg() -> None:
    result = -_A
    assert result.gwp == pytest.approx(-1.0)
    assert result.pm == pytest.approx(-2.0)


def test_zero() -> None:
    z = DefaultImpactVector.zero()
    for val in z.to_dict().values():
        assert val == pytest.approx(0.0)


def test_to_from_dict_roundtrip() -> None:
    d = _A.to_dict()
    restored = DefaultImpactVector.from_dict(d)
    assert restored == _A


def test_from_dict_ignores_unknown_keys() -> None:
    d = _A.to_dict()
    d["unknown_category"] = 99.9
    restored = DefaultImpactVector.from_dict(d)
    assert restored == _A


def test_type_mismatch_raises() -> None:
    other = _OtherVector(x=1.0)
    with pytest.raises(TypeError):
        _ = _A + other  # type: ignore[operator]
