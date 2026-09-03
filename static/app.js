const status = document.querySelector('#status');
const convertForm = document.querySelector('#convert-form');
const artworkForm = document.querySelector('#artwork-form');
const station1 = document.querySelector('#station-1');
const station2 = document.querySelector('#station-2');
let sessionId = null;

function announce(message) {
  status.textContent = message;
}

const ESCAPE_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ESCAPE_MAP[char]);
}

// ---------- Dropzones ----------

const isPdf = (file) => file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
const isZip = (file) => file.type === 'application/zip' || /\.zip$/i.test(file.name);

function configureDropzone({ zoneId, inputId, labelId, listId, predicate, invalidMessage, defaultLabel, noun }) {
  const zone = document.querySelector(zoneId);
  const input = document.querySelector(inputId);
  const label = document.querySelector(labelId);
  const list = document.querySelector(listId);

  function setFiles(files) {
    if (!files?.length) return;
    if (![...files].every(predicate)) {
      announce(invalidMessage);
      return;
    }
    const transfer = new DataTransfer();
    [...files].forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    label.textContent = `${files.length} ${noun}${files.length === 1 ? '' : 's'} ready`;
    list.innerHTML = [...files].map((file) => `<li>${escapeHtml(file.name)}</li>`).join('');
    list.hidden = false;
    announce('');
  }

  input.addEventListener('change', () => setFiles(input.files));
  ['dragenter', 'dragover'].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault(); zone.classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault(); zone.classList.remove('dragging');
  }));
  zone.addEventListener('drop', (event) => setFiles(event.dataTransfer.files));
}

configureDropzone({
  zoneId: '#po-dropzone', inputId: '#pdf', labelId: '#po-label', listId: '#po-file-list',
  predicate: isPdf, invalidMessage: "That's not a PDF. Choose the purchase order file you were sent.",
  defaultLabel: 'Drop PO PDFs here, or click to choose', noun: 'PDF',
});

configureDropzone({
  zoneId: '#artwork-dropzone', inputId: '#artwork', labelId: '#artwork-label', listId: '#artwork-file-list',
  predicate: isZip, invalidMessage: 'Upload one ZIP artwork package.',
  defaultLabel: 'Drop the artwork ZIP here, or click to choose', noun: 'package',
});

// ---------- Networking ----------

async function requestJson(url, data) {
  const response = await fetch(url, { method: 'POST', body: data });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || 'Something went wrong. Try again.');
  return body;
}

// ---------- Station 1: purchase order ----------

convertForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const pdfs = document.querySelector('#pdf').files;
  if (!pdfs.length) return;
  const button = document.querySelector('#create');
  button.disabled = true;
  announce('Reading the purchase order…');
  try {
    const data = new FormData();
    data.append('format', document.querySelector('#workbook-format').value);
    [...pdfs].forEach((file) => data.append('pdfs', file));
    const result = await requestJson('/api/convert', data);
    sessionId = result.session_id;

    const poWord = result.sheets.length === 1 ? 'purchase order' : 'purchase orders';
    document.querySelector('#station-1-summary').textContent =
      `${result.sheets.length} ${poWord} logged — ${result.row_count} rows total.`;
    document.querySelector('#station-1-sheets').innerHTML = result.sheets
      .map((s) => `<li>${escapeHtml(s.title)} — PO ${escapeHtml(s.po_number)} · ${s.row_count} row${s.row_count === 1 ? '' : 's'}</li>`)
      .join('');
    document.querySelector('#sheet-link').href = result.download_url;

    convertForm.hidden = true;
    document.querySelector('#station-1-receipt').hidden = false;
    station1.dataset.state = 'done';

    station2.dataset.state = 'active';
    document.querySelector('#station-2-locked-note').hidden = true;
    artworkForm.hidden = false;

    announce('Station 1 complete. Add the artwork below to finish.');
  } catch (error) {
    announce(error.message);
  } finally {
    button.disabled = false;
  }
});

// ---------- Station 2: artwork ----------

const RESULT_COPY = {
  matched: ['good', 'Source artwork inserted'],
  fallback: ['good', 'Inserted from spec-sheet JPG'],
  missing: ['warn', 'Artwork missing'],
  ambiguous: ['bad', 'Multiple possible files — nothing inserted'],
  unreadable: ['bad', 'Matched file could not be used'],
};

function renderManifest(report) {
  const manifest = document.querySelector('#manifest');
  const groups = (report.records || []).reduce((result, record) => {
    (result[record.contract] ||= []).push(record);
    return result;
  }, {});
  manifest.innerHTML = Object.entries(groups).map(([contract, records]) => `
      <div class="manifest-card" data-tone="${records.every((item) => ['matched', 'fallback'].includes(item.status)) ? 'good' : 'warn'}">
        <div class="manifest-head">
          <span class="manifest-title">${escapeHtml(contract)}</span>
          <span class="manifest-count">${records.filter((item) => ['matched', 'fallback'].includes(item.status)).length}/${records.length}</span>
        </div>
        <ul class="manifest-list">${records.map((record) => {
          const [tone, copy] = RESULT_COPY[record.status] || ['neutral', record.status];
          const detail = record.path || record.detail || '';
          return `<li data-tone="${tone}"><code>${escapeHtml(record.position)}</code> <span>${escapeHtml(copy)}</span>${detail ? ` <span class="detail">— ${escapeHtml(detail)}</span>` : ''}</li>`;
        }).join('')}</ul>
      </div>`).join('');
}

artworkForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const packageFile = document.querySelector('#artwork').files[0];
  if (!sessionId || !packageFile) return;
  const button = document.querySelector('#finish');
  button.disabled = true;
  announce('Uploading, unpacking, and matching the artwork package…');
  try {
    const data = new FormData();
    data.append('session_id', sessionId);
    data.append('package', packageFile);
    const result = await requestJson('/api/enrich', data);

    const stamp = document.querySelector('#station-2-stamp');
    const clean = result.matched_count === result.slot_count;
    stamp.textContent = clean ? 'Matched' : 'Check manifest';
    stamp.className = `stamp ${clean ? 'stamp-good' : 'stamp-warn'}`;

    document.querySelector('#station-2-summary').textContent =
      `${result.matched_count} of ${result.slot_count} artwork positions matched${result.fallback_count ? ` · ${result.fallback_count} from JPG fallback` : ''}.`;
    renderManifest(result.report);
    document.querySelector('#final-link').href = result.download_url;

    artworkForm.hidden = true;
    document.querySelector('#station-2-receipt').hidden = false;
    station2.dataset.state = 'done';

    announce('Station 2 complete. Your plan sheet is ready to download.');
  } catch (error) {
    announce(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector('#print-manifest').addEventListener('click', () => window.print());
