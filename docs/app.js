const state = {
  data: null,
  catalog: null,
  activeDocumentFile: "",
  map: null,
  markerLayer: null,
  geocodeCache: loadGeocodeCache(),
  filters: {
    state: "",
    software: "",
  },
};

const STATIC_MUNICIPALITY_COORDS = {
  "bom sucesso do sul|paraná": { lat: -26.07, lon: -52.83, display_name: "Bom Sucesso do Sul, Paraná, Brasil" },
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function normalizeForKey(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((left, right) => left.localeCompare(right, "pt-BR"));
}

function getMunicipalities() {
  return state.catalog || state.data?.municipalities || [];
}

function getDocuments() {
  return state.data?.documents || [];
}

function getActiveDocument() {
  const documents = getDocuments();
  if (!documents.length) {
    return null;
  }
  return documents.find((document) => document.file === state.activeDocumentFile) || documents[0];
}

function getDocumentLots(file) {
  return (state.data?.lots || []).filter((lot) => lot.source_file === file);
}

function getDocumentSections(file) {
  return (state.data?.sections || []).filter((section) => section.source_file === file);
}

function getFilteredMunicipalities() {
  const municipalities = getMunicipalities();
  const selectedState = state.filters.state;
  const selectedSoftware = state.filters.software;

  return municipalities.filter((entry) => {
    if (selectedState && entry.state !== selectedState) {
      return false;
    }
    if (selectedSoftware && !(entry.software_modules || []).includes(selectedSoftware)) {
      return false;
    }
    return true;
  });
}

function loadGeocodeCache() {
  try {
    return JSON.parse(localStorage.getItem("municipality-geocode-cache-v1") || "{}");
  } catch {
    return {};
  }
}

function saveGeocodeCache() {
  try {
    localStorage.setItem("municipality-geocode-cache-v1", JSON.stringify(state.geocodeCache));
  } catch {
    // Ignore storage failures.
  }
}

function renderStats() {
  const docs = state.data.document_count || state.data.documents.length;
  const lots = state.data.lot_count || state.data.lots?.length || 0;
  const items = (state.data.lots || []).reduce((sum, lot) => sum + (lot.items?.length || 0), 0);
  const municipalities = state.data.municipality_count || state.data.municipalities?.length || 0;
  const generatedAt = state.data.generated_at
    ? new Date(state.data.generated_at).toLocaleString("pt-BR")
    : "Data indisponível";

  document.getElementById("stats").innerHTML = `
    <div class="stat"><span>Documentos</span><strong>${docs}</strong></div>
    <div class="stat"><span>Municípios</span><strong>${municipalities}</strong></div>
    <div class="stat"><span>Lotes</span><strong>${lots}</strong></div>
    <div class="stat"><span>Itens</span><strong>${items}</strong></div>
    <div class="stat"><span>Gerado em</span><strong>${escapeHtml(generatedAt)}</strong></div>
  `;
}

function renderStatus() {
  const container = document.getElementById("pipelineStatus");
  const lots = state.data.lot_count || state.data.lots?.length || 0;
  const items = (state.data.lots || []).reduce((sum, lot) => sum + (lot.items?.length || 0), 0);
  const municipalities = state.data.municipality_count || state.data.municipalities?.length || 0;
  const csvReady = state.data.requirement_count > 0 ? "CSV gerado" : "Nenhum CSV disponível ainda";
  const generatedAt = state.data.generated_at
    ? new Date(state.data.generated_at).toLocaleString("pt-BR")
    : "Data indisponível";

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
      <span>Municípios catalogados</span>
      <strong>${municipalities}</strong>
    </div>
    <div class="status-card">
      <span>Lotes detectados</span>
      <strong>${lots}</strong>
    </div>
    <div class="status-card">
      <span>Itens extraídos</span>
      <strong>${items}</strong>
    </div>
    <div class="status-card">
      <span>Exportação</span>
      <strong>${escapeHtml(csvReady)}</strong>
    </div>
  `;
}

function renderLots() {
  const document = getActiveDocument();
  const lots = document ? getDocumentLots(document.file) : [];
  const count = document.getElementById("lotCount");
  count.textContent = document ? `${document.file} • ${lots.length} lote(s)` : "Nenhum documento ativo";
}

function renderDocumentTabs() {
  const tabsContainer = document.getElementById("documentTabs");
  const detailsContainer = document.getElementById("documentDetails");
  const documents = getDocuments();

  if (!tabsContainer || !detailsContainer) {
    return;
  }

  if (!documents.length) {
    tabsContainer.innerHTML = "";
    detailsContainer.innerHTML = `<div class="empty">Nenhum documento disponível.</div>`;
    return;
  }

  if (!state.activeDocumentFile) {
    state.activeDocumentFile = documents[0].file;
  }

  tabsContainer.innerHTML = documents
    .map((document) => {
      const active = document.file === state.activeDocumentFile ? "is-active" : "";
      const label = [document.municipality || document.file, document.state].filter(Boolean).join(" - ");
      return `<button class="doc-tab ${active}" type="button" data-file="${escapeHtml(document.file)}">${escapeHtml(label)}</button>`;
    })
    .join("");

  tabsContainer.querySelectorAll(".doc-tab").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeDocumentFile = button.dataset.file || "";
      renderDocumentTabs();
      renderLots();
    });
  });

  const activeDocument = getActiveDocument();
  if (!activeDocument) {
    detailsContainer.innerHTML = `<div class="empty">Nenhum documento ativo.</div>`;
    return;
  }

  const modules = activeDocument.software_modules || [];
  const modulePills = modules.length
    ? modules.map((name) => `<span class="pill">${escapeHtml(name)}</span>`).join("")
    : `<span class="empty">Nenhum módulo identificado neste documento.</span>`;

  const docLots = getDocumentLots(activeDocument.file);
  const docSections = getDocumentSections(activeDocument.file);
  const sectionTitles = docSections
    .filter((section) => /M[oó]dulo|PORTAL/i.test(section.title))
    .slice(0, 8)
    .map((section) => `<span class="pill">${escapeHtml(section.title.replace(/^\s*[A-Z]\s*-\s*/, "").replace(/^\d+(?:\.\d+)*\.?\s*/, ""))}</span>`)
    .join("");

  const lotRows = docLots
    .flatMap((lot) => (lot.items || []).map((item) => ({ ...item, lot_number: lot.number })))
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

  detailsContainer.innerHTML = `
    <article class="document-card">
      <div class="document-head">
        <div>
          <span class="badge">${escapeHtml(activeDocument.state || "BR")}</span>
          <h3>${escapeHtml(activeDocument.municipality || activeDocument.file)}</h3>
          <p class="map-note">${escapeHtml(activeDocument.file)}</p>
        </div>
        <div class="meta">
          <span><strong>Fornecedor:</strong> ${escapeHtml(activeDocument.supplier_name || "Não identificado")}</span>
          <span><strong>CNPJ fornecedor:</strong> ${escapeHtml(activeDocument.supplier_cnpj || "Não identificado")}</span>
          <span><strong>Lotes:</strong> ${activeDocument.lot_count || 0}</span>
          <span><strong>Itens:</strong> ${activeDocument.item_count || 0}</span>
          <span><strong>Total:</strong> ${escapeHtml(activeDocument.total_value || "Não identificado")}</span>
        </div>
      </div>
      <div class="kind-pills">${modulePills}</div>
      ${sectionTitles ? `<div class="kind-pills">${sectionTitles}</div>` : ""}
      <div class="document-summary-grid">
        <div class="status-card"><span>Município</span><strong>${escapeHtml(activeDocument.municipality || "Não identificado")}</strong></div>
        <div class="status-card"><span>Estado</span><strong>${escapeHtml(activeDocument.state || "Não identificado")}</strong></div>
        <div class="status-card"><span>Requisitos</span><strong>${activeDocument.requirement_count || 0}</strong></div>
        <div class="status-card"><span>Seções</span><strong>${docSections.length}</strong></div>
      </div>
      ${
        lotRows
          ? `
            <div class="table-wrap document-lot-wrap">
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
                <tbody>${lotRows}</tbody>
              </table>
            </div>
          `
          : `<div class="empty">Nenhum item de lote foi detectado neste documento.</div>`
      }
    </article>
  `;
}

function renderFilterControls() {
  const stateSelect = document.getElementById("stateFilter");
  const softwareSelect = document.getElementById("softwareFilter");
  const clearButton = document.getElementById("clearFilters");

  if (!stateSelect || !softwareSelect || !clearButton) {
    return;
  }

  const states = uniqueSorted(getMunicipalities().map((entry) => entry.state));
  const software = uniqueSorted(getMunicipalities().flatMap((entry) => entry.software_modules || []));

  stateSelect.innerHTML = [
    `<option value="">Todos os estados</option>`,
    ...states.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`),
  ].join("");

  softwareSelect.innerHTML = [
    `<option value="">Todos os softwares</option>`,
    ...software.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`),
  ].join("");

  stateSelect.value = state.filters.state;
  softwareSelect.value = state.filters.software;

  stateSelect.onchange = (event) => {
    state.filters.state = event.target.value;
    renderMunicipalityCatalog();
    renderMap();
  };

  softwareSelect.onchange = (event) => {
    state.filters.software = event.target.value;
    renderMunicipalityCatalog();
    renderMap();
  };

  clearButton.onclick = () => {
    state.filters.state = "";
    state.filters.software = "";
    stateSelect.value = "";
    softwareSelect.value = "";
    renderMunicipalityCatalog();
    renderMap();
  };
}

function renderMunicipalityCatalog() {
  const allMunicipalities = getMunicipalities();
  const municipalities = getFilteredMunicipalities();
  const container = document.getElementById("municipalityCatalog");
  const count = document.getElementById("municipalityCount");

  if (count) {
    const total = allMunicipalities.length;
    const filtered = municipalities.length;
    const suffix = filtered === total ? "" : ` de ${total}`;
    count.textContent = `${filtered}${suffix} município(s) catalogado(s)`;
  }

  if (!municipalities.length) {
    container.innerHTML = `<div class="empty">Nenhum município corresponde aos filtros selecionados.</div>`;
    return;
  }

  container.innerHTML = municipalities
    .map((entry) => {
      const software = (entry.software_modules || [])
        .slice(0, 8)
        .map((name) => `<span class="pill">${escapeHtml(name)}</span>`)
        .join("");
      const sources = (entry.source_files && entry.source_files.length ? entry.source_files : [entry.source_file]).filter(Boolean);

      return `
        <article class="municipality-card">
          <div class="municipality-head">
            <div>
              <span class="badge">${escapeHtml(entry.state || "BR")}</span>
              <h3>${escapeHtml(entry.municipality || entry.source_file)}</h3>
            </div>
            <div class="meta">
              <span><strong>Cód. IBGE:</strong> ${escapeHtml(entry.cod_municipio || "Não identificado")}</span>
              <span><strong>Fornecedor:</strong> ${escapeHtml(entry.supplier_name || "Não identificado")}</span>
              <span><strong>CNPJ fornecedor:</strong> ${escapeHtml(entry.supplier_cnpj || "Não identificado")}</span>
              <span><strong>Arquivos:</strong> ${escapeHtml(sources.join(", "))}</span>
              <span><strong>Lotes:</strong> ${entry.lot_count || 0}</span>
              <span><strong>Itens:</strong> ${entry.item_count || 0}</span>
            </div>
          </div>
          <div class="kind-pills">${software || '<span class="empty">Sem módulos identificados.</span>'}</div>
          <div class="kind-pills">
            <span class="pill">Interno: ${escapeHtml(entry.software_internal || "n/d")}</span>
            <span class="pill">Sociedade: ${escapeHtml(entry.software_sociedade || "n/d")}</span>
            <span class="pill">Sem software: ${escapeHtml(entry.nao_desenvolveu_software || "n/d")}</span>
          </div>
          <p class="municipality-total">
            <strong>Base:</strong>
            ${escapeHtml(entry.region || "Região não identificada")}
            ${entry.population ? ` • População ${escapeHtml(entry.population)}` : ""}
          </p>
          <p class="municipality-total">
            <strong>Atendimento:</strong>
            ${[entry.atendimento_website, entry.atendimento_whatsapp, entry.atendimento_telefone]
              .filter(Boolean)
              .join(" / ") || "Não identificado"}
          </p>
          <p class="municipality-total"><strong>Total:</strong> ${escapeHtml(entry.total_value || "Não identificado")}</p>
        </article>
      `;
    })
    .join("");
}

async function geocodeMunicipality(entry) {
  const query = [entry.municipality, entry.state, "Brasil"].filter(Boolean).join(", ");
  const cacheKey = query.toLowerCase();
  const fallbackKey = `${String(entry.municipality || "").toLowerCase()}|${String(entry.state || "").toLowerCase()}`;

  if (STATIC_MUNICIPALITY_COORDS[fallbackKey]) {
    return STATIC_MUNICIPALITY_COORDS[fallbackKey];
  }
  if (state.geocodeCache[cacheKey]) {
    return state.geocodeCache[cacheKey];
  }

  const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&countrycodes=br&limit=1&q=${encodeURIComponent(query)}`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    return null;
  }

  const results = await response.json();
  if (!results.length) {
    return null;
  }

  const point = {
    lat: Number(results[0].lat),
    lon: Number(results[0].lon),
    display_name: results[0].display_name,
  };
  state.geocodeCache[cacheKey] = point;
  saveGeocodeCache();
  return point;
}

