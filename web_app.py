"""Local web interface for the Data Probe student-data explorer."""
from io import BytesIO
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import qrcode
import qrcode.image.svg
from flask import Flask, jsonify, render_template, request, send_file

from data_cleaning import VALID_RANGES, health_check
from data_generator import build_dataset
from evaluation import compare_detectors, make_truth
from ml_detector import detect_isolation_forest
from report_generator import build_pdf_report, build_suspect_table
from statistical_detector import detect_iqr

BASE_DIR = Path(__file__).resolve().parent
UCI_CSV = BASE_DIR / "datasets" / "student-mat.csv"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20_000
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = os.environ.get("DATAPROBE_OLLAMA_MODEL", "llama3.2")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


def _read_uploaded_csv(upload):
    """Parse a comma- or semicolon-separated CSV uploaded to the local app."""
    try:
        return pd.read_csv(upload, sep=None, engine="python")
    except (UnicodeDecodeError, pd.errors.EmptyDataError,
            pd.errors.ParserError, ValueError) as error:
        raise ValueError(f"Could not read this CSV: {error}") from error


def _analyze(df, dataset_name, k, contamination, has_known_labels=False):
    """Run the health check and both detectors and return browser-ready results."""
    if df.empty:
        raise ValueError("The selected CSV has no data rows.")
    if len(df) > MAX_ROWS:
        raise ValueError(f"CSV has {len(df):,} rows; the local demo limit is "
                         f"{MAX_ROWS:,}.")

    report = health_check(df)
    features = report["feature_cols"]
    if not features:
        raise ValueError("This dataset needs at least one numeric, "
                         "non-constant feature column.")

    iqr_flag, col_flags, bounds = detect_iqr(df, features, k=k)
    if_flag, if_score = detect_isolation_forest(
        df, features, contamination=contamination
    )
    suspects = build_suspect_table(
        df, features, iqr_flag, col_flags, bounds, if_flag, if_score
    )

    chart_frame = df[features].copy()
    chart_frame.insert(0, "row_index", df.index.astype(str))
    chart_frame["detector"] = "Not flagged"
    chart_frame.loc[iqr_flag & ~if_flag, "detector"] = "IQR only"
    chart_frame.loc[~iqr_flag & if_flag, "detector"] = "Isolation Forest only"
    chart_frame.loc[iqr_flag & if_flag, "detector"] = "Both"
    if len(chart_frame) > 1200:
        chart_frame = chart_frame.sample(n=1200, random_state=42).sort_index()
    chart_rows_shown = len(chart_frame)

    suspect_frame = (
        suspects.groupby("flagged_by", sort=False, group_keys=False)
        .head(100)
        .copy()
    )
    suspect_frame.insert(0, "row_index", suspect_frame.index.astype(str))
    missing_counts = {
        str(column): int(count)
        for column, count in report["missing_per_column"].items()
    }

    result = {
        "dataset_name": dataset_name,
        "rows": report["n_rows"],
        "columns": report["n_columns"],
        "features": features,
        "feature_ranges": {
            str(column): [float(df[column].min()), float(df[column].max())]
            for column in features if not df[column].dropna().empty
        },
        "rows_with_missing": report["rows_with_missing"],
        "duplicates": report["n_duplicates"],
        "range_violations": report["n_rule_violations"],
        "range_columns": report["rule_columns"],
        "range_limits": {
            column: list(VALID_RANGES[column])
            for column in report["rule_columns"]
        },
        "constant_columns": report["constant_columns"],
        "numbers_stored_as_text": report["numbers_stored_as_text"],
        "missing_per_column": missing_counts,
        "iqr_count": int(iqr_flag.sum()),
        "if_count": int(if_flag.sum()),
        "both_count": int((iqr_flag & if_flag).sum()),
        "suspect_count": len(suspects),
        "chart_rows": json.loads(chart_frame.to_json(orient="records")),
        "chart_rows_shown": chart_rows_shown,
        "chart_rows_sampled": chart_rows_shown < len(df),
        "suspects": json.loads(suspect_frame.to_json(orient="records")),
        "suspects_csv": suspects.to_csv(index=True, index_label="row_index"),
        "has_labels": bool(has_known_labels and "anomaly_type" in df.columns),
        "evaluation_target_count": (
            int(make_truth(df).sum())
            if has_known_labels and "anomaly_type" in df.columns else 0
        ),
    }
    if result["has_labels"]:
        result["evaluation"] = json.loads(
            compare_detectors(df, iqr_flag, if_flag).round(3).reset_index(
                names="detector"
            ).to_json(orient="records")
        )
    return result


