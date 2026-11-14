from pathlib import Path


SOURCE = Path(__file__).parents[2].joinpath("src", "collection", "detail_service.py")


def test_detail_service_uses_structured_logging_for_runtime_events() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in source
    assert 'logger.info("Saved HTML to %s", html_path)' in source
    location_source = SOURCE.with_name("detail_location.py").read_text(encoding="utf-8")
    assert (
        'logger.exception("Error calling LLM for location inference")'
        in location_source
    )
    assert "print(" not in location_source
    assert "print(" not in source
