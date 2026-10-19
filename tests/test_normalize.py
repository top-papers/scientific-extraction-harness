"""Unit/value normalization, reversible source retention, and strict error handling.

Covers C2 from work-packages.md and requirements from self-improvement-design.md (Phase 3).
"""

import pytest

from scientific_extraction_harness.normalize import (
    NORMALIZATION_SCHEMA_VERSION,
    NormalizationError,
    NormalizationResult,
    NormalizationRule,
    NormalizationTrace,
    normalize_value,
    normalize_record,
)


class TestNormalizationSchema:
    def test_schema_version_constant(self):
        assert NORMALIZATION_SCHEMA_VERSION == "1"

    def test_rule_version_validation(self):
        rule = NormalizationRule(
            rule_id="kg_to_g",
            source_unit="kg",
            target_unit="g",
            factor=1000,
            offset=0,
            version=NORMALIZATION_SCHEMA_VERSION,
        )
        assert rule.version == NORMALIZATION_SCHEMA_VERSION

    def test_rule_invalid_version_raises(self):
        with pytest.raises(ValueError, match="unsupported normalization version"):
            NormalizationRule(
                rule_id="r",
                source_unit="kg",
                target_unit="g",
                factor=1,
                offset=0,
                version="99",
            )


class TestNormalizationRule:
    def test_basic(self):
        rule = NormalizationRule("r1", "kg", "g", 1000)
        assert rule.rule_id == "r1"
        assert rule.source_unit == "kg"
        assert rule.target_unit == "g"
        assert rule.factor == 1000
        assert rule.offset == 0

    def test_aliases(self):
        rule = NormalizationRule("r2", "C", "K", 273.15, source_aliases=("°C", "deg C"))
        assert "C" in rule.accepted_units
        assert "°C" in rule.accepted_units
        assert "deg C" in rule.accepted_units

    def test_field_filter(self):
        rule = NormalizationRule("r3", "cm", "m", 0.01, field="length")
        assert rule.field == "length"
        assert rule.matches("cm", "length")
        assert not rule.matches("cm", "height")

    def test_numeric_factor_offset(self):
        rule = NormalizationRule("r4", "A", "V", "3", "10")
        assert rule.factor == 3
        assert rule.offset == 10

    def test_matches_case_and_spaces(self):
        rule = NormalizationRule("r5", "ml", "l", 0.001)
        assert rule.matches("ml")
        assert rule.matches("ML")
        assert rule.matches("mL")
        assert rule.matches("Ml")
        assert rule.matches("ML ")
        assert rule.matches("  ml  ")

    def test_matches_with_none_unit(self):
        rule = NormalizationRule("r6", "kg", "g")
        assert not rule.matches(None)

    def test_zero_factor_raises(self):
        with pytest.raises(ValueError, match="factor must not be zero"):
            NormalizationRule("r7", "foo", "bar", 0)

    def test_nonfinite_factor_raises(self):
        with pytest.raises(ValueError, match="factor and offset must be finite"):
            NormalizationRule("r8", "foo", "bar", float("inf"))

    def test_alias_empty(self):
        rule = NormalizationRule("r9", "unit", "target", source_aliases=())
        assert rule.source_aliases == ()


class TestNormalizationTrace:
    def test_trace_properties(self):
        trace = NormalizationTrace("10", "kg", "1000", "0", "g")
        assert trace.source_value == "10"
        assert trace.source_unit == "kg"
        assert trace.factor == "1000"
        assert trace.offset == "0"
        assert trace.target_unit == "g"

    def test_trace_to_dict(self):
        trace = NormalizationTrace("5", None, "0.5", "2", "cm")
        d = trace.to_dict()
        assert d["source_value"] == "5"
        assert d["source_unit"] == None


class TestNormalizationResult:
    def test_abstained_default(self):
        res = NormalizationResult("foo", None, None, None, None, None)
        assert res.abstained
        assert res.status == "abstained"

    def test_normalized(self):
        res = NormalizationResult("5", "kg", "5000", "g", "r1", None, "normalized")
        assert not res.abstained
        assert res.source_value == "5"
        assert res.source_unit == "kg"
        assert res.normalized_value == "5000"
        assert res.normalized_unit == "g"
        assert res.rule_id == "r1"

    def test_abstained_with_reason(self):
        res = NormalizationResult(1, "kg", None, None, None, None, "abstained", reason="unknown unit")
        assert res.reason == "unknown unit"

    def test_to_dict_with_trace(self):
        trace = NormalizationTrace("5", "kg", "1000", "0", "g")
        res = NormalizationResult("5", "kg", "5000", "g", "r1", trace)
        d = res.to_dict()
        assert d["trace"]["source_value"] == "5"

    def test_reverse(self):
        res = NormalizationResult("5", "kg", "5000", "g", "r1", None)
        assert res.reverse() == ("5", "kg")