def _analysis_from_request():
    """Load the selected dataset, validate settings, and run the detectors."""
    try:
        k = float(request.form.get("k", "1.5"))
        contamination = float(request.form.get("contamination", "0.05"))
    except ValueError as error:
        raise ValueError("k and contamination must be valid numbers.") from error

    if not math.isfinite(k) or k <= 0:
        raise ValueError("IQR multiplier k must be greater than zero.")
    if not math.isfinite(contamination) or not 0 < contamination <= 0.5:
        raise ValueError(
            "Contamination must be greater than zero and at most 0.5."
        )

    source = request.form.get("source", "synthetic")
    has_known_labels = False
    if source == "synthetic":
        df = build_dataset()
        dataset_name = "Synthetic student data"
        has_known_labels = True
    elif source == "uci":
        if not UCI_CSV.is_file():
            raise ValueError(f"UCI dataset is missing: {UCI_CSV.name}")
        try:
            df = pd.read_csv(UCI_CSV, sep=None, engine="python")
        except (UnicodeDecodeError, pd.errors.EmptyDataError,
                pd.errors.ParserError, ValueError) as error:
            app.logger.exception("Could not load the bundled UCI dataset")
            raise ValueError(f"Could not read UCI dataset: {error}") from error
        dataset_name = "UCI Student Performance · Mathematics"
    elif source == "upload":
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            raise ValueError("Choose a CSV file to upload.")
        df = _read_uploaded_csv(BytesIO(upload.read()))
        dataset_name = Path(upload.filename).name
    else:
        raise ValueError("Choose a supported dataset source.")

    return _analyze(df, dataset_name, k, contamination, has_known_labels)


