"""Core utility classes for eflips-lca.

Provides the ``ImpactVector`` base class and the ``DefaultImpactVector``
concrete subclass used throughout the package.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dc_fields
from typing import Any, TypeVar

_IV = TypeVar("_IV", bound="ImpactVector")


@dataclass
class ImpactVector:
    """Base class for environmental impact vectors.

    To define a category set, subclass this and add ``float`` fields with
    default ``0.0``::

        @dataclass
        class MyImpactVector(ImpactVector):
            gwp: float = 0.0   # kg CO2 eq
            pm: float = 0.0    # kg PM2.5 eq

    Arithmetic is implemented generically via ``dataclasses.fields()`` and
    works for any subclass without modification.
    """

    def _check_compatible(self, other: ImpactVector) -> None:
        """Verify that two ImpactVectors are of the same concrete type.

        Args:
            other: The other ImpactVector to compare against.

        Raises:
            TypeError: If the types do not match.
        """
        if type(self) is not type(other):
            raise TypeError(
                f"Cannot combine {type(self).__name__} and {type(other).__name__}"
            )

    def __add__(self: _IV, other: ImpactVector) -> _IV:
        """Element-wise addition of two impact vectors.

        Args:
            other: Another ImpactVector of the same concrete type.

        Returns:
            A new ImpactVector with element-wise sums.
        """
        self._check_compatible(other)
        return type(self)(
            **{
                f.name: getattr(self, f.name) + getattr(other, f.name)
                for f in dc_fields(self)
            }
        )

    def __sub__(self: _IV, other: ImpactVector) -> _IV:
        """Element-wise subtraction of two impact vectors.

        Args:
            other: Another ImpactVector of the same concrete type.

        Returns:
            A new ImpactVector with element-wise differences.
        """
        self._check_compatible(other)
        return type(self)(
            **{
                f.name: getattr(self, f.name) - getattr(other, f.name)
                for f in dc_fields(self)
            }
        )

    def __mul__(self: _IV, scalar: float) -> _IV:
        """Multiply all impact categories by a scalar.

        Args:
            scalar: The scalar multiplier.

        Returns:
            A new ImpactVector with all fields multiplied.
        """
        return type(self)(
            **{f.name: getattr(self, f.name) * scalar for f in dc_fields(self)}
        )

    def __rmul__(self: _IV, scalar: float) -> _IV:
        """Right-multiply (scalar * vector).

        Args:
            scalar: The scalar multiplier.

        Returns:
            A new ImpactVector with all fields multiplied.
        """
        return self.__mul__(scalar)

    def __truediv__(self: _IV, scalar: float) -> _IV:
        """Divide all impact categories by a scalar.

        Args:
            scalar: The scalar divisor.

        Returns:
            A new ImpactVector with all fields divided.
        """
        return type(self)(
            **{f.name: getattr(self, f.name) / scalar for f in dc_fields(self)}
        )

    def __neg__(self: _IV) -> _IV:
        """Negate all impact categories.

        Returns:
            A new ImpactVector with all fields negated.
        """
        return type(self)(**{f.name: -getattr(self, f.name) for f in dc_fields(self)})

    def to_dict(self) -> dict[str, float]:
        """Serialize to a plain dictionary suitable for JSONB storage.

        Returns:
            A dictionary mapping field names to their float values.
        """
        return {f.name: getattr(self, f.name) for f in dc_fields(self)}

    @classmethod
    def from_dict(cls: type[_IV], data: dict[str, Any]) -> _IV:
        """Deserialize from a dictionary.

        Args:
            data: A dictionary mapping field names to float values.

        Returns:
            An ImpactVector instance populated from the dictionary.
        """
        field_names = {f.name for f in dc_fields(cls)}
        filtered = {k: float(v) for k, v in data.items() if k in field_names}
        return cls(**filtered)

    @classmethod
    def zero(cls: type[_IV]) -> _IV:
        """Create a zero-valued impact vector.

        Returns:
            An ImpactVector with all fields set to ``0.0``.
        """
        return cls(**{f.name: 0.0 for f in dc_fields(cls)})


@dataclass
class DefaultImpactVector(ImpactVector):
    """The default 8-category impact vector used by this package.

    Subclass to add categories or replace with a different set.
    """

    gwp: float = 0.0
    """kg CO2 eq -- Global warming potential (100a)."""

    pm: float = 0.0
    """kg PM2.5 eq -- Particulate matter formation."""

    pocp: float = 0.0
    """kg NOx eq -- Photochemical ozone creation potential."""

    ap: float = 0.0
    """kg SO2 eq -- Acidification potential."""

    ep_freshwater: float = 0.0
    """kg P eq -- Freshwater eutrophication."""

    ep_marine: float = 0.0
    """kg N eq -- Marine eutrophication."""

    fuel: float = 0.0
    """kg Oil eq -- Fossil resource depletion."""

    water: float = 0.0
    """m³ -- Water consumption."""
