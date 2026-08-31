"""Unit coverage for fixed API evidence paths and the published evaluation summary."""

from pathlib import Path

import pytest

from skillscope.api.service import SkillScopeApiService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_latest_evaluation_exposes_only_canonical_aggregate_test_evidence() -> None:
    service = SkillScopeApiService(project_root=PROJECT_ROOT)

    response = service.latest_evaluation(request_id="a" * 32)
    payload = response.model_dump(mode="json")

    assert response.split == "test"
    assert response.dataset_snapshot.sha256 == (
        "d5f2c2ced677a468862edb25bbb8edea8b05ce63039916bbaeb02c7fb78c6562"
    )
    assert [method.method.value for method in response.methods] == [
        "bm25",
        "dense",
        "hybrid",
    ]
    assert response.methods[0].ndcg_at_10 == pytest.approx(0.8363377669222886)
    assert "queries" not in payload
    assert "failure_examples" not in payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bm25_config_path", "../bm25.json"),
        ("dense_config_path", "/tmp/dense.json"),
        ("evaluation_report_path", "reports/evaluation.txt"),
    ],
)
def test_service_rejects_paths_outside_its_fixed_project_root(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match="project-relative"):
        SkillScopeApiService(project_root=PROJECT_ROOT, **{field: value})
