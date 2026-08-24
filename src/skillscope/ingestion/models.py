"""Typed payload models for the read-only GitHub REST API surface."""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from skillscope.ingestion.validation import (
    validate_git_object_sha,
    validate_git_ref,
    validate_github_api_url,
    validate_github_html_url,
    validate_owner,
    validate_relative_path,
    validate_repository_full_name,
    validate_repository_name,
)

type GitHubLogin = Annotated[str, AfterValidator(validate_owner)]
type GitHubRepositoryName = Annotated[str, AfterValidator(validate_repository_name)]
type GitHubRepositoryFullName = Annotated[str, AfterValidator(validate_repository_full_name)]
type GitHubRelativePath = Annotated[str, AfterValidator(validate_relative_path)]
type GitHubGitRef = Annotated[str, AfterValidator(validate_git_ref)]
type GitObjectSha = Annotated[str, AfterValidator(validate_git_object_sha)]
type GitHubApiUrl = Annotated[str, AfterValidator(validate_github_api_url)]
type GitHubHtmlUrl = Annotated[str, AfterValidator(validate_github_html_url)]


class GitHubPayload(BaseModel):
    """Base model that ignores unrelated API fields and prevents mutation."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class GitHubOwnerPayload(GitHubPayload):
    """Repository-owner fields retained from GitHub responses."""

    login: GitHubLogin
    id: int = Field(gt=0)
    html_url: GitHubHtmlUrl


class GitHubRepositorySummaryPayload(GitHubPayload):
    """Repository fields embedded in a code-search item."""

    id: int = Field(gt=0)
    name: GitHubRepositoryName
    full_name: GitHubRepositoryFullName
    owner: GitHubOwnerPayload
    private: bool
    html_url: GitHubHtmlUrl

    @model_validator(mode="after")
    def validate_consistent_names(self) -> Self:
        expected = f"{self.owner.login}/{self.name}"
        if self.full_name.casefold() != expected.casefold():
            raise ValueError("repository full_name does not match owner and name")
        return self


class GitHubCodeSearchItemPayload(GitHubPayload):
    """One file returned by GitHub code search."""

    name: str = Field(min_length=1)
    path: GitHubRelativePath
    sha: GitObjectSha
    url: GitHubApiUrl
    git_url: GitHubApiUrl
    html_url: GitHubHtmlUrl
    repository: GitHubRepositorySummaryPayload


class GitHubCodeSearchResponsePayload(GitHubPayload):
    """A decoded page from ``GET /search/code``."""

    total_count: int = Field(ge=0)
    incomplete_results: bool
    items: tuple[GitHubCodeSearchItemPayload, ...]


class GitHubLicensePayload(GitHubPayload):
    """Nullable repository licence metadata reported by GitHub."""

    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    spdx_id: str | None = None
    url: GitHubApiUrl | None = None


class GitHubRepositoryPayload(GitHubPayload):
    """Repository metadata required by the SkillScope persistence model."""

    id: int = Field(gt=0)
    owner: GitHubOwnerPayload
    name: GitHubRepositoryName
    full_name: GitHubRepositoryFullName
    private: bool
    html_url: GitHubHtmlUrl
    default_branch: GitHubGitRef
    description: str | None = None
    stargazers_count: int = Field(ge=0)
    forks_count: int = Field(ge=0)
    open_issues_count: int = Field(ge=0)
    fork: bool
    archived: bool
    license: GitHubLicensePayload | None = None
    pushed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_consistent_names(self) -> Self:
        expected = f"{self.owner.login}/{self.name}"
        if self.full_name.casefold() != expected.casefold():
            raise ValueError("repository full_name does not match owner and name")
        return self


class GitHubFilePayload(GitHubPayload):
    """A file returned by the repository contents endpoint."""

    type: Literal["file"]
    name: str = Field(min_length=1)
    path: GitHubRelativePath
    sha: GitObjectSha
    size: int = Field(ge=0)
    encoding: Literal["base64", "none"]
    content: str | None = None
    url: GitHubApiUrl
    git_url: GitHubApiUrl | None = None
    html_url: GitHubHtmlUrl | None = None

    @model_validator(mode="after")
    def validate_name_matches_path(self) -> Self:
        if self.path.rsplit("/", maxsplit=1)[-1] != self.name:
            raise ValueError("file name does not match the final path component")
        return self

    def decode_content(self) -> bytes:
        """Decode GitHub's line-wrapped Base64 representation strictly."""
        if self.encoding != "base64" or self.content is None:
            raise ValueError("file content is not available as Base64")
        try:
            encoded = self.content.encode("ascii")
            compact = b"".join(encoded.splitlines())
            return base64.b64decode(compact, validate=True)
        except (binascii.Error, UnicodeEncodeError) as error:
            raise ValueError("file content is not valid Base64") from error


class GitHubDirectoryEntryPayload(GitHubPayload):
    """Structural metadata for one repository directory entry."""

    type: Literal["file", "dir", "symlink", "submodule"]
    name: str = Field(min_length=1)
    path: GitHubRelativePath
    sha: GitObjectSha
    size: int = Field(ge=0)
    url: GitHubApiUrl
    git_url: GitHubApiUrl | None = None
    html_url: GitHubHtmlUrl | None = None

    @model_validator(mode="after")
    def validate_name_matches_path(self) -> Self:
        if self.path.rsplit("/", maxsplit=1)[-1] != self.name:
            raise ValueError("directory entry name does not match its path")
        return self


class GitHubRateLimitBucketPayload(GitHubPayload):
    """One primary GitHub rate-limit resource bucket."""

    limit: int = Field(ge=0)
    used: int = Field(ge=0)
    remaining: int = Field(ge=0)
    reset: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.used > self.limit or self.remaining > self.limit:
            raise ValueError("rate-limit counts cannot exceed the limit")
        return self

    @property
    def reset_at(self) -> datetime:
        """Return the reset timestamp as an aware UTC datetime."""
        return datetime.fromtimestamp(self.reset, tz=UTC)


class GitHubRateLimitResourcesPayload(GitHubPayload):
    """Rate buckets used by SkillScope's read-only endpoints."""

    core: GitHubRateLimitBucketPayload
    search: GitHubRateLimitBucketPayload
    code_search: GitHubRateLimitBucketPayload


class GitHubRateLimitResponsePayload(GitHubPayload):
    """Response from ``GET /rate_limit``."""

    resources: GitHubRateLimitResourcesPayload
