const elements = {
  runButton: document.querySelector("#run-button"),
  status: document.querySelector("#status-text"),
  statusDot: document.querySelector(".status-dot"),
  error: document.querySelector("#error-banner"),
  empty: document.querySelector("#empty-state"),
  report: document.querySelector("#report"),
  uploadZone: document.querySelector("#upload-zone"),
  file: document.querySelector("#csv-file"),
  fileName: document.querySelector("#file-name"),
  k: document.querySelector("#k-slider"),
  kValue: document.querySelector("#k-value"),
  contamination: document.querySelector("#contamination-slider"),
  contaminationValue: document.querySelector("#contamination-value"),
  xFeature: document.querySelector("#x-feature"),
  yFeature: document.querySelector("#y-feature"),
  zFeature: document.querySelector("#z-feature"),
  connectionCount: document.querySelector("#connection-count"),
  connectionCountValue: document.querySelector("#connection-count-value"),
  showConnections: document.querySelector("#show-connections"),
  chart: document.querySelector("#scatter-chart"),
  chartTooltip: document.querySelector("#chart-tooltip"),
  chartEmpty: document.querySelector("#chart-empty"),
  rowSearch: document.querySelector("#row-search"),
  aiStatus: document.querySelector("#llm-status"),
  aiCheckButton: document.querySelector("#llm-check-button"),
  aiButton: document.querySelector("#ai-explain-button"),
  aiExplanation: document.querySelector("#ai-explanation"),
  aiError: document.querySelector("#ai-error"),
  pdfButton: document.querySelector("#download-pdf-button"),
};

let latestResult = null;
let chartRows = [];
let suspectColumns = [];
let selectedFilter = "All";
let currentTablePage = 1;
let tableSortKey = "row_index";
let tableSortDirection = "asc";
let selectedScoreMetric = "f1";
let selectedScoreDetector = "Isolation Forest";
let changedSettings = false;
let drawnPoints = [];
let chartConnections = [];
let chartRotation = { yaw: -0.58, pitch: 0.42 };
let chartDrag = null;
let analysisRequestId = 0;
let activePage = ["map", "records", "report", "guide", "about"].includes(location.hash.slice(1))
  ? location.hash.slice(1) : "overview";

function showPage(page, updateUrl = true) {
  const allowedPages = ["overview", "map", "records", "report", "guide", "about"];
  activePage = allowedPages.includes(page) ? page : "overview";
  document.querySelectorAll(".nav-link").forEach((button) => {
    if (button.dataset.page === activePage) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
  document.querySelectorAll("[data-page-panel]").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.pagePanel !== activePage);
  });

  const isInformationPage = ["guide", "about"].includes(activePage);
  elements.report.classList.toggle("hidden", isInformationPage || !latestResult);
  elements.empty.classList.toggle("hidden", isInformationPage || Boolean(latestResult));
  document.querySelector(".workspace").classList.toggle("hidden", activePage === "about");
  if (activePage === "map" && latestResult) requestAnimationFrame(drawChart);
  if (updateUrl) {
    history.pushState(
      null,
      "",
      activePage === "overview" ? location.pathname : `#${activePage}`,
    );
  }
}

function selectedSource() {
  return document.querySelector('input[name="source"]:checked').value;
}

function updateSource() {
  document.querySelectorAll(".dataset-option").forEach((option) => {
    const selected = option.dataset.sourceOption === selectedSource();
    option.classList.toggle("selected", selected);
  });
  elements.uploadZone.classList.toggle("hidden", selectedSource() !== "upload");
  elements.error.classList.add("hidden");
  if (selectedSource() === "upload") {
    markSettingsChanged();
    if (elements.file.files.length) {
      runInvestigation();
    } else {
      analysisRequestId += 1;
      latestResult = null;
      chartRows = [];
      elements.report.classList.add("hidden");
      elements.empty.classList.remove("hidden");
      elements.empty.querySelector("h3").textContent = "Choose a CSV to get started";
      elements.empty.querySelector("p").textContent =
        "Pick a comma- or semicolon-separated CSV. It will be analyzed on this computer.";
      elements.status.textContent = "Waiting for your CSV";
      elements.runButton.querySelector("span:first-child").textContent = "Choose a CSV file";
      elements.runButton.disabled = true;
      showPage(activePage, false);
    }
    return;
  }
  elements.runButton.disabled = false;
  if (latestResult) runInvestigation();
}

function setBusy(isBusy) {
  elements.runButton.disabled = isBusy;
  elements.runButton.querySelector("span:first-child").textContent =
    isBusy ? "Investigating…" : changedSettings ? "Update results" : latestResult ? "Run again" : "Run investigation";
  if (isBusy) elements.status.textContent = "Analyzing your data…";
  elements.statusDot.classList.toggle("busy", isBusy);
}

function markSettingsChanged() {
  if (!latestResult) return;
  changedSettings = true;
  elements.runButton.querySelector("span:first-child").textContent = "Update results";
  elements.status.textContent = "Settings changed · update to refresh";
}

function addCell(row, value, tag = "td") {
  const cell = document.createElement(tag);
  cell.textContent = value == null ? "—" : String(value);
  row.append(cell);
  return cell;
}

