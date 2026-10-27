"""Read-only, conservative document control checks for synthetic QMS records."""

from .assessment import assess_document, assess_document_register

__all__ = ["assess_document", "assess_document_register"]