function initMap() {
  const mapEl = document.getElementById("municipalityMap");
  if (!mapEl || typeof L === "undefined" || state.map) {
    return;
  }

  state.map = L.map("municipalityMap", { scrollWheelZoom: false }).setView([-14.235, -51.9253], 4);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 18,
  }).addTo(state.map);

  state.markerLayer =
    typeof L.markerClusterGroup === "function"
      ? L.markerClusterGroup({
          showCoverageOnHover: false,
          spiderfyOnMaxZoom: true,
          removeOutsideVisibleBounds: true,
        })
      : L.layerGroup();
  state.map.addLayer(state.markerLayer);
}

function clearMarkers() {
  if (state.markerLayer && typeof state.markerLayer.clearLayers === "function") {
    state.markerLayer.clearLayers();
  }
}

function buildPopupContent(entry, point) {
  const software = (entry.software_modules || []).slice(0, 10).join(", ") || "Sem módulos identificados";
  const sources = (entry.source_files && entry.source_files.length ? entry.source_files : [entry.source_file]).filter(Boolean).join(", ");

  return `
    <strong>${escapeHtml(entry.municipality || entry.source_file)}</strong><br />
    ${escapeHtml(entry.state || "")}<br />
    <small>${escapeHtml(point.display_name || "")}</small><br />
    <strong>Softwares:</strong> ${escapeHtml(software)}<br />
    <strong>Fornecedor:</strong> ${escapeHtml(entry.supplier_name || "Não identificado")}<br />
    <strong>CNPJ fornecedor:</strong> ${escapeHtml(entry.supplier_cnpj || "Não identificado")}<br />
    <strong>Arquivos:</strong> ${escapeHtml(sources)}
  `;
}

