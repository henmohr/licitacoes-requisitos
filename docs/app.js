const state = {
  data: null,
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderStats() {
  const docs = state.data.document_count || state.data.documents.length;
  const lots = state.data.lot_count || state.data.lots?.length || 0;
  const items = (state.data.lots || []).reduce((sum, lot) => sum + (lot.items?.length || 0), 0);
  const generatedAt = state.data.generated_at
    ? new Date(state.data.generated_at).toLocaleString("pt-BR")
    : "Data indisponível";

  document.getElementById("stats").innerHTML = `
    <div class="stat"><span>Documentos</span><strong>${docs}</strong></div>
    <div class="stat"><span>Lotes</span><strong>${lots}</strong></div>
    <div class="stat"><span>Itens</span><strong>${items}</strong></div>
    <div class="stat"><span>Gerado em</span><strong>${escapeHtml(generatedAt)}</strong></div>
  `;
}

function renderStatus() {
  const container = document.getElementById("pipelineStatus");
  const lots = state.data.lot_count || state.data.lots?.length || 0;
  const items = (state.data.lots || []).reduce((sum, lot) => sum + (lot.items?.length || 0), 0);
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

async function main() {
  const response = await fetch("./data/requirements.json");
  state.data = await response.json();
  renderStats();
  renderStatus();
  renderLots();
}

main().catch((error) => {
  document.body.innerHTML = `<pre style="padding:24px;color:#b00020">Falha ao carregar dados: ${escapeHtml(error.message)}</pre>`;
});
