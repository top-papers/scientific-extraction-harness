"""Tests for domain-specific extraction knowledge (survey findings)."""

from __future__ import annotations

import pytest

from scientific_extraction_harness.domain_knowledge import (
    AERODYNAMICS,
    CONTROL,
    DOMAINS,
    RADAR,
    STRENGTH,
    domain_prompt,
    get_domain_profile,
    list_domains,
    run_domain_checks,
)


@pytest.mark.parametrize("domain", DOMAINS)
def test_profiles_are_complete(domain):
    profile = get_domain_profile(domain)
    assert profile.domain == domain
    assert profile.title
    assert profile.fields, "each domain must name typical variables"
    assert profile.chart_types, "each domain must name chart vocabulary"
    assert profile.checks, "each domain must ship at least one sanity check"
    # serializable, prompt-usable
    data = profile.to_dict()
    assert data["domain"] == domain
    assert domain_prompt(domain)


def test_unknown_domain_fails_closed():
    with pytest.raises(ValueError):
        get_domain_profile("chemistry")


def test_list_domains_matches_profiles():
    assert list_domains() == ("aerodynamics", "radar", "control", "strength")


# --- physical sanity checks -------------------------------------------------


def test_aerodynamics_negative_drag_flagged():
    record = {"field": "drag_coefficient", "value": "-0.01", "unit": "dimensionless", "modality": "text"}
    assert run_domain_checks("aerodynamics", record) == ["drag coefficient must be positive"]


def test_aerodynamics_valid_polar_value_passes():
    record = {"field": "lift_coefficient", "value": "1.42", "unit": "dimensionless", "modality": "table"}
    assert run_domain_checks("aerodynamics", record) == []


def test_aerodynamics_malformed_value_is_silent():
    # schema validation owns malformed inputs; sanity checks stay defensive
    record = {"field": "drag_coefficient", "value": "n/a", "unit": None, "modality": "text"}
    assert run_domain_checks("aerodynamics", record) == []


def test_radar_probability_bounds():
    assert run_domain_checks("radar", {"field": "detection_probability", "value": "1.2"}) == [
        "detection probability must be in [0, 1]"
    ]
    assert run_domain_checks("radar", {"field": "pfa", "value": "0"}) == [
        "false-alarm probability must be in (0, 1]"
    ]
    assert run_domain_checks("radar", {"field": "detection_probability", "value": "0.9"}) == []


def test_control_overshoot_range():
    assert run_domain_checks("control", {"field": "overshoot", "value": "250"}) == [
        "percent overshoot outside plausible range (0-200%)"
    ]
    assert run_domain_checks("control", {"field": "settling_time", "value": "-2", "unit": "s"}) == [
        "time constant must be positive"
    ]


def test_strength_positive_strength_and_censoring_notes():
    assert run_domain_checks("strength", {"field": "yield_strength", "value": "-5", "unit": "MPa"}) == [
        "strength must be positive"
    ]
    assert run_domain_checks("strength", {"field": "elongation", "value": "150", "unit": "percent"}) == [
        "elongation outside 0-100% — check whether value is a strain ratio"
    ]
    # S-N notes survive in the profile for prompts
    assert any("run-out" in note or "Run-out" in note for note in STRENGTH.notes)


def test_checks_are_pure_and_defensive():
    # missing keys must not raise
    for domain in DOMAINS:
        assert run_domain_checks(domain, {}) == []


def test_prompt_lines_cover_fields_and_conditions():
    lines = domain_prompt("strength").splitlines()
    assert any("stress-strain" in line or "S-N" in line for line in lines)
    assert any("stress_ratio_r" in line for line in lines)
