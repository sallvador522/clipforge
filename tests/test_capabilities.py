"""Capability registry integrity and honesty tests (Milestone 6B-PREP)."""

from __future__ import annotations

import pytest

from clipforge_contracts.capabilities import (
    CAPABILITIES,
    CapabilityStatus,
    capability_summary_for_prompt,
    disabled_capability_ids,
    executable_capabilities,
    get_capability,
)


def test_all_five_statuses_are_supported():
    assert {status.value for status in CapabilityStatus} == {
        "available_mock",
        "available_local",
        "available_live",
        "planned",
        "disabled",
    }


def test_only_expected_capabilities_are_executable():
    executable = {capability.capability_id for capability in executable_capabilities()}
    assert executable == {
        "subject.isolate",
        "background.blur",
        "background.replace",
        "audio.preserve",
        "video.render_mp4",
        "output.verify",
    }


def test_mock_segmentation_is_labelled_and_not_sam():
    isolate = get_capability("subject.isolate")
    assert isolate is not None
    assert isolate.status is CapabilityStatus.AVAILABLE_MOCK
    assert isolate.simulated is True
    assert "not sam" in isolate.description.lower()
    assert isolate.required_provider == "segmentation"


def test_local_capabilities_are_not_live_ai():
    for capability_id in ("background.blur", "audio.preserve", "video.render_mp4", "output.verify"):
        capability = get_capability(capability_id)
        assert capability is not None
        assert capability.status is CapabilityStatus.AVAILABLE_LOCAL
        assert capability.status is not CapabilityStatus.AVAILABLE_LIVE


def test_background_replacement_uses_local_assets_not_muse_image():
    replace = get_capability("background.replace")
    assert replace is not None
    assert replace.status is CapabilityStatus.AVAILABLE_LOCAL
    assert "not Muse Image" in replace.description
    assert replace.requires_approval is True
    planned_generation = get_capability("background.generate")
    assert planned_generation is not None
    assert planned_generation.status is CapabilityStatus.PLANNED


def test_disabled_capabilities_have_no_handler_and_are_never_executable():
    disabled = disabled_capability_ids()
    assert "transition.apply" in disabled
    assert "keyframe.animate" in disabled
    for capability_id in disabled:
        capability = CAPABILITIES[capability_id]
        assert capability.backend_handler is None
        assert capability.executable is False


def test_prompt_summary_marks_status_and_simulation():
    summary = capability_summary_for_prompt()
    assert "subject.isolate [ENABLED (simulated)]" in summary
    assert "transition.apply [DISABLED]" in summary
    assert "background.generate [PLANNED]" in summary


def test_registry_rejects_unknown_dependency():
    from clipforge_contracts.capabilities import Capability, _validate_registry
    import clipforge_contracts.capabilities as capabilities_module

    bad = Capability(
        capability_id="test.bad",
        name="Bad",
        description="Bad",
        input_schema="X",
        output_schema="Y",
        backend_handler="x:y",
        dependencies=("does.not_exist",),
        status=CapabilityStatus.AVAILABLE_LOCAL,
        verification="none",
    )
    original = dict(capabilities_module.CAPABILITIES)
    capabilities_module.CAPABILITIES["test.bad"] = bad
    try:
        with pytest.raises(ValueError):
            _validate_registry()
    finally:
        capabilities_module.CAPABILITIES.clear()
        capabilities_module.CAPABILITIES.update(original)
