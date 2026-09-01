"""Token-free demonstration corpus built from committed synthetic skills."""

from skillscope.demo.fixtures import (
    DEMO_GIT_COMMIT,
    DEMO_REPOSITORY_FULL_NAME,
    LocalFixtureClient,
    build_demo_manifest,
)

__all__ = [
    "DEMO_GIT_COMMIT",
    "DEMO_REPOSITORY_FULL_NAME",
    "LocalFixtureClient",
    "build_demo_manifest",
]
