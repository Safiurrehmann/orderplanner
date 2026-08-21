const form = document.querySelector('#convert-form');
const fileInput = document.querySelector('#pdf');
const fileLabel = document.querySelector('#file-label');
const dropzone = document.querySelector('#dropzone');
const submit = document.querySelector('#submit');
const status = document.querySelector('#status');

function setFile(file) {
  if (!file) return;
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    status.textContent = 'Please choose a PDF file.';
    return;
  }
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  fileLabel.textContent = file.name;
  status.textContent = '';
}

fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
['dragenter', 'dragover'].forEach((eventName) => dropzone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropzone.classList.add('dragging');
}));
['dragleave', 'drop'].forEach((eventName) => dropzone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropzone.classList.remove('dragging');
}));
dropzone.addEventListener('drop', (event) => setFile(event.dataTransfer.files[0]));

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file) {
    status.textContent = 'Choose a PDF first.';
    return;
  }
  submit.disabled = true;
  status.textContent = 'Creating your Excel sheet…';
  const data = new FormData();
  data.append('pdf', file);
  data.append('download_name', document.querySelector('#download-name').value);
  try {
    const response = await fetch('/api/convert', { method: 'POST', body: data });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || 'Conversion failed.');
    }
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    const header = response.headers.get('content-disposition') || '';
    link.download = (header.match(/filename="?([^";]+)"?/) || [])[1] || 'plan_sheet.xlsx';
    link.click();
    URL.revokeObjectURL(link.href);
    status.textContent = 'Done — your download has started.';
  } catch (error) {
    status.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
