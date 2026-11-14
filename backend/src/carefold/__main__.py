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

"""Module CLI entrypoint (`python -m carefold --data-dir ...`)."""

from __future__ import annotations

from typing import Optional, Sequence

from carefold.data_dir import apply_data_dir, parse_cli_args


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_cli_args(argv)
    if args.data_dir:
        apply_data_dir(args.data_dir, set_cli_override=True)
    from carefold.main import run

    run(argv)


if __name__ == "__main__":
    main()