function formatFeatureName(feature) {
  return feature.replace(/_/g, " ").replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

function renderAxisRanges(result) {
  const rangeContainer = document.querySelector("#axis-ranges");
  rangeContainer.replaceChildren();
  [
    ["X", elements.xFeature.value, "#7654c8"],
    ["Y", elements.yFeature.value, "#ff642d"],
    ["Z", elements.zFeature.value, "#288b98"],
  ].forEach(([axis, feature, color]) => {
    const [minimum, maximum] = result.feature_ranges[feature] || [0, 0];
    const range = document.createElement("div");
    range.className = "axis-range";
    range.style.setProperty("--axis-color", color);
    const title = document.createElement("strong");
    title.textContent = `${axis} · ${formatFeatureName(feature)}`;
    const values = document.createElement("span");
    const format = (value) => new Intl.NumberFormat(undefined, {
      maximumSignificantDigits: 5,
    }).format(value);
    values.textContent = `${format(minimum)}  →  ${format(maximum)}`;
    range.append(title, values);
    rangeContainer.append(range);
  });
}

function buildChartConnections() {
  chartConnections = [];
  if (!latestResult || !elements.xFeature.value ||
      !elements.yFeature.value || !elements.zFeature.value) return;

  const keys = [elements.xFeature.value, elements.yFeature.value, elements.zFeature.value];
  const points = chartRows.map((row, chartIndex) => {
    const coordinates = keys.map((key) => row[key] == null ? Number.NaN : Number(row[key]));
    if (!coordinates.every(Number.isFinite)) return null;
    return {
      chartIndex,
      coordinates: coordinates.map((value, axis) => {
        const [minimum, maximum] = latestResult.feature_ranges[keys[axis]] || [0, 0];
        return maximum === minimum ? 0 : (value - minimum) / (maximum - minimum);
      }),
    };
  }).filter(Boolean);
  const neighborCount = Number(elements.connectionCount.value);
  const pairs = new Set();

  points.forEach((point, index) => {
    const nearest = [];
    points.forEach((candidate, candidateIndex) => {
      if (candidateIndex === index) return;
      const distance = point.coordinates.reduce((sum, value, axis) => {
        const difference = value - candidate.coordinates[axis];
        return sum + difference * difference;
      }, 0);
      if (nearest.length === neighborCount && distance >= nearest[nearest.length - 1].distance) return;
      nearest.push({ index: candidateIndex, distance });
      nearest.sort((left, right) => left.distance - right.distance);
      if (nearest.length > neighborCount) nearest.pop();
    });
    nearest.forEach(({ index: neighborIndex }) => {
      const first = Math.min(index, neighborIndex);
      const second = Math.max(index, neighborIndex);
      pairs.add(`${first}:${second}`);
    });
  });

  chartConnections = [...pairs].map((pair) => {
    const [first, second] = pair.split(":").map(Number);
    return [points[first].chartIndex, points[second].chartIndex];
  });
}

function populateSelect(select, options, chosen) {
  select.replaceChildren();
  options.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = formatFeatureName(value);
    option.selected = value === chosen;
    select.append(option);
  });
}

