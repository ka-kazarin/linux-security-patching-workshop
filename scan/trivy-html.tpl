{{- /* Trivy report HTML template. Usage:
     trivy fs --format template --template @scan/trivy-html.tpl -o out.html <target>
     A summary (overall + per-host severity counts) on top, one collapsed
     findings table per target below (AGENTS.md: lean, but the overall
     count-first structure was a direct fix for "one long unreadable
     sheet" feedback from a real test run). */ -}}
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Trivy scan report</title>
<style>
  body { font-family: sans-serif; margin: 2rem; }
  h2 { margin-top: 2rem; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 1rem; }
  th, td { border: 1px solid #ccc; padding: 6px 8px; text-align: left; font-size: 14px; }
  th { background: #f2f2f2; }
  .CRITICAL { color: #b3202c; font-weight: bold; }
  .HIGH { color: #e06c00; font-weight: bold; }
  .MEDIUM { color: #c9a400; }
  .LOW { color: #3a7d44; }
  #summary-table td, #summary-table th { text-align: center; }
  #summary-table td:first-child, #summary-table th:first-child { text-align: left; }
  #summary-total td { border-top: 2px solid #888; }
  details.target-block { margin-bottom: 0.5rem; }
  details.target-block summary { cursor: pointer; font-weight: bold; padding: 6px 0; }
</style>
</head>
<body>
<h1>Trivy scan report</h1>

<h2>Summary</h2>
<table id="summary-table">
  <thead><tr><th>Host</th><th>CRITICAL</th><th>HIGH</th><th>MEDIUM</th><th>LOW</th><th>UNKNOWN</th><th>Total</th></tr></thead>
  <tbody id="summary-body"></tbody>
  <tfoot><tr id="summary-total"><td><b>Total</b></td></tr></tfoot>
</table>

<h2>Details (per host, click to expand)</h2>
{{- range . }}
<details class="target-block" data-target="{{ .Target }}">
  <summary>{{ .Target }}{{ if .Class }} ({{ .Class }}){{ end }} — {{ len .Vulnerabilities }} finding(s)</summary>
  {{- if .Vulnerabilities }}
  <table class="findings">
    <tr><th>CVE</th><th>Package</th><th>Installed</th><th>Fixed in</th><th>Severity</th><th>Title</th></tr>
    {{- range .Vulnerabilities }}
    <tr data-severity="{{ .Severity }}">
      <td><a href="{{ .PrimaryURL }}">{{ .VulnerabilityID }}</a></td>
      <td>{{ .PkgName }}</td>
      <td>{{ .InstalledVersion }}</td>
      <td>{{ .FixedVersion }}</td>
      <td class="{{ .Severity }}">{{ .Severity }}</td>
      <td>{{ .Title }}</td>
    </tr>
    {{- end }}
  </table>
  {{- else }}
  <p>No findings.</p>
  {{- end }}
</details>
{{- end }}

<script>
(function () {
  var severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"];
  var totals = {};
  severities.forEach(function (s) { totals[s] = 0; });
  var byHost = {};
  var hostOrder = [];
  document.querySelectorAll(".target-block").forEach(function (block) {
    var host = block.getAttribute("data-target");
    hostOrder.push(host);
    var counts = {};
    severities.forEach(function (s) { counts[s] = 0; });
    block.querySelectorAll("tr[data-severity]").forEach(function (row) {
      var sev = row.getAttribute("data-severity");
      if (!(sev in counts)) { sev = "UNKNOWN"; }
      counts[sev]++;
      totals[sev]++;
    });
    byHost[host] = counts;
  });
  var tbody = document.getElementById("summary-body");
  hostOrder.forEach(function (host) {
    var counts = byHost[host];
    var total = severities.reduce(function (sum, s) { return sum + counts[s]; }, 0);
    var tr = document.createElement("tr");
    [host].concat(severities.map(function (s) { return counts[s]; })).concat([total]).forEach(function (c) {
      var td = document.createElement("td");
      td.textContent = c;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  var grandTotal = severities.reduce(function (sum, s) { return sum + totals[s]; }, 0);
  var totalRow = document.getElementById("summary-total");
  severities.map(function (s) { return totals[s]; }).concat([grandTotal]).forEach(function (c) {
    var td = document.createElement("td");
    td.innerHTML = "<b>" + c + "</b>";
    totalRow.appendChild(td);
  });
})();
</script>
</body>
</html>