def _ollama_request(path, payload=None, timeout=3):
    """Make a bounded request to the Ollama service on this computer."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_object = Request(
        f"{OLLAMA_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urlopen(request_object, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _validate_llm_summary(summary, require_evaluation=False):
    """Allow only aggregate counts through to the local language model."""
    count_fields = {
        "rows", "columns", "numeric_features", "rows_with_missing",
        "duplicates", "range_violations", "iqr_count", "if_count",
        "both_count", "suspect_count",
    }
    expected_fields = count_fields | {"has_labels"}
    if not isinstance(summary, dict) or set(summary) not in (
        expected_fields, expected_fields | {"evaluation"},
    ):
        raise ValueError("Only the supplied aggregate summary can be explained.")
    for field in count_fields:
        value = summary[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Summary counts must be non-negative whole numbers.")
    if summary["rows"] < 1 or summary["columns"] < 1:
        raise ValueError("The summary must describe a non-empty dataset.")
    if any(summary[field] > summary["rows"] for field in (
        "rows_with_missing", "duplicates", "range_violations", "iqr_count",
        "if_count", "both_count", "suspect_count",
    )):
        raise ValueError("Summary counts cannot exceed the number of rows.")
    if not isinstance(summary["has_labels"], bool):
        raise ValueError("The label indicator must be true or false.")
    if summary["numeric_features"] > summary["columns"]:
        raise ValueError("Numeric features cannot exceed the number of columns.")
    if summary["both_count"] > min(summary["iqr_count"], summary["if_count"]):
        raise ValueError("The overlap cannot exceed either detector's count.")
    if summary["suspect_count"] != (
        summary["iqr_count"] + summary["if_count"] - summary["both_count"]
    ):
        raise ValueError("Detector totals and overlap do not match the unique flag count.")
    if summary["has_labels"] and (
        require_evaluation or "evaluation" in summary
    ):
        evaluation = summary.get("evaluation")
        expected_detectors = {"IQR", "Isolation Forest", "Either (OR)", "Both (AND)"}
        metric_fields = {"detector", "precision", "recall", "f1", "TP", "FP", "FN"}
        if not isinstance(evaluation, list) or len(evaluation) != len(expected_detectors):
            raise ValueError("Labeled summaries need all four aggregate detector evaluations.")
        if {item.get("detector") for item in evaluation if isinstance(item, dict)} != expected_detectors:
            raise ValueError("Evaluation results must include each supported detector.")
        for item in evaluation:
            if not isinstance(item, dict) or set(item) != metric_fields:
                raise ValueError("Only aggregate detector evaluation metrics are allowed.")
            for field in ("precision", "recall", "f1"):
                value = item[field]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("Evaluation metrics must be numeric.")
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("Evaluation metrics must be between zero and one.")
            for field in ("TP", "FP", "FN"):
                value = item[field]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError("Evaluation counts must be non-negative whole numbers.")
                if value > summary["rows"]:
                    raise ValueError("Evaluation counts cannot exceed the number of rows.")
    elif "evaluation" in summary:
        raise ValueError("Unlabeled summaries cannot include evaluation scores.")
    return summary


def _validate_report_summary(summary):
    """Validate the small set of totals used to make the downloadable PDF."""
    expected_fields = {
        "dataset_name", "rows", "columns", "numeric_features",
        "rows_with_missing", "duplicates", "range_violations", "iqr_count",
        "if_count", "both_count", "suspect_count", "has_labels",
    }
    if not isinstance(summary, dict) or set(summary) != expected_fields:
        raise ValueError("The PDF needs a complete aggregate analysis summary.")
    dataset_name = summary["dataset_name"]
    if (
        not isinstance(dataset_name, str)
        or not dataset_name.strip()
        or len(dataset_name) > 120
        or any(ord(character) < 32 for character in dataset_name)
    ):
        raise ValueError("The report dataset name is invalid.")
    _validate_llm_summary({
        key: value for key, value in summary.items() if key != "dataset_name"
    })
    return summary


@app.get("/")
def index():
    """Serve the Data Probe dashboard."""
    return render_template("index.html")


@app.get("/profile-qr.svg")
def profile_qr():
    """Create an offline SVG QR code linking to the developer's GitHub."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=8,
        border=4,
        image_factory=qrcode.image.svg.SvgPathImage,
    )
    qr.add_data("https://github.com/aditya3380-a11y")
    qr.make(fit=True)
    image = qr.make_image(fill_color="#211a2d", back_color="#ffffff")
    output = BytesIO()
    image.save(output)
    output.seek(0)
    return send_file(output, mimetype="image/svg+xml", max_age=86400)


@app.post("/api/analyze")
def analyze():
    """Validate the selected input and return an analysis as JSON."""
    try:
        return jsonify(_analysis_from_request())
    except ValueError as error:
        return jsonify(error=str(error)), 400


@app.post("/api/report.pdf")
def download_report():
    """Create a self-contained PDF using only the supplied aggregate totals."""
    payload = request.get_json(silent=True)
    if payload is None and request.form.get("summary"):
        try:
            payload = json.loads(request.form["summary"])
        except json.JSONDecodeError as error:
            return jsonify(error="The PDF summary is not valid JSON."), 400
    try:
        result = _validate_report_summary(payload)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return send_file(
        BytesIO(build_pdf_report(result)),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="data_probe_report.pdf",
    )