function renderTable(head, body, columns, rows, badgeColumn = null) {
  const headRow = document.createElement("tr");
  columns.forEach((column) => addCell(headRow, column.label, "th"));
  head.replaceChildren(headRow);
  body.replaceChildren();

  rows.forEach((item) => {
    const row = document.createElement("tr");
    columns.forEach((column) => {
      const cell = addCell(row, item[column.key]);
      if (cell.tagName === "TH") cell.scope = "col";
      if (column.key === badgeColumn) {
        const badge = document.createElement("span");
        badge.className = "flag-pill";
        badge.textContent = item[column.key] ?? "Unknown";
        cell.replaceChildren(badge);
      }
    });
    body.append(row);
  });
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderEvaluation(result) {
  const card = document.querySelector("#evaluation-card");
  const unlabeled = document.querySelector("#unlabeled-note");
  const preview = document.querySelector("#evaluation-preview");
  if (!result.has_labels) {
    card.classList.add("hidden");
    unlabeled.classList.remove("hidden");
    preview.classList.add("hidden");
    return;
  }
  unlabeled.classList.add("hidden");
  card.classList.remove("hidden");
  preview.classList.remove("hidden");
  const metricNames = ["precision", "recall", "f1"];
  const columns = [
    { key: "detector", label: "Detector" },
    ...metricNames.map((name) => ({ key: name, label: formatFeatureName(name) })),
    { key: "TP", label: "Found" },
    { key: "FP", label: "False alarms" },
    { key: "FN", label: "Missed" },
  ];
  const rows = result.evaluation.map((item) => ({
    ...item,
    precision: Number(item.precision).toFixed(2),
    recall: Number(item.recall).toFixed(2),
    f1: Number(item.f1).toFixed(2),
  }));
  selectedScoreMetric = "f1";
  selectedScoreDetector = result.evaluation.some((item) => item.detector === "Isolation Forest")
    ? "Isolation Forest" : result.evaluation[0].detector;
  document.querySelectorAll(".score-tab").forEach((tab) => {
    const active = tab.dataset.scoreMetric === selectedScoreMetric;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-pressed", String(active));
  });
  renderScoreExplorer(result.evaluation);
  document.querySelector("#evaluation-note").textContent =
    `The practice dataset has ${result.evaluation_target_count.toLocaleString()} planted value anomalies. Missing-value and duplicate cases are handled by the data checks, not counted as detector targets. These in-sample scores are a learning check, not a held-out test.`;
  renderTable(
    document.querySelector("#evaluation-head"),
    document.querySelector("#evaluation-body"),
    columns,
    rows,
  );
  renderTable(
    document.querySelector("#evaluation-preview-head"),
    document.querySelector("#evaluation-preview-body"),
    [
      { key: "detector", label: "Detector" },
      ...metricNames.map((name) => ({ key: name, label: formatFeatureName(name) })),
    ],
    rows,
  );
}

function renderScoreExplorer(evaluation) {
  const metricNames = {
    precision: "Precision",
    recall: "Recall",
    f1: "F1 score",
  };
  const metric = selectedScoreMetric;
  const bars = document.querySelector("#score-bars");
  bars.replaceChildren();
  document.querySelector("#score-metric-title").textContent = metricNames[metric];

  evaluation.forEach((item) => {
    const value = Number(item[metric]);
    const button = document.createElement("button");
    button.className = "score-bar-row";
    button.type = "button";
    button.setAttribute("aria-pressed", String(item.detector === selectedScoreDetector));
    button.setAttribute("aria-label", `${item.detector}: ${metricNames[metric]} ${(value * 100).toFixed(1)} percent`);
    const label = document.createElement("span");
    label.className = "score-bar-label";
    label.textContent = item.detector;
    const track = document.createElement("span");
    track.className = "score-bar-track";
    const fill = document.createElement("span");
    fill.className = "score-bar-fill";
    fill.style.width = `${Math.max(0, Math.min(100, value * 100))}%`;
    track.append(fill);
    const score = document.createElement("strong");
    score.className = "score-bar-value";
    score.textContent = `${(value * 100).toFixed(1)}%`;
    button.append(label, track, score);
    button.addEventListener("click", () => {
      selectedScoreDetector = item.detector;
      renderScoreExplorer(evaluation);
    });
    bars.append(button);
  });

  const selected = evaluation.find((item) => item.detector === selectedScoreDetector);
  const detail = document.querySelector("#score-detail");
  detail.replaceChildren();
  if (!selected) return;
  const heading = document.createElement("strong");
  heading.textContent = `${selected.detector} · ${metricNames[metric]} ${(Number(selected[metric]) * 100).toFixed(1)}%`;
  const counts = document.createElement("span");
  counts.textContent =
    `${Number(selected.TP).toLocaleString()} found · ${Number(selected.FP).toLocaleString()} false alarms · ${Number(selected.FN).toLocaleString()} missed`;
  detail.append(heading, counts);
}

function renderResult(result) {
  latestResult = result;
  changedSettings = false;
  chartRows = result.chart_rows;
  elements.report.classList.remove("hidden");
  elements.empty.classList.add("hidden");
  elements.error.classList.add("hidden");
  elements.status.textContent = "Investigation complete";

  document.querySelector("#dataset-name").textContent = result.dataset_name;
  document.querySelector("#dataset-size").textContent =
    `${result.rows.toLocaleString()} rows · ${result.columns} columns · ${result.features.length} numeric features`;
  const labelTag = document.querySelector("#label-tag");
  labelTag.textContent = result.has_labels ? "DEMO LABELS" : "NOT SCORED";
  labelTag.classList.toggle("unlabeled", !result.has_labels);
  document.querySelector("#missing-metric").textContent =
    result.rows_with_missing.toLocaleString();
  document.querySelector("#duplicate-metric").textContent =
    result.duplicates.toLocaleString();
  document.querySelector("#range-metric").textContent =
    result.range_violations.toLocaleString();
  document.querySelector("#suspect-metric").textContent =
    result.suspect_count.toLocaleString();
  renderHealthDetails(result);
  document.querySelector("#iqr-count").textContent = result.iqr_count.toLocaleString();
  document.querySelector("#if-count").textContent = result.if_count.toLocaleString();
  document.querySelector("#both-count").textContent = result.both_count.toLocaleString();
  document.querySelector("#detector-caption").textContent =
    `IQR k=${Number(elements.k.value).toFixed(1)} · Isolation Forest ${Math.round(Number(elements.contamination.value) * 100)}%`;

  const firstFeature = result.features.includes("study_hours_per_day")
    ? "study_hours_per_day" : result.features[0];
  const secondFeature = result.features.includes("exam_score") && firstFeature !== "exam_score"
    ? "exam_score" : result.features.find((feature) => feature !== firstFeature);
  const thirdFeature = result.features.includes("attendance_percent") &&
    ![firstFeature, secondFeature].includes("attendance_percent")
    ? "attendance_percent"
    : result.features.find((feature) => ![firstFeature, secondFeature].includes(feature));
  [elements.xFeature, elements.yFeature, elements.zFeature].forEach((select) => {
    populateSelect(select, result.features, result.features.length >= 3 ? undefined : result.features[0]);
  });
  elements.xFeature.value = firstFeature || "";
  elements.yFeature.value = secondFeature || "";
  elements.zFeature.value = thirdFeature || "";
  [elements.xFeature, elements.yFeature, elements.zFeature].forEach((select) => {
    select.disabled = result.features.length < 3;
  });
  elements.chart.classList.toggle("hidden", result.features.length < 3);
  elements.chartEmpty.classList.toggle("hidden", result.features.length >= 3);
  document.querySelector("#chart-controls").classList.toggle("hidden", result.features.length < 3);
  document.querySelector("#network-controls").classList.toggle("hidden", result.features.length < 3);
  document.querySelector("#chart-legend").classList.toggle("hidden", result.features.length < 3);
  if (result.features.length < 3) {
    elements.chartEmpty.textContent =
      `This dataset has ${result.features.length} numeric feature${result.features.length === 1 ? "" : "s"}. A 3D chart needs at least three; the detectors still analyze the available columns.`;
  }
  elements.connectionCountValue.value = `${elements.connectionCount.value} nearest`;
  buildChartConnections();
  renderAxisRanges(result);
  chartRotation = { yaw: -0.58, pitch: 0.42 };
  drawChart();
  document.querySelector("#chart-note").textContent = result.features.length < 3
    ? "Choose a dataset with three or more numeric columns to explore it in 3D."
    : result.chart_rows_sampled
      ? `Chart shows a random sample of ${result.chart_rows_shown.toLocaleString()} of ${result.rows.toLocaleString()} rows. Counts above use every row.`
      : `Each point is a row from this dataset. Nearby points are connected across the selected X, Y, and Z values.`;

  suspectColumns = [
    { key: "row_index", label: "Row" },
    ...result.features.slice(0, 5).map((feature) => ({ key: feature, label: formatFeatureName(feature) })),
    { key: "flagged_by", label: "Flagged by" },
    { key: "isolation_score", label: "Forest score" },
  ];
  selectedFilter = "All";
  currentTablePage = 1;
  tableSortKey = "row_index";
  tableSortDirection = "asc";
  elements.rowSearch.value = "";
  const tableSort = document.querySelector("#table-sort");
  tableSort.replaceChildren();
  suspectColumns.forEach((column) => {
    const option = document.createElement("option");
    option.value = column.key;
    option.textContent = column.label;
    tableSort.append(option);
  });
  tableSort.value = tableSortKey;
  document.querySelector("#table-sort-order").textContent = "↑";
  document.querySelector("#table-sort-order").setAttribute("aria-label", "Sort ascending");
  document.querySelector("#table-sort-order").title = "Sort ascending";
  document.querySelectorAll(".filter-chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.filter === selectedFilter);
  });
  document.querySelector("#filter-all-count").textContent = result.suspect_count.toLocaleString();
  document.querySelector("#filter-both-count").textContent = result.both_count.toLocaleString();
  document.querySelector('[data-filter="IQR only"]').lastElementChild.textContent =
    Math.max(0, result.iqr_count - result.both_count).toLocaleString();
  document.querySelector('[data-filter="Isolation Forest only"]').lastElementChild.textContent =
    Math.max(0, result.if_count - result.both_count).toLocaleString();
  renderSuspects();

  const rangeColumns = result.range_columns.length
    ? "The built-in student-data limits are rough checks, not universal rules. Confirm that they make sense for your data."
    : "No built-in student-data limits matched this dataset’s columns.";
  document.querySelector("#range-note").textContent =
    rangeColumns;
  document.querySelector("#report-summary").textContent =
    `Across ${result.rows.toLocaleString()} rows, IQR flagged ${result.iqr_count.toLocaleString()} and Isolation Forest flagged ${result.if_count.toLocaleString()}; ${result.both_count.toLocaleString()} were flagged by both. In total, ${result.suspect_count.toLocaleString()} distinct row${result.suspect_count === 1 ? "" : "s"} may be worth a closer look. ` +
    (result.has_labels
      ? "This practice dataset has labels, so the evaluation below compares the flags with its planted examples."
      : "This dataset has no verified anomaly labels, so no accuracy score is reported.");
  renderEvaluation(result);
  showPage(activePage, false);
}

