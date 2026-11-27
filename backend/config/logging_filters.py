from __future__ import annotations

import logging

from core.services.privacy import PIISanitizer


class SensitiveDataLogFilter(logging.Filter):
    """Redacts CPF, CNPJ, email addresses, and phone numbers from application logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = PIISanitizer.mask_text(record.msg).masked_text
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    PIISanitizer.mask_text(arg).masked_text if isinstance(arg, str) else arg
                    for arg in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    key: PIISanitizer.mask_text(val).masked_text if isinstance(val, str) else val
                    for key, val in record.args.items()
                }
        return True
