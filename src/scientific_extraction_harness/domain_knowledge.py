"""Domain-specific extraction knowledge distilled from the research survey.

The survey phase (`research_search_results/` in the working workspace; summary in
`docs/domain-extraction-survey.md`) studied how LLM/VLM extraction of experimental
data transfers to four engineering domains: aerodynamics, radar, control systems
and structural strength.  This module exposes that knowledge as data:

- per-domain field vocabularies and chart types for prompts and validation;
- physical sanity-check predicates applied to candidate records;
- unit hints used by the reversible normalization layer.

Nothing here approves a record, performs a network call or converts values
silently.  Every check is advisory: it lowers confidence and adds a reviewer note
via the existing evidence/normalization machinery; the human remains the only
approval authority (see AGENTS.md rules 3-4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

DOMAIN_SCHEMA_VERSION = "1"

DOMAINS = ("aerodynamics", "radar", "control", "strength")


@dataclass(frozen=True)
class DomainProfile:
    """Extraction profile for one engineering domain."""

    domain: str
    title: str
    fields: tuple[str, ...] = ()            # normalized variable names the domain cares about
    chart_types: tuple[str, ...] = ()       # figure vocabulary for classification prompts
    units: tuple[str, ...] = ()             # canonical unit strings (never auto-converted)
    conditions: tuple[str, ...] = ()        # experimental conditions to capture as metadata
    checks: tuple[Callable[[Mapping[str, object]], str | None], ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "title": self.title,
            "fields": list(self.fields),
            "chart_types": list(self.chart_types),
            "units": list(self.units),
            "conditions": list(self.conditions),
            "notes": list(self.notes),
        }

    def prompt_lines(self) -> list[str]:
        """Domain additions for the extraction SYSTEM_PROMPT (advisory guidance)."""
        lines = [f"Domain context: {self.title}."]
        if self.fields:
            lines.append("Typical measured variables: " + ", ".join(self.fields) + ".")
        if self.conditions:
            lines.append("Always capture experimental conditions when stated: " + ", ".join(self.conditions) + ".")
        if self.chart_types:
            lines.append("Figure vocabulary: " + ", ".join(self.chart_types) + ".")
        lines.extend(self.notes)
        return lines


# --- physical sanity checks -------------------------------------------------
# Each check receives a mapping with at least field/value/unit/modality and
# returns a human-readable problem string or None.  Checks must be pure and
# defensive: malformed input yields None (other validators own schema errors).

def _num(value: object) -> float | None:
    try:
        text = str(value).strip().replace(",", ".")
        return float(text)
    except (TypeError, ValueError):
        return None


def _field_in(field_name: object, *keys: str) -> bool:
    text = str(field_name or "").lower()
    return any(k in text for k in keys)


def check_aerodynamics(record: Mapping[str, object]) -> str | None:
    field_name, value = record.get("field"), record.get("value")
    number = _num(value)
    if number is None:
        return None
    if _field_in(field_name, "cd", "drag_coefficient") and number <= 0:
        return "drag coefficient must be positive"
    if _field_in(field_name, "cl", "lift_coefficient") and not -3 <= number <= 3:
        return "lift coefficient outside plausible range (-3..3)"
    if _field_in(field_name, "re", "reynolds") and not 1e3 <= number <= 1e9:
        return "Reynolds number outside plausible range"
    if _field_in(field_name, "mach") and not 0 <= number <= 30:
        return "Mach number outside plausible range"
    return None


def check_radar(record: Mapping[str, object]) -> str | None:
    field_name, value = record.get("field"), record.get("value")
    number = _num(value)
    if number is None:
        return None
    if _field_in(field_name, "pd", "detection_prob", "probability_detection") and not 0 <= number <= 1:
        return "detection probability must be in [0, 1]"
    if _field_in(field_name, "pfa", "false_alarm") and not 0 < number <= 1:
        return "false-alarm probability must be in (0, 1]"
    if _field_in(field_name, "snr") and not -50 <= number <= 200:
        return "SNR (dB) outside plausible range"
    if _field_in(field_name, "frequency", "carrier") and number < 0:
        return "frequency must be positive"
    return None


def check_control(record: Mapping[str, object]) -> str | None:
    field_name, value = record.get("field"), record.get("value")
    number = _num(value)
    if number is None:
        return None
    if _field_in(field_name, "overshoot", "sigma") and not 0 <= number <= 200:
        # percent overshoot; >200% is almost certainly a unit mix-up
        return "percent overshoot outside plausible range (0-200%)"
    if _field_in(field_name, "kp", "ki", "kd", "gain") and abs(number) > 1e8:
        return "controller gain implausibly large"
    if _field_in(field_name, "settling_time", "rise_time") and number <= 0:
        return "time constant must be positive"
    return None


def check_strength(record: Mapping[str, object]) -> str | None:
    field_name, value, unit = record.get("field"), record.get("value"), record.get("unit")
    number = _num(value)
    if number is None:
        return None
    if _field_in(field_name, "yield", "sigma_y", "uts", "tensile") and number <= 0:
        return "strength must be positive"
    if _field_in(field_name, "elongation") and not 0 <= number <= 100:
        # percent elongation; >100% needs a note (possible strain ratio instead)
        return "elongation outside 0-100% — check whether value is a strain ratio"
    if _field_in(field_name, "cycles", "n_f", "fatigue_life") and number <= 0:
        return "fatigue life must be positive"
    if _field_in(field_name, "young", "modulus") and unit and str(unit).lower() in ("mpa", "gpa") and number <= 0:
        return "elastic modulus must be positive"
    return None


AERODYNAMICS = DomainProfile(
    domain="aerodynamics",
    title="Aerodynamics (airfoil/wing polars, pressure distributions, flow fields)",
    fields=("lift_coefficient", "drag_coefficient", "moment_coefficient", "lift_to_drag_ratio",
            "max_lift_coefficient", "stall_angle", "pressure_coefficient", "reynolds_number",
            "mach_number", "turbulence_intensity", "boundary_layer_thickness"),
    chart_types=("polar Cl-α", "drag polar Cd-Cl", "Cp(x/c) distribution", "step-response-like transients",
                 "multi-series polar family", "wake profile"),
    units=("dimensionless", "deg", "m", "m/s", "Pa", "kg/m3"),
    conditions=("reynolds_number", "mach_number", "tunnel_type", "turbulence_intensity",
                "model_scale", "surface_roughness", "blockage_correction"),
    checks=(check_aerodynamics,),
    notes=(
        "NACA/NASA reports (public domain) are the recommended corpus: OCR quality is low, "
        "foldout figures may hold dozens of polars per sheet.",
        "Log-scale drag axes and 3-6 series per panel are typical; digitized points are "
        "candidates, never measurements equivalent to an author-provided source table.",
    ),
)

RADAR = DomainProfile(
    domain="radar",
    title="Radiolocation (RCS, antenna patterns, detection statistics)",
    fields=("radar_cross_section", "antenna_gain", "beamwidth", "detection_probability",
            "false_alarm_probability", "signal_to_noise_ratio", "carrier_frequency", "transmit_power",
            "pulse_repetition_frequency", "range_resolution", "sidelobe_level"),
    chart_types=("RCS vs angle (polar)", "RCS vs frequency", "antenna pattern (polar dB)",
                 "Pd vs SNR (Swerling/ Marcum curves)", "ROC curve", "range-Doppler map"),
    units=("dBsm", "m2", "dB", "dBi", "deg", "Hz", "GHz", "W", "dBm"),
    conditions=("polarization", "mono_or_bistatic", "target_class", "frequency_band",
                "waveform", "bandwidth", "chirp_parameters"),
    checks=(check_radar,),
    notes=(
        "Defence-related measurements are frequently de-identified (axes in relative units): "
        "keep unit=null and flag for the reviewer instead of guessing the scale.",
        "Run-out/censored-style markers have no radar analogue, but Swerling-family curves "
        "put many dense series on one log panel — one record per series value, never merged.",
    ),
)

CONTROL = DomainProfile(
    domain="control",
    title="Control systems (transient and frequency responses, controller parameters)",
    fields=("rise_time", "settling_time", "overshoot", "peak_time", "gain_margin",
            "phase_margin", "bandwidth", "crossover_frequency", "kp", "ki", "kd",
            "natural_frequency", "damping_ratio", "steady_state_error"),
    chart_types=("step response", "impulse response", "Bode magnitude", "Bode phase",
                 "Nyquist hodograph", "Nichols chart", "error-vs-time"),
    units=("s", "ms", "Hz", "rad/s", "dB", "deg", "percent", "dimensionless"),
    conditions=("plant_model", "controller_structure", "actuator_limits", "sampling_time",
                "simulation_or_experiment", "normalization_reference"),
    checks=(check_control,),
    notes=(
        "IEEE/Automatica figures are usually vector PDFs (easy digitization); Russian-language "
        "journals often use per-unit axes — preserve the normalization metadata.",
        "Log-log Bode axes are a known VLM failure mode: read axes via OCR, cross-check values "
        "against formulas in the text (transfer functions are a second source of truth).",
    ),
)

STRENGTH = DomainProfile(
    domain="strength",
    title="Structural strength (stress-strain, fatigue, fracture, creep)",
    fields=("yield_strength", "ultimate_tensile_strength", "youngs_modulus", "elongation",
            "hardness", "fracture_toughness", "j_integral", "fatigue_limit", "sn_curve_stress",
            "cycles_to_failure", "creep_rate", "rupture_time", "stress_ratio"),
    chart_types=("stress-strain curve", "S-N curve (log-log)", "creep curve (strain-time)",
                 "Goodman/Haigh diagram", "J-R resistance curve", "da/dN vs ΔK"),
    units=("MPa", "GPa", "ksi", "N", "mm", "percent", "h", "cycles", "dimensionless"),
    conditions=("material_grade", "heat_treatment", "temperature", "orientation",
                "specimen_standard", "stress_ratio_r", "loading_frequency", "censored_runout"),
    checks=(check_strength,),
    notes=(
        "Run-out points on S-N curves (arrows, N > 1e7 without failure) must be marked as "
        "censored in the conditions, never digitized as ordinary failure points.",
        "MPa vs ksi and log10 vs ln in OCR'd axis labels are the top source of 10x scale "
        "errors; prefer abstention over conversion.",
        "MMPDS-style allowables require regulated statistics: extracted values are pooling "
        "candidates only and must never be presented as design allowables.",
    ),
)

_PROFILES: dict[str, DomainProfile] = {
    p.domain: p for p in (AERODYNAMICS, RADAR, CONTROL, STRENGTH)
}


def get_domain_profile(domain: str) -> DomainProfile:
    if domain not in _PROFILES:
        raise ValueError(f"unknown domain {domain!r}; available: {', '.join(DOMAINS)}")
    return _PROFILES[domain]


def list_domains() -> tuple[str, ...]:
    return DOMAINS


def domain_prompt(domain: str) -> str:
    """Advisory prompt addition for one domain (plain text, safe to embed)."""
    return "\n".join(get_domain_profile(domain).prompt_lines())


def run_domain_checks(domain: str, record: Mapping[str, object]) -> list[str]:
    """Physical sanity problems for one candidate record (advisory, never approving)."""
    profile = get_domain_profile(domain)
    problems: list[str] = []
    for check in profile.checks:
        try:
            problem = check(record)
        except Exception:  # checks must never break the pipeline
            problem = None
        if problem:
            problems.append(problem)
    return problems


__all__ = [
    "DOMAIN_SCHEMA_VERSION",
    "DOMAINS",
    "DomainProfile",
    "AERODYNAMICS",
    "RADAR",
    "CONTROL",
    "STRENGTH",
    "get_domain_profile",
    "list_domains",
    "domain_prompt",
    "run_domain_checks",
]