function renderHealthDetails(result) {
  const content = document.querySelector("#health-details-content");
  const details = [];
  const columnsWithMissing = Object.entries(result.missing_per_column)
    .filter(([, count]) => count > 0)
    .map(([column, count]) => `${formatFeatureName(column)}: ${count} empty value${count === 1 ? "" : "s"}`);

  details.push(
    columnsWithMissing.length
      ? `Empty values by column — ${columnsWithMissing.join("; ")}.`
      : "No empty values found.",
  );
  details.push(
    result.range_columns.length
      ? `Built-in student-data limits checked — ${result.range_columns.map((column) =>
        `${formatFeatureName(column)}: ${result.range_limits[column][0]} to ${result.range_limits[column][1]}`).join("; ")}.`
      : "No known value-limit rules matched this dataset.",
  );
  details.push("Detectors use numeric columns only; category and text columns are not analyzed.");
  details.push("Missing numeric values are skipped by IQR and filled with the column median for Isolation Forest.");
  if (result.numbers_stored_as_text.length) {
    details.push(
      `Some values look numeric but are stored as text: ${result.numbers_stored_as_text.map(formatFeatureName).join(", ")}. These columns are not used by the detectors.`,
    );
  }
  if (result.constant_columns.length) {
    details.push(
      `Constant columns are left out of the detectors: ${result.constant_columns.map(formatFeatureName).join(", ")}.`,
    );
  }
  details.push("Duplicate count means extra exact copies after the first matching row.");

  const list = document.createElement("ul");
  details.forEach((detail) => {
    const item = document.createElement("li");
    item.textContent = detail;
    list.append(item);
  });
  content.replaceChildren(list);
}

function renderSuspects() {
  if (!latestResult) return;
  renderRowCharts();
  const search = elements.rowSearch.value.trim().toLocaleLowerCase();
  const rows = latestResult.suspects.filter((item) => {
    const matchesFilter = selectedFilter === "All" || item.flagged_by === selectedFilter;
    const matchesSearch = !search || suspectColumns.some((column) =>
      String(item[column.key] ?? "").toLocaleLowerCase().includes(search));
    return matchesFilter && matchesSearch;
  }).sort((left, right) => {
    const first = left[tableSortKey];
    const second = right[tableSortKey];
    const firstNumber = Number(first);
    const secondNumber = Number(second);
    const bothNumeric = first != null && second != null &&
      Number.isFinite(firstNumber) && Number.isFinite(secondNumber);
    const comparison = bothNumeric
      ? firstNumber - secondNumber
      : String(first ?? "").localeCompare(String(second ?? ""), undefined, {
        numeric: true,
        sensitivity: "base",
      });
    return tableSortDirection === "asc" ? comparison : -comparison;
  });
  const pageSize = Number(document.querySelector("#table-page-size").value);
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  currentTablePage = Math.min(currentTablePage, pageCount);
  const firstIndex = (currentTablePage - 1) * pageSize;
  const visibleRows = rows.slice(firstIndex, firstIndex + pageSize);
  renderTable(
    document.querySelector("#suspects-head"),
    document.querySelector("#suspects-body"),
    suspectColumns,
    visibleRows,
    "flagged_by",
  );
  const availableCount = latestResult.suspects.length;
  document.querySelector("#table-footer").textContent =
    rows.length
      ? `Showing ${firstIndex + 1}–${Math.min(firstIndex + visibleRows.length, rows.length)} of ${rows.length.toLocaleString()} matching preview records. The preview is capped at 100 per detector; export CSV for all ${latestResult.suspect_count.toLocaleString()} flagged records.`
      : `No matching rows in this preview. Export CSV for all ${latestResult.suspect_count.toLocaleString()} flagged records.`;
  document.querySelector("#table-page-status").textContent =
    `${currentTablePage} / ${pageCount}`;
  document.querySelector("#table-prev").disabled = currentTablePage <= 1;
  document.querySelector("#table-next").disabled = currentTablePage >= pageCount;
  document.querySelector("#table-pagination").classList.toggle("hidden", rows.length <= pageSize);
}

function createSvgElement(tag, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([name, value]) => {
    element.setAttribute(name, String(value));
  });
  return element;
}

function activateRowChartCategory(element, category) {
  element.setAttribute("tabindex", "0");
  element.setAttribute("role", "button");
  element.setAttribute("aria-label", `Show ${category} flagged rows`);
  element.addEventListener("click", () => selectRowChartCategory(category));
  element.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    selectRowChartCategory(category);
  });
}

