# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Backward-compatibility re-export shim for yarvelle_core.platform.email_drafts."""

import yarvelle_core.platform.email_drafts as _yc_email_drafts

_yc_email_drafts.NO_AUTO_SEND_NOTICE = (
    "Draft saved locally. Carefold never sends emails automatically in v1."
)
_yc_email_drafts.AUTOMATED_DRAFT_EMAIL_HEADER_NOTE = (
    "Prepared locally by Carefold as an administrative aid. "
    "Review and verify all details before sending."
)

from yarvelle_core.platform.email_drafts import *  # noqa: E402, F401, F403
from yarvelle_core.platform.email_drafts import (  # noqa: E402
    AUTOMATED_DRAFT_EMAIL_HEADER_NOTE,
    AUTOMATED_DRAFT_EMAIL_HEADER_NOTE as NON_CLINICAL_EMAIL_HEADER_NOTE,
    NO_AUTO_SEND_NOTICE,
    VALID_DRAFT_CATEGORIES,
    build_mailto_uri,
    create_email_draft,
    delete_email_draft,
    execute_create_email_draft,
    export_draft_as_eml,
    get_email_draft,
    list_email_drafts,
    serialize_email_draft,
)