async function renderMap() {
  const municipalities = getFilteredMunicipalities();
  if (!state.map || !state.markerLayer) {
    return;
  }

  clearMarkers();
  const points = [];

  for (const entry of municipalities) {
    const point = await geocodeMunicipality(entry);
    if (!point || Number.isNaN(point.lat) || Number.isNaN(point.lon)) {
      continue;
    }

    points.push([point.lat, point.lon]);
    const marker = L.marker([point.lat, point.lon]);
    marker.bindPopup(buildPopupContent(entry, point));
    state.markerLayer.addLayer(marker);
  }

  if (points.length) {
    const bounds = L.latLngBounds(points);
    state.map.fitBounds(bounds.pad(0.25));
  } else {
    state.map.setView([-14.235, -51.9253], 4);
  }
}

async function main() {
  const response = await fetch("./data/requirements.json");
  state.data = await response.json();
  try {
    const catalogResponse = await fetch("./data/municipality_catalog.json");
    state.catalog = await catalogResponse.json();
  } catch {
    state.catalog = state.data.municipality_catalog || state.data.municipalities || [];
  }

  renderStats();
  renderStatus();
  renderFilterControls();
  renderDocumentTabs();
  renderMunicipalityCatalog();
  renderLots();
  initMap();
  await renderMap();
}

main().catch((error) => {
  document.body.innerHTML = `<pre style="padding:24px;color:#b00020">Falha ao carregar dados: ${escapeHtml(error.message)}</pre>`;
});