function selectRowChartCategory(category) {
  selectedFilter = category;
  currentTablePage = 1;
  document.querySelectorAll(".filter-chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.filter === category);
  });
  renderSuspects();
}

function renderRowCharts() {
  const categories = [
    { label: "Both", value: latestResult.both_count, color: "#7955cf" },
    { label: "IQR only", value: Math.max(0, latestResult.iqr_count - latestResult.both_count), color: "#ff7043" },
    { label: "Isolation Forest only", value: Math.max(0, latestResult.if_count - latestResult.both_count), color: "#d94f9d" },
  ];
  const total = categories.reduce((sum, item) => sum + item.value, 0);
  const barChart = document.querySelector("#row-bar-chart");
  const pieChart = document.querySelector("#row-pie-chart");
  const legend = document.querySelector("#row-pie-legend");
  const barWidth = 480;
  const barHeight = 178;
  const barLeft = 154;
  const barRight = 42;
  const barTop = 13;
  const rowGap = 54;
  const maxValue = Math.max(1, ...categories.map((item) => item.value));

  barChart.setAttribute("viewBox", `0 0 ${barWidth} ${barHeight}`);
  barChart.replaceChildren();
  categories.forEach((item, index) => {
    const y = barTop + index * rowGap;
    const width = (barWidth - barLeft - barRight) * item.value / maxValue;
    const group = createSvgElement("g", {
      class: `row-bar-group${selectedFilter === item.label ? " is-selected" : ""}`,
    });
    const label = createSvgElement("text", {
      x: barLeft - 12, y: y + 20, class: "row-bar-label", "text-anchor": "end",
    });
    label.textContent = item.label;
    const track = createSvgElement("rect", {
      x: barLeft, y, width: barWidth - barLeft - barRight, height: 28, rx: 8,
      class: "row-bar-track",
    });
    const bar = createSvgElement("rect", {
      x: barLeft, y, width: Math.max(item.value ? 4 : 0, width), height: 28, rx: 8,
      fill: item.color, class: "row-bar-fill",
    });
    const count = createSvgElement("text", {
      x: barLeft + width + 10, y: y + 20, class: "row-bar-count",
    });
    count.textContent = item.value.toLocaleString();
    group.append(label, track, bar, count);
    activateRowChartCategory(group, item.label);
    barChart.append(group);
  });

  pieChart.setAttribute("viewBox", "0 0 180 180");
  pieChart.replaceChildren();
  const center = 90;
  const radius = 72;
  if (!total) {
    pieChart.append(createSvgElement("circle", {
      cx: center, cy: center, r: radius, fill: "#ebe7f0", class: "row-pie-empty",
    }));
    const emptyLabel = createSvgElement("text", {
      x: center, y: center + 4, class: "row-pie-empty-label", "text-anchor": "middle",
    });
    emptyLabel.textContent = "No flags";
    pieChart.append(emptyLabel);
  } else {
    let startAngle = -Math.PI / 2;
    categories.forEach((item) => {
      if (!item.value) return;
      const endAngle = startAngle + (item.value / total) * Math.PI * 2;
      const startX = center + radius * Math.cos(startAngle);
      const startY = center + radius * Math.sin(startAngle);
      const endX = center + radius * Math.cos(endAngle);
      const endY = center + radius * Math.sin(endAngle);
      const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
      const path = createSvgElement("path", {
        d: `M ${center} ${center} L ${startX} ${startY} A ${radius} ${radius} 0 ${largeArc} 1 ${endX} ${endY} Z`,
        fill: item.color,
        class: `row-pie-slice${selectedFilter === item.label ? " is-selected" : ""}`,
      });
      activateRowChartCategory(path, item.label);
      const tooltip = createSvgElement("title");
      tooltip.textContent = `${item.label}: ${item.value.toLocaleString()} rows (${(item.value / total * 100).toFixed(1)}%)`;
      path.append(tooltip);
      pieChart.append(path);
      startAngle = endAngle;
    });
  }

  const centerLabel = createSvgElement("text", {
    x: center, y: center - 3, class: "row-pie-total", "text-anchor": "middle",
  });
  centerLabel.textContent = total.toLocaleString();
  const centerCaption = createSvgElement("text", {
    x: center, y: center + 14, class: "row-pie-caption", "text-anchor": "middle",
  });
  centerCaption.textContent = total === 1 ? "flagged row" : "flagged rows";
  pieChart.append(centerLabel, centerCaption);

  legend.replaceChildren();
  categories.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `row-legend-item${selectedFilter === item.label ? " is-selected" : ""}`;
    button.setAttribute("aria-pressed", String(selectedFilter === item.label));
    button.addEventListener("click", () => selectRowChartCategory(item.label));
    const swatch = document.createElement("span");
    swatch.className = "row-legend-swatch";
    swatch.style.setProperty("--legend-color", item.color);
    const label = document.createElement("span");
    label.textContent = item.label;
    const value = document.createElement("strong");
    value.textContent = `${item.value.toLocaleString()} · ${total ? (item.value / total * 100).toFixed(1) : "0.0"}%`;
    button.append(swatch, label, value);
    legend.append(button);
  });
}

