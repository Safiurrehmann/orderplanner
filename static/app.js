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
const isImage = (file) => file.type.startsWith('image/') || /\.(jpe?g|png)$/i.test(file.name);

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
  predicate: isImage, invalidMessage: 'That needs to be a JPG or PNG spec-sheet image.',
  defaultLabel: 'Drop spec-sheet images here, or click to choose', noun: 'image',
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

const MANIFEST_CATEGORIES = [
  {
    key: 'matched', tone: 'good', title: 'Matched',
    desc: 'Artwork was found and placed on the sheet for these contracts.',
    render: 'chips',
  },
  {
    key: 'missing', tone: 'warn', title: 'Needs artwork',
    desc: "No spec-sheet image was uploaded for these contracts. Their artwork cells were left blank.",
    render: 'chips',
  },
  {
    key: 'duplicate', tone: 'bad', title: 'Uploaded twice',
    desc: 'More than one file matched the same contract, so neither was used — rather than guess. Rename the extra file and re-add it.',
    render: 'list',
  },
  {
    key: 'unreadable', tone: 'bad', title: "Couldn't read",
    desc: "Matched a contract, but the image didn't look like the expected spec-sheet layout, so it was skipped.",
    render: 'list',
  },
  {
    key: 'unused', tone: 'neutral', title: "Didn't match anything",
    desc: "These filenames didn't contain a contract code from this workbook.",
    render: 'list',
  },
];

function splitLeadingCode(item) {
  const match = item.match(/^(.*?)([:(].*)$/);
  return match ? [match[1].trim(), match[2].trim()] : [item, ''];
}

function renderManifest(report) {
  const manifest = document.querySelector('#manifest');
  manifest.innerHTML = MANIFEST_CATEGORIES.map(({ key, tone, title, desc, render }) => {
    const items = report[key] || [];
    let body;
    if (!items.length) {
      body = '<p class="manifest-empty">None.</p>';
    } else if (render === 'chips') {
      body = `<div class="chips">${items.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join('')}</div>`;
    } else {
      body = `<ul class="manifest-list">${items.map((item) => {
        const [code, detail] = splitLeadingCode(item);
        return `<li><code>${escapeHtml(code)}</code> <span class="detail">${escapeHtml(detail)}</span></li>`;
      }).join('')}</ul>`;
    }
    return `
      <div class="manifest-card" data-tone="${tone}">
        <div class="manifest-head">
          <span class="manifest-title">${escapeHtml(title)}</span>
          <span class="manifest-count">${items.length}</span>
        </div>
        <p class="manifest-desc">${escapeHtml(desc)}</p>
        ${body}
      </div>`;
  }).join('');
}

artworkForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const files = document.querySelector('#artwork').files;
  if (!sessionId || !files.length) return;
  const button = document.querySelector('#finish');
  button.disabled = true;
  announce('Matching artwork to contracts…');
  try {
    const data = new FormData();
    data.append('session_id', sessionId);
    [...files].forEach((file) => data.append('artwork', file));
    const result = await requestJson('/api/enrich', data);

    const stamp = document.querySelector('#station-2-stamp');
    const clean = result.matched_count === result.contract_count
      && !result.report.duplicate.length && !result.report.unreadable.length;
    stamp.textContent = clean ? 'Matched' : 'Check manifest';
    stamp.className = `stamp ${clean ? 'stamp-good' : 'stamp-warn'}`;

    document.querySelector('#station-2-summary').textContent =
      `${result.matched_count} of ${result.contract_count} contracts matched.`;
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
