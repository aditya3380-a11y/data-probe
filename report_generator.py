"""Build clear summaries and exports for suspicious records."""
from html import escape
from io import BytesIO

import numpy as np


def explain_iqr(row, col_flags_row, bounds):
    """Human-readable reason, e.g. 'attendance_percent=120.0 outside [55.0, 98.5]'."""
    reasons = []
    for col in col_flags_row.index[col_flags_row]:
        low, high = bounds[col]
        reasons.append(f"{col}={row[col]} outside [{low:.1f}, {high:.1f}]")
    return "; ".join(reasons)


def build_suspect_table(df, feature_cols, iqr_flag, col_flags, bounds,
                        if_flag, if_score):
    """One row per record flagged by at least one detector."""
    flagged = iqr_flag | if_flag
    table = df.loc[flagged, feature_cols].copy()

    table["flagged_by"] = np.select(
        [iqr_flag[flagged] & if_flag[flagged], iqr_flag[flagged]],
        ["Both", "IQR only"],
        default="Isolation Forest only",
    )
    table["iqr_reason"] = [
        explain_iqr(df.loc[i], col_flags.loc[i], bounds) for i in table.index
    ]
    table["isolation_score"] = if_score[flagged].round(3)
    return table.sort_values("isolation_score", ascending=False)


def build_pdf_report(result):
    """Create a short, plain-language PDF report from analysis totals."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=letter, rightMargin=0.7 * inch,
        leftMargin=0.7 * inch, topMargin=0.65 * inch,
        bottomMargin=0.65 * inch, title="Data Probe data report",
        author="Data Probe",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], alignment=TA_LEFT,
        textColor=colors.HexColor("#34483e"), fontName="Helvetica-Bold",
        fontSize=25, leading=30, spaceAfter=7,
    ))
    styles.add(ParagraphStyle(
        name="ReportDeck", parent=styles["BodyText"],
        textColor=colors.HexColor("#686c6a"), fontSize=10,
        leading=15, spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        name="ReportHeading", parent=styles["Heading2"],
        textColor=colors.HexColor("#526f4d"), fontName="Helvetica-Bold",
        fontSize=14, leading=18, spaceBefore=13, spaceAfter=7,
    ))
    styles.add(ParagraphStyle(
        name="ReportBody", parent=styles["BodyText"],
        textColor=colors.HexColor("#434a46"), fontSize=9.5,
        leading=14, spaceAfter=7,
    ))
    styles.add(ParagraphStyle(
        name="ReportSmall", parent=styles["BodyText"],
        textColor=colors.HexColor("#747875"), fontSize=8,
        leading=11,
    ))

    def paragraph(text, style="ReportBody"):
        safe_text = str(text).encode("latin-1", "replace").decode("latin-1")
        return Paragraph(escape(safe_text), styles[style])

    def section_heading(text):
        return paragraph(text, "ReportHeading")

    def style_table(table, header_background, header_text, padding, specific=()):
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), header_background),
            ("TEXTCOLOR", (0, 0), (-1, 0), header_text),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            *specific,
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#faf8f3")]),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e5e5dd")),
            ("LEFTPADDING", (0, 0), (-1, -1), padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), padding),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))

    story = [
        paragraph("Data Probe", "ReportTitle"),
        paragraph("A clear summary of the patterns in your dataset", "ReportDeck"),
        paragraph(f"Dataset: {result['dataset_name']}"),
        paragraph(
            f"{result['rows']:,} rows · {result['columns']:,} columns · "
        f"{result['numeric_features']:,} numeric features",
        ),
        section_heading("The short version"),
        paragraph(
            f"The checks found {result['suspect_count']:,} rows flagged for "
            "review by at least one detector. This is a prompt to take a "
            "closer look, not proof that those records are wrong."
        ),
        section_heading("Data health"),
    ]

    health_rows = [
        ["Check", "Rows or columns"],
        ["Rows with at least one blank", f"{result['rows_with_missing']:,}"],
        ["Extra exact duplicate rows", f"{result['duplicates']:,}"],
        ["Rows outside a built-in range", f"{result['range_violations']:,}"],
        ["Numeric features analyzed", f"{result['numeric_features']:,}"],
    ]
    health_table = Table(health_rows, colWidths=[4.9 * inch, 1.5 * inch])
    style_table(
        health_table,
        colors.HexColor("#eaf0e3"),
        colors.HexColor("#455542"),
        9,
        [
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#434a46")),
        ],
    )
    story.extend([
        health_table,
        section_heading("What each detector found"),
    ])
    detector_rows = [
        ["Method", "Rows flagged", "In everyday terms"],
        ["IQR", f"{result['iqr_count']:,}",
         "Finds values far from the usual range in one column."],
        ["Isolation Forest", f"{result['if_count']:,}",
         "Finds rows with unusual combinations of values."],
        ["Both methods", f"{result['both_count']:,}",
         "Rows both methods independently flagged."],
    ]
    detector_table = Table(
        [[paragraph(cell, "ReportSmall") for cell in row]
         for row in detector_rows],
        colWidths=[1.35 * inch, 0.85 * inch, 4.2 * inch],
    )
    style_table(
        detector_table,
        colors.HexColor("#f5eadd"),
        colors.HexColor("#55483f"),
        7,
        [("VALIGN", (0, 0), (-1, -1), "TOP")],
    )
    story.extend([
        detector_table,
        section_heading("How to read this"),
        paragraph(
            "The IQR rule checks each numeric column separately. Isolation "
            "Forest looks across numeric columns for unusual combinations. "
            "A record can be unusual and still be valid, so review the "
            "original context before making a decision."
        ),
    ])
    if result["has_labels"]:
        story.append(paragraph(
            "This is the built-in practice dataset, which has planted labels. "
            "Its evaluation scores are shown in the app; they describe this "
            "designed example and are not a guarantee on new data."
        ))
    else:
        story.append(paragraph(
            "This dataset has no verified anomaly labels. The app does not "
            "report accuracy scores because there is no trusted answer key."
        ))
    story.append(Spacer(1, 8))
    story.append(paragraph(
        "Made with Data Probe · Results are screening clues, not a verdict.",
        "ReportSmall",
    ))
    document.build(story)
    return output.getvalue()