function drawChart() {
  if (
    !chartRows.length ||
    !elements.xFeature.value ||
    !elements.yFeature.value ||
    !elements.zFeature.value
  ) return;
  const canvas = elements.chart;
  const bounds = canvas.getBoundingClientRect();
  if (bounds.width < 2) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * ratio);
  canvas.height = Math.round(bounds.height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);

  const width = bounds.width;
  const height = bounds.height;
  const xKey = elements.xFeature.value;
  const yKey = elements.yFeature.value;
  const zKey = elements.zFeature.value;
  const numericValue = (value) => value == null ? Number.NaN : Number(value);
  const points = chartRows.map((row, chartIndex) => ({
    x: numericValue(row[xKey]),
    y: numericValue(row[yKey]),
    z: numericValue(row[zKey]),
    group: row.detector,
    row,
    chartIndex,
  })).filter((point) =>
    Number.isFinite(point.x) && Number.isFinite(point.y) && Number.isFinite(point.z));
  if (!points.length) return;

  const boundsByAxis = ["x", "y", "z"].reduce((result, axis) => {
    const key = axis === "x" ? xKey : axis === "y" ? yKey : zKey;
    const fullRange = latestResult?.feature_ranges?.[key];
    if (fullRange) {
      result[axis] = fullRange;
    } else {
      const values = points.map((point) => point[axis]);
      result[axis] = [Math.min(...values), Math.max(...values)];
    }
    return result;
  }, {});
  const normalize = (value, axis) => {
    const [min, max] = boundsByAxis[axis];
    return max === min ? 0 : ((value - min) / (max - min)) * 2 - 1;
  };
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.max(35, Math.min(width * 0.3, (height - 90) * 0.3, 120));
  const cameraDistance = 6.5;
  const project = (point) => {
    const cosYaw = Math.cos(chartRotation.yaw);
    const sinYaw = Math.sin(chartRotation.yaw);
    const cosPitch = Math.cos(chartRotation.pitch);
    const sinPitch = Math.sin(chartRotation.pitch);
    const rotatedX = point.x * cosYaw + point.z * sinYaw;
    const rotatedZ = -point.x * sinYaw + point.z * cosYaw;
    const rotatedY = point.y * cosPitch - rotatedZ * sinPitch;
    const depth = point.y * sinPitch + rotatedZ * cosPitch;
    const perspective = cameraDistance / (cameraDistance - depth);
    return {
      x: centerX + rotatedX * radius * perspective,
      y: centerY - rotatedY * radius * perspective,
      depth,
    };
  };
  const colors = {
    "Not flagged": "#9ca6aa",
    "IQR only": "#7654c8",
    "Isolation Forest only": "#ff642d",
    Both: "#d74f9d",
  };

  drawnPoints = [];
  context.clearRect(0, 0, width, height);
  context.font = '10px "Segoe UI", sans-serif';
  context.textBaseline = "middle";
  context.lineWidth = 1;

  const world = (x, y, z) => ({ x, y, z });
  const gridValues = [-1, -0.5, 0, 0.5, 1];
  context.strokeStyle = "#e6e2d9";
  context.globalAlpha = 0.72;
  gridValues.forEach((value) => {
    context.beginPath();
    let start = project(world(-1, -1, value));
    let end = project(world(1, -1, value));
    context.moveTo(start.x, start.y);
    context.lineTo(end.x, end.y);
    start = project(world(value, -1, -1));
    end = project(world(value, -1, 1));
    context.moveTo(start.x, start.y);
    context.lineTo(end.x, end.y);
    context.stroke();
  });
  context.globalAlpha = 1;

  const corners = [];
  [-1, 1].forEach((x) => [-1, 1].forEach((y) => [-1, 1].forEach((z) => {
    corners.push(world(x, y, z));
  })));
  const edges = [];
  corners.forEach((point, index) => {
    corners.slice(index + 1).forEach((other) => {
      const difference = Math.abs(point.x - other.x) +
        Math.abs(point.y - other.y) + Math.abs(point.z - other.z);
      if (difference === 2) edges.push([point, other]);
    });
  });
  context.strokeStyle = "#aebbb0";
  context.lineWidth = 1.15;
  edges.forEach(([start, end]) => {
    context.beginPath();
    const a = project(start);
    const b = project(end);
    context.moveTo(a.x, a.y);
    context.lineTo(b.x, b.y);
    context.stroke();
  });

  const axisLabels = [
    { name: xKey, point: world(1.12, -1, -1), color: "#7654c8" },
    { name: yKey, point: world(-1, 1.12, -1), color: "#ff642d" },
    { name: zKey, point: world(-1, -1, 1.12), color: "#288b98" },
  ];
  context.font = '600 10px "Segoe UI", sans-serif';
  axisLabels.forEach(({ name, point, color }) => {
    const label = project(point);
    context.fillStyle = color;
    context.textAlign = "center";
    context.fillText(formatFeatureName(name), label.x, label.y, 100);
  });

  const projectedPoints = points.map((point) => {
    const normalized = {
      x: normalize(point.x, "x"),
      y: normalize(point.y, "y"),
      z: normalize(point.z, "z"),
    };
    const projected = project(normalized);
    return {
      ...point,
      screenX: projected.x,
      screenY: projected.y,
      depth: projected.depth,
    };
  }).sort((a, b) => a.depth - b.depth);

  if (elements.showConnections.checked) {
    const projectedByIndex = new Map(
      projectedPoints.map((point) => [point.chartIndex, point]),
    );
    chartConnections.forEach(([firstIndex, secondIndex]) => {
      const first = projectedByIndex.get(firstIndex);
      const second = projectedByIndex.get(secondIndex);
      if (!first || !second) return;
      const flagged = first.group !== "Not flagged" || second.group !== "Not flagged";
      context.beginPath();
      context.moveTo(first.screenX, first.screenY);
      context.lineTo(second.screenX, second.screenY);
      context.strokeStyle = flagged ? "#ff642d" : "#8870c9";
      context.globalAlpha = flagged ? 0.48 : 0.36;
      context.lineWidth = flagged ? 1.2 : 0.9;
      context.stroke();
    });
    context.globalAlpha = 1;
  }

  projectedPoints.forEach((point) => {
    drawnPoints.push({ ...point, canvasX: point.screenX, canvasY: point.screenY });
    const pointRadius = point.group === "Both" ? 4.1 : 3.2;
    context.beginPath();
    context.arc(point.screenX, point.screenY, pointRadius + Math.max(0, point.depth) * 0.7, 0, Math.PI * 2);
    context.fillStyle = colors[point.group] || colors["Not flagged"];
    context.globalAlpha = point.group === "Not flagged"
      ? 0.42 + Math.max(0, point.depth) * 0.12
      : 0.82 + Math.max(0, point.depth) * 0.08;
    context.fill();
    if (point.group !== "Not flagged") {
      context.strokeStyle = "#fffdf8";
      context.lineWidth = 0.8;
      context.stroke();
    }
  });
  context.globalAlpha = 1;
}

