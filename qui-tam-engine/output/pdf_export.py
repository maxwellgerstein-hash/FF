"""
PDF Export for case memos.
Phase 5: Will use weasyprint. For Phase 1, this is a placeholder.
"""


def export_case_memo_pdf(case_docket_entry: dict, output_path: str) -> str:
    """
    Export a case docket entry as a PDF memo.
    Phase 1: Returns a placeholder message.
    Phase 5: Will use weasyprint to generate attorney-ready PDF.
    """
    # TODO: Phase 5 — implement with weasyprint
    return f"PDF export not yet available. Case ID: {case_docket_entry.get('case_id')}"
