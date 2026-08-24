"""Pure tests for deterministic ingestion persistence policy."""

import pytest

from skillscope.db.enums import LicenseStatus
from skillscope.ingestion.models import GitHubRepositoryPayload
from skillscope.ingestion.persistence import classify_repository_license


def _repository_payload(spdx_id: object = "MIT") -> GitHubRepositoryPayload:
    license_payload: object
    if spdx_id is _MISSING:
        license_payload = None
    else:
        license_payload = {
            "key": "fixture",
            "name": "Synthetic License",
            "spdx_id": spdx_id,
            "url": "https://api.github.com/licenses/fixture",
        }
    return GitHubRepositoryPayload.model_validate(
        {
            "id": 9001,
            "owner": {
                "login": "skillscope-tests",
                "id": 9002,
                "html_url": "https://github.com/skillscope-tests",
            },
            "name": "catalogue",
            "full_name": "skillscope-tests/catalogue",
            "private": False,
            "html_url": "https://github.com/skillscope-tests/catalogue",
            "default_branch": "main",
            "description": None,
            "stargazers_count": 0,
            "forks_count": 0,
            "open_issues_count": 0,
            "fork": False,
            "archived": False,
            "license": license_payload,
            "pushed_at": None,
        }
    )


_MISSING = object()


@pytest.mark.parametrize(
    ("spdx_id", "expected"),
    [
        ("MIT", LicenseStatus.PERMISSIVE),
        ("Apache-2.0", LicenseStatus.PERMISSIVE),
        ("GPL-3.0-only", LicenseStatus.RESTRICTIVE),
        ("NOASSERTION", LicenseStatus.UNKNOWN),
        (None, LicenseStatus.UNKNOWN),
        (_MISSING, LicenseStatus.MISSING),
    ],
)
def test_repository_license_policy_is_conservative(
    spdx_id: object,
    expected: LicenseStatus,
) -> None:
    assert classify_repository_license(_repository_payload(spdx_id)) is expected
