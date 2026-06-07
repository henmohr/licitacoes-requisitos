const state = {
  data: null,
  map: null,
  markers: [],
  geocodeCache: loadGeocodeCache(),
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

function renderMunicipalityCatalog() {
  const municipalities = state.data.municipalities || [];
  const container = document.getElementById("municipalityCatalog");
  const count = document.getElementById("municipalityCount");
  count.textContent = `${municipalities.length} município(s) catalogado(s)`;

  if (!municipalities.length) {
    container.innerHTML = `<div class="empty">Nenhum município identificado ainda.</div>`;
    return;
  }

  container.innerHTML = municipalities
    .map((entry) => {
      const software = (entry.software_modules || [])
        .slice(0, 8)
        .map((name) => `<span class="pill">${escapeHtml(name)}</span>`)
        .join("");

      return `
        <article class="municipality-card">
          <div class="municipality-head">
            <div>
              <span class="badge">${escapeHtml(entry.state || "BR")}</span>
              <h3>${escapeHtml(entry.municipality || entry.source_file)}</h3>
            </div>
            <div class="meta">
              <span><strong>Arquivo:</strong> ${escapeHtml(entry.source_file)}</span>
              <span><strong>Lotes:</strong> ${entry.lot_count || 0}</span>
              <span><strong>Itens:</strong> ${entry.item_count || 0}</span>
            </div>
          </div>
          <div class="kind-pills">${software || '<span class="empty">Sem módulos identificados.</span>'}</div>
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

function clearMarkers() {
  for (const marker of state.markers) {
    marker.remove();
  }
  state.markers = [];
}

function initMap() {
  const mapEl = document.getElementById("municipalityMap");
  if (!mapEl || typeof L === "undefined") {
    return;
  }

  state.map = L.map("municipalityMap", { scrollWheelZoom: false }).setView([-14.235, -51.9253], 4);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 18,
  }).addTo(state.map);
}

async function renderMap() {
  const municipalities = state.data.municipalities || [];
  if (!state.map || !municipalities.length) {
    return;
  }

  clearMarkers();
  const points = [];

  for (const entry of municipalities) {
    const point = await geocodeMunicipality(entry);
    if (!point || Number.isNaN(point.lat) || Number.isNaN(point.lon)) {
      continue;
    }

    points.push(point);
    const marker = L.marker([point.lat, point.lon]).addTo(state.map);
    marker.bindPopup(`
      <strong>${escapeHtml(entry.municipality || entry.source_file)}</strong><br />
      ${escapeHtml(entry.state || "")}<br />
      ${escapeHtml((entry.software_modules || []).slice(0, 6).join(", "))}
    `);
    state.markers.push(marker);
  }

  if (points.length) {
    const bounds = L.latLngBounds(points.map((point) => [point.lat, point.lon]));
    state.map.fitBounds(bounds.pad(0.25));
  }
}

async function main() {
  const response = await fetch("./data/requirements.json");
  state.data = await response.json();

  renderStats();
  renderStatus();
  renderMunicipalityCatalog();
  renderLots();
  initMap();
  await renderMap();
}

main().catch((error) => {
  document.body.innerHTML = `<pre style="padding:24px;color:#b00020">Falha ao carregar dados: ${escapeHtml(error.message)}</pre>`;
});
