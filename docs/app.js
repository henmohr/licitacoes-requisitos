const state = {
  data: null,
  search: "",
  kind: "",
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function uniq(values) {
  return [...new Set(values)].sort((a, b) => a.localeCompare(b, "pt-BR"));
}

function truncate(value, limit = 42) {
  const text = String(value);
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function matches(item) {
  const search = state.search.trim().toLowerCase();
  const kindMatch = !state.kind || item.kind === state.kind;
  if (!kindMatch) return false;
  if (!search) return true;
  const haystack = [
    item.text,
    item.section,
    item.source_file,
    item.kind,
    item.keyword,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(search);
}

function renderStats() {
  const requirements = state.data.requirements.filter(matches);
  const total = state.data.requirements.length;
  const docs = state.data.documents.length;
  const sections = state.data.sections?.length || 0;
  const lots = state.data.lot_count || state.data.lots?.length || 0;
  const kinds = uniq(state.data.requirements.map((item) => item.kind));
  const shared = state.data.comparison.shared_requirement_count;
  const unique = state.data.comparison.unique_requirement_count;

  document.getElementById("stats").innerHTML = `
    <div class="stat"><span>Documentos</span><strong>${docs}</strong></div>
    <div class="stat"><span>Seções</span><strong>${sections}</strong></div>
    <div class="stat"><span>Lotes</span><strong>${lots}</strong></div>
    <div class="stat"><span>Requisitos exibidos</span><strong>${requirements.length}</strong></div>
    <div class="stat"><span>Total bruto</span><strong>${total}</strong></div>
    <div class="stat"><span>Tipos detectados</span><strong>${kinds.length}</strong></div>
    <div class="stat"><span>Compartilhados</span><strong>${shared}</strong></div>
    <div class="stat"><span>Únicos</span><strong>${unique}</strong></div>
  `;
}

function renderStatus() {
  const container = document.getElementById("pipelineStatus");
  const date = new Date(state.data.generated_at);
  const generatedAt = Number.isNaN(date.getTime())
    ? "Data indisponível"
    : date.toLocaleString("pt-BR");
  const comparison = state.data.comparison || {};
  const shared = comparison.shared_requirement_count || 0;
  const unique = comparison.unique_requirement_count || 0;
  const duplicates = (comparison.duplicate_groups || []).length;
  const sections = state.data.section_count || state.data.sections?.length || 0;
  const lots = state.data.lot_count || state.data.lots?.length || 0;
  const csvReady = state.data.requirement_count > 0 ? "CSV gerado" : "Nenhum CSV disponível ainda";

  container.innerHTML = `
    <div class="status-card">
      <span>Gerado em</span>
      <strong>${escapeHtml(generatedAt)}</strong>
    </div>
    <div class="status-card">
      <span>PDFs processados</span>
      <strong>${state.data.document_count}</strong>
    </div>
    <div class="status-card">
      <span>Requisitos extraídos</span>
      <strong>${state.data.requirement_count}</strong>
    </div>
    <div class="status-card">
      <span>Seções estruturadas</span>
      <strong>${sections}</strong>
    </div>
    <div class="status-card">
      <span>Lotes detectados</span>
      <strong>${lots}</strong>
    </div>
    <div class="status-card">
      <span>Compartilhados</span>
      <strong>${shared}</strong>
    </div>
    <div class="status-card">
      <span>Únicos</span>
      <strong>${unique}</strong>
    </div>
    <div class="status-card">
      <span>Duplicatas exatas</span>
      <strong>${duplicates}</strong>
    </div>
    <div class="status-card">
      <span>Exportação</span>
      <strong>${escapeHtml(csvReady)}</strong>
    </div>
  `;
}

function renderDocuments() {
  const container = document.getElementById("documents");
  container.innerHTML = state.data.documents
    .map(
      (doc) => `
        <article class="doc-card">
          <div class="doc-head">
            <div class="badge">${escapeHtml(doc.file)}</div>
            <p class="meta">
              <span>${doc.requirement_count} requisitos</span>
              <span>${escapeHtml(doc.relative_path)}</span>
            </p>
          </div>
          <div class="kind-pills">
            ${(doc.top_kinds || [])
              .map(([kind, count]) => `<span class="pill">${escapeHtml(kind)} ${count}</span>`)
              .join("")}
          </div>
          <div class="kind-pills">
            ${(doc.top_sections || [])
              .map(
                ([section, count]) =>
                  `<span class="pill">${escapeHtml(truncate(section))} ${count}</span>`,
              )
              .join("")}
          </div>
        </article>
      `,
    )
    .join("");
}

function renderLots() {
  const lots = state.data.lots || [];
  const container = document.getElementById("lots");
  const count = document.getElementById("lotCount");
  count.textContent = `${lots.length} lote(s) detectado(s)`;

  if (!lots.length) {
    container.innerHTML = `<div class="empty">Nenhum lote de preços foi detectado ainda.</div>`;
    return;
  }

  container.innerHTML = lots
    .map((lot) => {
      const rows = (lot.items || [])
        .map(
          (item) => `
            <tr>
              <td>${escapeHtml(item.item)}</td>
              <td>${escapeHtml(item.description)}</td>
              <td>${escapeHtml(item.unit)}</td>
              <td>${escapeHtml(item.qty)}</td>
              <td>${escapeHtml(item.unit_price)}</td>
              <td>${escapeHtml(item.total_price || "")}</td>
            </tr>
          `,
        )
        .join("");

      return `
        <article class="lot-card">
          <div class="lot-head">
            <div>
              <span class="badge">${escapeHtml(lot.number)}</span>
              <h3>${escapeHtml(lot.title)}</h3>
            </div>
            <div class="meta">
              <span><strong>Página:</strong> ${lot.page}</span>
              <span><strong>Total do lote:</strong> ${escapeHtml(lot.total_value || "Não identificado")}</span>
              <span><strong>Itens:</strong> ${lot.items?.length || 0}</span>
            </div>
          </div>
          <div class="table-wrap">
            <table class="lot-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Descrição</th>
                  <th>Unid.</th>
                  <th>Qtde.</th>
                  <th>Valor Unit.</th>
                  <th>Valor Total</th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </article>
      `;
    })
    .join("");
}

function parseSectionTable(section) {
  const lines = String(section.content || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    return null;
  }

  const headerLine = lines[0];
  const headerNames = [];
  if (/item/i.test(headerLine) && /descri/i.test(headerLine)) {
    headerNames.push("Item", "Descrição");
    if (/avali/i.test(headerLine)) {
      headerNames.push("Avaliadores");
    }
  } else {
    headerNames.push(
      ...headerLine
        .split(/\s{2,}/)
        .map((part) => part.trim())
        .filter(Boolean),
    );
  }

  const rows = [];
  let currentRow = null;

  for (const line of lines.slice(1)) {
    if (/^(?:\d+\.\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]|\d+(?:\.\d+)+\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ])/.test(line)) {
      break;
    }

    const match = line.match(/^(\d+)\s+(.*)$/);
    if (match) {
      if (currentRow) {
        rows.push(currentRow);
      }
      currentRow = {
        item: match[1],
        description: match[2].trim(),
        evaluators: "",
      };
      continue;
    }

    if (currentRow) {
      currentRow.description = currentRow.description
        ? `${currentRow.description} ${line}`
        : line;
    }
  }

  if (currentRow) {
    rows.push(currentRow);
  }

  if (!rows.length) {
    return null;
  }

  return {
    headers: headerNames.length ? headerNames : ["Item", "Descrição"],
    rows,
  };
}

function renderSections() {
  const sections = state.data.sections || [];
  const container = document.getElementById("sections");
  const count = document.getElementById("sectionCount");
  count.textContent = `${sections.length} seção(ões) detectadas`;

  if (!sections.length) {
    container.innerHTML = `<div class="empty">Nenhuma seção estruturada foi detectada ainda.</div>`;
    return;
  }

  container.innerHTML = sections
    .map(
      (section) => `
        <article class="section-card">
          <div class="section-head">
            <div>
              <span class="badge">${escapeHtml(section.source_file)}</span>
              <h3>${escapeHtml(section.title)}</h3>
            </div>
            <div class="meta">
              <span><strong>Página:</strong> ${section.page}</span>
              <span><strong>Linhas:</strong> ${section.line_count}</span>
              <span><strong>Tipo:</strong> ${section.is_table_like ? "Tabela" : "Texto"}</span>
            </div>
          </div>
          ${
            section.is_table_like
              ? (() => {
                  const table = parseSectionTable(section);
                  if (!table) {
                    return `<pre class="section-content">${escapeHtml(
                      section.content || "Sem conteúdo extraído para esta seção.",
                    )}</pre>`;
                  }
                  const headerHtml = table.headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("");
                  const bodyHtml = table.rows
                    .map(
                      (row) => `
                        <tr>
                          <td>${escapeHtml(row.item)}</td>
                          <td>${escapeHtml(row.description)}</td>
                          ${table.headers.length > 2 ? `<td>${escapeHtml(row.evaluators || "")}</td>` : ""}
                        </tr>
                      `,
                    )
                    .join("");
                  return `
                    <div class="table-wrap">
                      <table class="section-table">
                        <thead>
                          <tr>${headerHtml}</tr>
                        </thead>
                        <tbody>${bodyHtml}</tbody>
                      </table>
                    </div>
                    <details class="section-raw">
                      <summary>Ver texto bruto</summary>
                      <pre class="section-content">${escapeHtml(
                        section.content || "Sem conteúdo extraído para esta seção.",
                      )}</pre>
                    </details>
                  `;
                })()
              : `<pre class="section-content">${escapeHtml(
                  section.content || "Sem conteúdo extraído para esta seção.",
                )}</pre>`
          }
        </article>
      `,
    )
    .join("");
}

function renderFilters() {
  const kinds = uniq(state.data.requirements.map((item) => item.kind));
  const select = document.getElementById("kindFilter");
  select.innerHTML =
    `<option value="">Todos</option>` +
    kinds.map((kind) => `<option value="${escapeHtml(kind)}">${escapeHtml(kind)}</option>`).join("");
}

function renderRequirements() {
  const items = state.data.requirements.filter(matches);
  const container = document.getElementById("requirements");
  document.getElementById("resultCount").textContent = `${items.length} itens exibidos`;

  if (!items.length) {
    container.innerHTML = `<div class="empty">Nenhum requisito encontrado com os filtros atuais.</div>`;
    return;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <article class="req-card">
          <div class="req-top">
            <span class="badge">${escapeHtml(item.kind)}</span>
            <span class="badge">${escapeHtml(item.keyword)}</span>
          </div>
          <h3>${escapeHtml(item.text)}</h3>
          <div class="meta">
            <span><strong>Arquivo:</strong> ${escapeHtml(item.source_file)}</span>
            <span><strong>Página:</strong> ${item.page}</span>
          </div>
          <div class="req-footer">
            <span><strong>Seção:</strong> ${escapeHtml(item.section)}</span>
            <span>Confiança ${Math.round(item.confidence * 100)}%</span>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderGeneratedAt() {
  const date = new Date(state.data.generated_at);
  document.getElementById("generatedAt").textContent = Number.isNaN(date.getTime())
    ? ""
    : `Gerado em ${date.toLocaleString("pt-BR")}`;
}

function renderComparison() {
  const container = document.getElementById("comparison");
  const compare = state.data.comparison;
  const docs = state.data.documents;
  document.getElementById("comparisonCount").textContent = `${docs.length} documento(s)`;

  if (docs.length < 2) {
    container.innerHTML = `<div class="empty">Adicione pelo menos dois PDFs para visualizar a comparação entre editais.</div>`;
    return;
  }

  const docSummaryRows = compare.document_summaries
    .map(
      (doc) => `
        <tr>
          <td>${escapeHtml(doc.file)}</td>
          <td>${doc.requirement_count}</td>
          <td>${doc.unique_count}</td>
          <td>${doc.shared_count}</td>
          <td>${(doc.top_kinds || [])
            .map(([kind, count]) => `${escapeHtml(kind)} (${count})`)
            .join(", ")}</td>
        </tr>
      `,
    )
    .join("");

  const allKinds = compare.kinds || [];
  const matrixRows = allKinds
    .map((kind) => {
      const cells = docs
        .map((doc) => {
          const summary = compare.document_summaries.find((item) => item.file === doc.file);
          const count = summary?.kind_counts?.[kind] || 0;
          return `<td>${count}</td>`;
        })
        .join("");
      return `<tr><th>${escapeHtml(kind)}</th>${cells}</tr>`;
    })
    .join("");

  const uniqueSections = compare.document_summaries
    .map((doc) => {
      const items = (compare.unique_examples_by_doc?.[doc.file] || [])
        .map(
          (item) => `
            <li>
              <span class="badge">${escapeHtml(item.kind)}</span>
              <span>${escapeHtml(item.text)}</span>
            </li>
          `,
        )
        .join("");
      return `
        <article class="compare-card">
          <h3>${escapeHtml(doc.file)}</h3>
          <ul class="compare-list">${items || "<li>Nenhum item único detectado.</li>"}</ul>
        </article>
      `;
    })
    .join("");

  const duplicateGroups = (compare.duplicate_groups || [])
    .map(
      (item) => `
        <li>
          <span class="badge">${escapeHtml(item.kind)}</span>
          <span>${escapeHtml(item.text)}</span>
          <small>${escapeHtml(item.docs.join(", "))}</small>
          <small>${escapeHtml(item.pages.join(" · "))}</small>
        </li>
      `,
    )
    .join("");

  const sharedItems = (compare.shared_examples || [])
    .map(
      (item) => `
        <li>
          <span class="badge">${escapeHtml(item.kind)}</span>
          <span>${escapeHtml(item.text)}</span>
          <small>${escapeHtml(item.docs.join(", "))}</small>
          <small>${escapeHtml((item.pages || []).join(" · "))}</small>
        </li>
      `,
    )
    .join("");

  container.innerHTML = `
    <div class="compare-grid">
      <article class="compare-card">
        <h3>Resumo por documento</h3>
        <table class="compare-table">
          <thead>
            <tr>
              <th>Documento</th>
              <th>Total</th>
              <th>Únicos</th>
              <th>Compart.</th>
              <th>Principais tipos</th>
            </tr>
          </thead>
          <tbody>${docSummaryRows}</tbody>
        </table>
      </article>

      <article class="compare-card">
        <h3>Comparação por tipo</h3>
        <table class="compare-table">
          <thead>
            <tr>
              <th>Tipo</th>
              ${docs.map((doc) => `<th>${escapeHtml(doc.file)}</th>`).join("")}
            </tr>
          </thead>
          <tbody>${matrixRows}</tbody>
        </table>
      </article>
    </div>

    <div class="compare-grid">
      <article class="compare-card">
        <h3>Itens únicos por edital</h3>
        <div class="compare-docs">${uniqueSections}</div>
      </article>

      <article class="compare-card">
        <h3>Itens compartilhados</h3>
        <ul class="compare-list">${sharedItems || "<li>Nenhum item compartilhado detectado.</li>"}</ul>
      </article>
    </div>

    <article class="compare-card">
      <h3>Duplicatas exatas entre documentos</h3>
      <ul class="compare-list">${duplicateGroups || "<li>Nenhuma duplicata exata detectada.</li>"}</ul>
    </article>
  `;
}

function bindEvents() {
  document.getElementById("search").addEventListener("input", (event) => {
    state.search = event.target.value;
    renderAll();
  });
  document.getElementById("kindFilter").addEventListener("change", (event) => {
    state.kind = event.target.value;
    renderAll();
  });
}

function renderAll() {
  renderStatus();
  renderStats();
  renderRequirements();
}

async function main() {
  const response = await fetch("./data/requirements.json");
  state.data = await response.json();
  renderDocuments();
  renderLots();
  renderSections();
  renderFilters();
  renderGeneratedAt();
  renderComparison();
  bindEvents();
  renderAll();
}

main().catch((error) => {
  document.body.innerHTML = `<pre style="padding:24px;color:#b00020">Falha ao carregar dados: ${escapeHtml(error.message)}</pre>`;
});
