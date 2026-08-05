
from __future__ import annotations

from app.services.safe_remote_fetch import RemoteFetchError as RemoteFetchError
from app.services.safe_remote_fetch import fetch_remote_file as fetch_remote_file
from app.services.smb_gateway import NetworkPathError as NetworkPathError
from app.services.smb_gateway import read_network_file as read_network_file
from app.services.smb_gateway import resolve_network_path as resolve_network_path

from .acquisition import acquire_local_upload as acquire_local_upload
from .acquisition import acquire_network_path as acquire_network_path
from .acquisition import acquire_url as acquire_url
from .finalize_document import finalize_document_import as finalize_document_import
from .finalize_tabular import FinalizeOptions as FinalizeOptions
from .finalize_tabular import _persist_ai_metadata as _persist_ai_metadata
from .finalize_tabular import finalize_tabular_import as finalize_tabular_import
from .jobs import apply_provenance as apply_provenance
from .jobs import cleanup_expired_jobs as cleanup_expired_jobs
from .jobs import get_job_for_user as get_job_for_user
from .preview import build_preview_payload as build_preview_payload
from .preview import profile_staged_file as profile_staged_file
from .staging import FileImportError as FileImportError
from .staging import SafeProvenance as SafeProvenance
from .staging import StagedFile as StagedFile
from .staging import _new_job as _new_job
from .staging import _stage as _stage
from .staging import _write_quarantine as _write_quarantine
from .staging import discard_quarantine as discard_quarantine
from .staging import logger as logger
from .staging import quarantine_dir as quarantine_dir
from .staging import read_staged_bytes as read_staged_bytes

"""Canonical file-ingestion service shared by all three acquisition methods.

Local upload, HTTPS URL, and UNC/SMB network path differ only in how bytes
arrive. They converge here on one :class:`StagedFile` contract and then follow
the pre-existing destination pipelines unchanged: tabular files profile into
Teiid + ``FileSourceMeta`` + a saved query, documents go to Project Assets.

The staged bytes live in tenant-scoped quarantine on disk and the job state
lives in Postgres, so an import survives an API restart and is not bound to
one Python process the way the old in-memory upload-session dict was.
"""