class TestNormalizeValue:
    def test_exact_match(self):
        rule = NormalizationRule("kg2g", "kg", "g", 1000)
        res = normalize_value("2", "kg", [rule])
        assert res.normalized_value == "2000"
        assert res.normalized_unit == "g"
        assert res.rule_id == "kg2g"
        assert not res.abstained

    def test_alias_match(self):
        rule = NormalizationRule("c2k", "C", "K", 1, 273.15, source_aliases=("deg C",))
        res = normalize_value("0", "deg C", [rule])
        assert res.normalized_value == "273.15"
        assert res.normalized_unit == "K"

    def test_field_filter(self):
        rule = NormalizationRule("length_cm_m", "cm", "m", 0.01, field="length")
        res = normalize_value("100", "cm", [rule], field="length")
        assert res.normalized_value == "1"
        assert not rule.matches("cm", "height")

    def test_no_match_abstained(self):
        rule = NormalizationRule("r", "kg", "g")
        res = normalize_value("5", "lb", [rule])
        assert res.abstained
        assert res.normalized_value is None
        assert res.reason == "unknown unit mapping"

    def test_multiple_matches_abstained(self):
        rule1 = NormalizationRule("r1", "C", "K", 273.15, field="temp")
        rule2 = NormalizationRule("r2", "C", "K", 1, field="temp")
        res = normalize_value("0", "C", [rule1, rule2], field="temp")
        assert res.abstained
        assert res.reason == "ambiguous unit mapping"

    def test_numeric_types(self):
        rule = NormalizationRule("int", "A", "V", 2, 0)
        res = normalize_value(5, "A", [rule])
        assert res.normalized_value == "10"
        res2 = normalize_value("3.5", "A", [rule])
        assert res2.normalized_value == "7"

    def test_decimal_format(self):
        rule = NormalizationRule("scale", "cm", "m", 0.01)
        res = normalize_value("1.00", "cm", [rule])
        assert res.normalized_value == "0.01"
        res2 = normalize_value("1.50", "cm", [rule])
        assert res2.normalized_value == "0.015"

    def test_non_numeric_value_abstained(self):
        rule = NormalizationRule("num", "x", "y", 1)
        res = normalize_value("xyz", "x", [rule])
        assert res.abstained
        assert res.reason == "value is not numeric"

    def test_infinite_value_abstained(self):
        rule = NormalizationRule("num", "x", "y", 1)
        res = normalize_value(float("inf"), "x", [rule])
        assert res.abstained
        assert res.reason == "value is not finite"

    def test_strict_mode_unknown_unit(self):
        rule = NormalizationRule("r", "kg", "g")
        with pytest.raises(NormalizationError, match="unknown unit mapping"):
            normalize_value("5", "lb", [rule], strict=True)

    def test_strict_mode_ambiguous_unit(self):
        rule1 = NormalizationRule("r1", "C", "K")
        rule2 = NormalizationRule("r2", "C", "K")
        with pytest.raises(NormalizationError, match="ambiguous unit mapping"):
            normalize_value("0", "C", [rule1, rule2], strict=True)

    def test_strict_mode_non_numeric(self):
        rule = NormalizationRule("r", "kg", "g")
        with pytest.raises(NormalizationError, match="value is not numeric"):
            normalize_value("xyz", "kg", [rule], strict=True)


class TestNormalizeRecord:
    def test_normalize_record_basic(self):
        class MockRecord:
            document_id = "doc1"
            page = 1
            modality = "table"
            locator = "table:2/row:1/column:value"
            field = "length"
            value = "100"
            unit = "cm"
            confidence = 0.9
            status = "candidate"
            reviewer_note = None

        rule = NormalizationRule("cm2m", "cm", "m", 0.01, field="length")
        res = normalize_record(MockRecord(), [rule])
        assert res.normalized_value == "1"
        assert res.normalized_unit == "m"
        assert res.source_value == "100"
        assert res.source_unit == "cm"

    def test_normalize_record_no_field(self):
        class MockRecord:
            value = "5"
            unit = "kg"

        rule = NormalizationRule("kg2g", "kg", "g", 1000)
        res = normalize_record(MockRecord(), [rule])
        assert res.normalized_value == "5000"
        assert res.normalized_unit == "g"


class TestDeterministicBehavior:
    def test_idempotent_normalized_values(self):
        rule = NormalizationRule("C2K", "C", "K", 273.15)
        res1 = normalize_value("0", "C", [rule])
        res2 = normalize_value("0", "C", [rule])
        assert res1.normalized_value == res2.normalized_value
        assert res1.normalized_unit == res2.normalized_unit
        assert res1.rule_id == res2.rule_id

    def test_reverse_preserves_source(self):
        rule = NormalizationRule("kg2g", "kg", "g", 1000)
        res = normalize_value("2.5", "kg", [rule])
        assert res.reverse() == ("2.5", "kg")

    def test_abstained_is_deterministic(self):
        rule = NormalizationRule("r", "kg", "g")
        res1 = normalize_value("5", "lb", [rule])
        res2 = normalize_value("5", "lb", [rule])
        assert res1.status == "abstained"
        assert res2.status == "abstained"
        assert res1.reason == res2.reason

    def test_trace_consistency(self):
        rule = NormalizationRule("trace_rule", "mm", "m", 0.001)
        res = normalize_value("150", "mm", [rule])
        assert res.trace is not None
        assert res.trace.source_value == "150"
        assert res.trace.source_unit == "mm"
        assert res.trace.factor == "0.001"
        assert res.trace.target_unit == "m"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])