function showChartPoint(event) {
  const bounds = elements.chart.getBoundingClientRect();
  const pointerX = event.clientX - bounds.left;
  const pointerY = event.clientY - bounds.top;
  let closest = null;
  let closestDistance = 11;
  drawnPoints.forEach((point) => {
    const distance = Math.hypot(point.canvasX - pointerX, point.canvasY - pointerY);
    if (distance < closestDistance) {
      closest = point;
      closestDistance = distance;
    }
  });
  if (!closest) {
    elements.chartTooltip.classList.add("hidden");
    return;
  }
  const row = closest.row;
  const recordId = row.row_index ?? "unknown";
  elements.chartTooltip.textContent =
    `Row ${recordId} · ${formatFeatureName(elements.xFeature.value)}: ${closest.x.toPrecision(4)} · ${formatFeatureName(elements.yFeature.value)}: ${closest.y.toPrecision(4)} · ${formatFeatureName(elements.zFeature.value)}: ${closest.z.toPrecision(4)} · ${closest.group}`;
  elements.chartTooltip.classList.remove("hidden");
  elements.chartTooltip.style.left = `${Math.max(4, Math.min(pointerX + 12, bounds.width - 310))}px`;
  elements.chartTooltip.style.top = `${Math.max(0, pointerY - 38)}px`;
}

function changeChartAxis(changedAxis) {
  if (!latestResult || latestResult.features.length < 3) return;
  const selects = [elements.xFeature, elements.yFeature, elements.zFeature];
  const otherValues = selects
    .filter((select) => select !== changedAxis)
    .map((select) => select.value);
  if (otherValues.includes(changedAxis.value)) {
    const replacement = latestResult.features.find((feature) => !otherValues.includes(feature));
    if (replacement) changedAxis.value = replacement;
  }
  elements.chartTooltip.classList.add("hidden");
  buildChartConnections();
  renderAxisRanges(latestResult);
  drawChart();
}

async function runInvestigation() {
  const requestId = ++analysisRequestId;
  const source = selectedSource();
  const body = new FormData();
  body.set("source", source);
  body.set("k", elements.k.value);
  body.set("contamination", elements.contamination.value);
  if (source === "upload") {
    if (!elements.file.files.length) {
      elements.error.textContent = "Choose a CSV file before starting the investigation.";
      elements.error.classList.remove("hidden");
      return;
    }
    body.set("file", elements.file.files[0]);
  }

  setBusy(true);
  elements.error.classList.add("hidden");
  try {
    const response = await fetch("/api/analyze", { method: "POST", body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The investigation could not be completed.");
    if (requestId !== analysisRequestId) return;
    renderResult(result);
  } catch (error) {
    if (requestId !== analysisRequestId) return;
    elements.error.textContent = error.message;
    elements.error.classList.remove("hidden");
    elements.status.textContent = "Investigation needs attention";
  } finally {
    if (requestId === analysisRequestId) setBusy(false);
  }
}

document.querySelectorAll('input[name="source"]').forEach((input) => {
  input.addEventListener("change", updateSource);
});
elements.k.addEventListener("input", () => {
  elements.kValue.value = Number(elements.k.value).toFixed(1);
  markSettingsChanged();
});
elements.contamination.addEventListener("input", () => {
  elements.contaminationValue.value = `${Math.round(Number(elements.contamination.value) * 100)}%`;
  markSettingsChanged();
});
elements.file.addEventListener("change", () => {
  elements.fileName.textContent = elements.file.files[0]?.name || "Choose a CSV file";
  elements.runButton.disabled = !elements.file.files.length;
  if (elements.file.files.length && selectedSource() === "upload") {
    runInvestigation();
  }
});
elements.runButton.addEventListener("click", runInvestigation);
document.querySelectorAll(".filter-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    selectedFilter = chip.dataset.filter;
    currentTablePage = 1;
    document.querySelectorAll(".filter-chip").forEach((item) => {
      item.classList.toggle("active", item === chip);
    });
    renderSuspects();
  });
});
elements.rowSearch.addEventListener("input", () => {
  currentTablePage = 1;
  renderSuspects();
});
document.querySelector("#table-sort").addEventListener("change", (event) => {
  tableSortKey = event.target.value;
  currentTablePage = 1;
  renderSuspects();
});
document.querySelector("#table-sort-order").addEventListener("click", (event) => {
  tableSortDirection = tableSortDirection === "asc" ? "desc" : "asc";
  event.currentTarget.textContent = tableSortDirection === "asc" ? "↑" : "↓";
  event.currentTarget.setAttribute(
    "aria-label",
    `Sort ${tableSortDirection === "asc" ? "ascending" : "descending"}`,
  );
  event.currentTarget.title = `Sort ${tableSortDirection === "asc" ? "ascending" : "descending"}`;
  currentTablePage = 1;
  renderSuspects();
});
document.querySelector("#table-page-size").addEventListener("change", () => {
  currentTablePage = 1;
  renderSuspects();
});
document.querySelector("#table-prev").addEventListener("click", () => {
  currentTablePage -= 1;
  renderSuspects();
});
document.querySelector("#table-next").addEventListener("click", () => {
  currentTablePage += 1;
  renderSuspects();
});
document.querySelectorAll(".score-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    selectedScoreMetric = tab.dataset.scoreMetric;
    document.querySelectorAll(".score-tab").forEach((item) => {
      const active = item === tab;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    if (latestResult?.evaluation) renderScoreExplorer(latestResult.evaluation);
  });
});
elements.xFeature.addEventListener("change", () => changeChartAxis(elements.xFeature));
elements.yFeature.addEventListener("change", () => changeChartAxis(elements.yFeature));
elements.zFeature.addEventListener("change", () => changeChartAxis(elements.zFeature));
elements.connectionCount.addEventListener("input", () => {
  elements.connectionCountValue.value = `${elements.connectionCount.value} nearest`;
  buildChartConnections();
  drawChart();
});
elements.showConnections.addEventListener("change", drawChart);
elements.chart.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || elements.chart.classList.contains("hidden")) return;
  chartDrag = { x: event.clientX, y: event.clientY };
  elements.chart.setPointerCapture(event.pointerId);
  elements.chart.classList.add("dragging");
  elements.chartTooltip.classList.add("hidden");
});
elements.chart.addEventListener("pointermove", (event) => {
  if (chartDrag) {
    const deltaX = event.clientX - chartDrag.x;
    const deltaY = event.clientY - chartDrag.y;
    chartDrag = { x: event.clientX, y: event.clientY };
    chartRotation.yaw += deltaX * 0.009;
    chartRotation.pitch = Math.max(-1.25, Math.min(1.25, chartRotation.pitch + deltaY * 0.009));
    drawChart();
    return;
  }
  showChartPoint(event);
});
const stopChartDrag = () => {
  chartDrag = null;
  elements.chart.classList.remove("dragging");
};
elements.chart.addEventListener("pointerup", stopChartDrag);
elements.chart.addEventListener("pointercancel", stopChartDrag);
elements.chart.addEventListener("pointerleave", () => elements.chartTooltip.classList.add("hidden"));
elements.chart.addEventListener("keydown", (event) => {
  const rotations = {
    ArrowLeft: [-0.08, 0],
    ArrowRight: [0.08, 0],
    ArrowUp: [0, -0.08],
    ArrowDown: [0, 0.08],
  };
  if (!rotations[event.key]) return;
  event.preventDefault();
  chartRotation.yaw += rotations[event.key][0];
  chartRotation.pitch = Math.max(-1.25, Math.min(1.25, chartRotation.pitch + rotations[event.key][1]));
  drawChart();
});
document.querySelector("#reset-chart-view").addEventListener("click", () => {
  chartRotation = { yaw: -0.58, pitch: 0.42 };
  drawChart();
});
document.querySelectorAll(".nav-link").forEach((button) => {
  button.addEventListener("click", () => showPage(button.dataset.page));
});
document.querySelectorAll("[data-go-page]").forEach((button) => {
  button.addEventListener("click", () => showPage(button.dataset.goPage));
});
window.addEventListener("popstate", () => {
  showPage(location.hash.slice(1) || "overview", false);
});
document.querySelector("#download-button").addEventListener("click", () => {
  if (!latestResult) return;
  downloadBlob(
    new Blob([latestResult.suspects_csv], { type: "text/csv;charset=utf-8" }),
    "data_probe_suspicious_records.csv",
  );
});