@app.get("/api/llm-status")
def llm_status():
    """Report whether the configured local Ollama model is ready."""
    try:
        response = _ollama_request("/api/tags")
    except (HTTPError, URLError, TimeoutError):
        return jsonify(
            ready=False,
            model=OLLAMA_MODEL,
            message=(
                "Ollama is not running. Install it from ollama.com and open the "
                "Ollama app, then run `ollama pull "
                f"{OLLAMA_MODEL}` in a terminal."
            ),
        )
    except (json.JSONDecodeError, UnicodeDecodeError):
        app.logger.exception("Ollama returned an unreadable model list")
        return jsonify(error="Ollama returned an unreadable model list."), 502

    if not isinstance(response, dict) or not isinstance(response.get("models"), list):
        return jsonify(error="Ollama returned an unreadable model list."), 502
    models = {
        model["name"]
        for model in response.get("models", [])
        if isinstance(model, dict) and isinstance(model.get("name"), str)
    }
    if OLLAMA_MODEL not in models and f"{OLLAMA_MODEL}:latest" not in models:
        return jsonify(
            ready=False,
            model=OLLAMA_MODEL,
            message=f"Install the {OLLAMA_MODEL} model in Ollama to enable explanations.",
        )
    return jsonify(
        ready=True,
        model=OLLAMA_MODEL,
        message=f"{OLLAMA_MODEL} is ready on this computer.",
    )


@app.post("/api/explain")
def explain_results():
    """Ask the local language model to explain aggregate detector results."""
    try:
        summary = _validate_llm_summary(
            request.get_json(silent=True),
            require_evaluation=True,
        )
    except ValueError as error:
        return jsonify(error=str(error)), 400

    if summary["has_labels"]:
        evaluation_lines = "\n".join(
            f'{item["detector"]}: Precision {item["precision"]:.3f}, '
            f'Recall {item["recall"]:.3f}, F1 {item["f1"]:.3f}'
            for item in summary["evaluation"]
        )
        target_count = (
            summary["evaluation"][0]["TP"] + summary["evaluation"][0]["FN"]
        )
        instructions = (
            "Explain this labeled synthetic practice dataset in plain language. "
            "Start by saying its results are in-sample and not a held-out test. "
            "Then reproduce every detector name and every Precision, Recall, "
            "and F1 value from the VERIFIED SCORES section exactly. Explain "
            f"that these scores compare flags with {target_count} planted value "
            "anomalies. Do not say accuracy cannot be measured for this labeled "
            "practice set. Do not invent counts or claim performance on new data."
        )
    else:
        evaluation_lines = ""
        instructions = (
            "Explain these unlabeled data-quality results in plain language. "
            "Say that detector accuracy cannot be measured without trusted "
            "anomaly labels. Do not claim a flagged row is incorrect and do not "
            "invent facts or counts."
        )
    prompt = (
        "You explain data-analysis results to a student. Use only the supplied "
        "aggregate counts and verified metrics; no raw records are available. "
        "This is a brief explanation of totals, not a deep dataset analysis. "
        "Do not infer feature-level patterns, causes, or facts not present in "
        "the summary. The explanation may be incomplete; state limits clearly. "
        f"{instructions} Keep the answer under 140 words.\n"
        f"VERIFIED SCORES (copy exactly):\n{evaluation_lines}\n"
        f"Aggregate counts: {json.dumps(summary, sort_keys=True)}"
    )
    try:
        response = _ollama_request(
            "/api/generate",
            {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=300,
        )
    except HTTPError as error:
        app.logger.warning("Ollama rejected an explanation request: %s", error)
        return jsonify(error="Ollama could not generate an explanation."), 502
    except (URLError, TimeoutError):
        return jsonify(
            error="Could not reach local Ollama. Start Ollama and try again."
        ), 503
    except (json.JSONDecodeError, UnicodeDecodeError):
        app.logger.exception("Ollama returned an unreadable explanation")
        return jsonify(error="Ollama returned an unreadable explanation."), 502

    if not isinstance(response, dict):
        return jsonify(error="Ollama returned an unreadable explanation."), 502
    explanation = response.get("response")
    if not isinstance(explanation, str) or not explanation.strip():
        return jsonify(error="Ollama returned an empty explanation."), 502
    return jsonify(explanation=explanation.strip(), model=OLLAMA_MODEL)


@app.errorhandler(413)
def upload_too_large(_error):
    """Explain the upload-size limit in the dashboard's JSON format."""
    return jsonify(error="CSV upload is too large; the limit is 10 MB."), _error.code


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