elements.pdfButton.addEventListener("click", () => {
  if (!latestResult) return;
  const body = {
    dataset_name: latestResult.dataset_name,
    rows: latestResult.rows,
    columns: latestResult.columns,
    numeric_features: latestResult.features.length,
    rows_with_missing: latestResult.rows_with_missing,
    duplicates: latestResult.duplicates,
    range_violations: latestResult.range_violations,
    iqr_count: latestResult.iqr_count,
    if_count: latestResult.if_count,
    both_count: latestResult.both_count,
    suspect_count: latestResult.suspect_count,
    has_labels: latestResult.has_labels,
  };
  document.querySelector('#pdf-form input[name="summary"]').value = JSON.stringify(body);
  document.querySelector("#pdf-form").requestSubmit();
});

async function checkLocalLlm() {
  elements.aiCheckButton.disabled = true;
  try {
    const response = await fetch("/api/llm-status");
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not check Ollama.");
    elements.aiStatus.textContent = result.message;
    elements.aiButton.disabled = !result.ready;
    elements.aiStatus.dataset.ready = String(result.ready);
    elements.aiStatus.dataset.message = result.message;
  } catch (error) {
    elements.aiStatus.textContent = error.message;
    elements.aiButton.disabled = true;
  } finally {
    elements.aiCheckButton.disabled = false;
  }
}

elements.aiCheckButton.addEventListener("click", checkLocalLlm);
elements.aiButton.addEventListener("click", async () => {
  if (!latestResult) return;
  const summary = {
    rows: latestResult.rows,
    columns: latestResult.columns,
    numeric_features: latestResult.features.length,
    rows_with_missing: latestResult.rows_with_missing,
    duplicates: latestResult.duplicates,
    range_violations: latestResult.range_violations,
    iqr_count: latestResult.iqr_count,
    if_count: latestResult.if_count,
    both_count: latestResult.both_count,
    suspect_count: latestResult.suspect_count,
    has_labels: latestResult.has_labels,
  };
  if (latestResult.has_labels) {
    summary.evaluation = latestResult.evaluation.map((item) => ({
      detector: item.detector,
      precision: item.precision,
      recall: item.recall,
      f1: item.f1,
      TP: Math.round(item.TP),
      FP: Math.round(item.FP),
      FN: Math.round(item.FN),
    }));
  }
  elements.aiButton.disabled = true;
  elements.aiButton.querySelector("span").textContent = "…";
  elements.aiError.classList.add("hidden");
  elements.aiExplanation.classList.add("hidden");
  elements.aiStatus.textContent = "Asking Ollama on this computer…";
  try {
    const response = await fetch("/api/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(summary),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The explanation could not be generated.");
    elements.aiExplanation.textContent = result.explanation;
    elements.aiExplanation.classList.remove("hidden");
    elements.aiStatus.textContent = `Written locally with ${result.model}.`;
  } catch (error) {
    elements.aiError.textContent = error.message;
    elements.aiError.classList.remove("hidden");
    elements.aiStatus.textContent = "The local explanation did not finish.";
  } finally {
    elements.aiButton.disabled = false;
    elements.aiButton.querySelector("span").textContent = "✦";
  }
});
window.addEventListener("resize", drawChart);

showPage(activePage, false);
updateSource();
runInvestigation();
checkLocalLlm();
