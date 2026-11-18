const bookingRows = document.querySelector("#booking-rows");
const tableRows = document.querySelector("#table-rows");
const notice = document.querySelector("#notice");
const dateFilter = document.querySelector("#filter-date");
const statusFilter = document.querySelector("#filter-status");
const bookingDialog = document.querySelector("#booking-dialog");
const tableDialog = document.querySelector("#table-dialog");
const loginScreen = document.querySelector("#login-screen");
const dashboard = document.querySelector("#admin-dashboard");
const loginForm = document.querySelector("#login-form");
const loginMessage = document.querySelector("#login-message");
const loginButton = document.querySelector("#login-button");
const logoutButton = document.querySelector("#logout-button");
let bookings = [];
let tables = [];
let noticeTimer;

function localDateString(date = new Date()) {
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers }
  });
  if (!response.ok) {
    let message = `So‘rov bajarilmadi (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((item) => item.msg).join(", ");
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

function showNotice(message, kind = "success") {
  clearTimeout(noticeTimer);
  notice.textContent = message;
  notice.className = `notice show ${kind}`;
  noticeTimer = setTimeout(() => { notice.className = "notice"; }, 5000);
}

function durationOf(booking) {
  const [startHour, startMinute] = booking.start_time.split(":").map(Number);
  const [endHour, endMinute] = booking.end_time.split(":").map(Number);
  return (endHour * 60 + endMinute) - (startHour * 60 + startMinute);
}

async function loadData() {
  bookingRows.innerHTML = '<tr><td class="empty-cell" colspan="6">Yuklanmoqda...</td></tr>';
  tableRows.innerHTML = '<tr><td class="empty-cell" colspan="3">Yuklanmoqda...</td></tr>';
  const params = new URLSearchParams();
  if (dateFilter.value) params.set("booking_date", dateFilter.value);
  if (statusFilter.value) params.set("status", statusFilter.value);
  try {
    [bookings, tables] = await Promise.all([
      api(`/admin/api/bookings?${params}`),
      api("/admin/api/tables")
    ]);
    renderBookings();
    renderTables();
    renderMetrics();
  } catch (error) {
    if (error.status === 401) {
      showLogin("Xavfsizlik uchun qayta kirishingiz kerak.");
      return;
    }
    bookingRows.innerHTML = `<tr><td class="empty-cell" colspan="6">${escapeHtml(error.message)}</td></tr>`;
    tableRows.innerHTML = `<tr><td class="empty-cell" colspan="3">${escapeHtml(error.message)}</td></tr>`;
    showNotice(error.message, "error");
  }
}

function showLogin(message = "") {
  dashboard.hidden = true;
  loginScreen.hidden = false;
  logoutButton.hidden = true;
  loginMessage.textContent = message;
  loginMessage.classList.toggle("show", Boolean(message));
  document.querySelector("#access-code").value = "";
  if (!message) document.querySelector("#access-code").focus();
}

function showDashboard() {
  loginScreen.hidden = true;
  dashboard.hidden = false;
  logoutButton.hidden = false;
}

function renderMetrics() {
  const active = bookings.filter((booking) => booking.status === "confirmed");
  document.querySelector("#metric-bookings").textContent = bookings.length;
  document.querySelector("#metric-active").textContent = active.length;
  document.querySelector("#metric-guests").textContent = active.reduce((sum, booking) => sum + booking.party_size, 0);
  document.querySelector("#metric-tables").textContent = tables.length;
}

function renderBookings() {
  if (!bookings.length) {
    bookingRows.innerHTML = '<tr><td class="empty-cell" colspan="6">Tanlangan filter bo‘yicha bron topilmadi.</td></tr>';
    return;
  }
  bookingRows.innerHTML = bookings.map((booking) => {
    const cancelled = booking.status === "cancelled";
    const date = new Date(`${booking.booking_date}T00:00:00`).toLocaleDateString("uz-UZ", { day: "numeric", month: "short", year: "numeric" });
    return `<tr>
      <td>${escapeHtml(date)}<small>${escapeHtml(booking.start_time.slice(0, 5))}–${escapeHtml(booking.end_time.slice(0, 5))}</small></td>
      <td>${escapeHtml(booking.customer_name)}<small>${escapeHtml(booking.phone)}</small></td>
      <td>${escapeHtml(booking.table_name)}</td>
      <td>${booking.party_size} kishi</td>
      <td><span class="status ${cancelled ? "cancelled" : ""}">${cancelled ? "Bekor qilingan" : "Faol"}</span></td>
      <td><div class="row-actions">
        ${cancelled ? "" : `<button class="action-button" type="button" data-edit-booking="${booking.id}">Tahrirlash</button><button class="action-button danger" type="button" data-cancel-booking="${booking.id}">Bekor qilish</button>`}
      </div></td>
    </tr>`;
  }).join("");
}

function renderTables() {
  if (!tables.length) {
    tableRows.innerHTML = '<tr><td class="empty-cell" colspan="3">Stollar topilmadi.</td></tr>';
    return;
  }
  tableRows.innerHTML = tables.map((table) => `<tr>
    <td>${escapeHtml(table.name)}</td><td>${table.seats} o‘rin</td>
    <td><div class="row-actions"><button class="action-button" type="button" data-edit-table="${table.id}">Tahrirlash</button><button class="action-button danger" type="button" data-delete-table="${table.id}">O‘chirish</button></div></td>
  </tr>`).join("");
}

function openBookingEditor(booking) {
  document.querySelector("#edit-booking-id").value = booking.id;
  document.querySelector("#edit-customer-name").value = booking.customer_name;
  document.querySelector("#edit-phone").value = booking.phone;
  document.querySelector("#edit-booking-date").value = booking.booking_date;
  document.querySelector("#edit-start-time").value = booking.start_time.slice(0, 5);
  document.querySelector("#edit-party-size").value = booking.party_size;
  const durationSelect = document.querySelector("#edit-duration");
  const duration = durationOf(booking);
  if (![...durationSelect.options].some((option) => Number(option.value) === duration)) {
    durationSelect.add(new Option(`${duration} daqiqa`, String(duration)));
  }
  durationSelect.value = String(duration);
  document.querySelector("#edit-table-id").innerHTML = tables.map((table) =>
    `<option value="${table.id}" ${table.id === booking.table_id ? "selected" : ""}>${escapeHtml(table.name)} · ${table.seats} o‘rin</option>`
  ).join("");
  bookingDialog.showModal();
}

function openTableEditor(table = null) {
  document.querySelector("#table-dialog-title").textContent = table ? "Stolni tahrirlash" : "Stol qo‘shish";
  document.querySelector("#edit-table-id").value = table ? table.id : "";
  document.querySelector("#edit-table-name").value = table ? table.name : "";
  document.querySelector("#edit-table-seats").value = table ? table.seats : 2;
  tableDialog.showModal();
}

document.querySelector("#filters").addEventListener("submit", (event) => {
  event.preventDefault();
  loadData();
});
document.querySelector("#clear-date").addEventListener("click", () => {
  dateFilter.value = "";
  loadData();
});
document.querySelector("#refresh-button").addEventListener("click", loadData);
document.querySelector("#add-table").addEventListener("click", () => openTableEditor());
logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    await api("/admin/logout", { method: "POST" });
    showLogin("Siz tizimdan chiqdingiz.");
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    logoutButton.disabled = false;
  }
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginButton.disabled = true;
  loginButton.querySelector("span:first-child").textContent = "Tekshirilmoqda...";
  loginMessage.classList.remove("show");
  try {
    await api("/admin/login", {
      method: "POST",
      body: JSON.stringify({ access_code: document.querySelector("#access-code").value })
    });
    document.querySelector("#access-code").value = "";
    showDashboard();
    await loadData();
  } catch (error) {
    loginMessage.textContent = error.message;
    loginMessage.classList.add("show");
    document.querySelector("#access-code").focus();
    document.querySelector("#access-code").select();
  } finally {
    loginButton.disabled = false;
    loginButton.querySelector("span:first-child").textContent = "Kirish";
  }
});

bookingRows.addEventListener("click", async (event) => {
  const editButton = event.target.closest("[data-edit-booking]");
  const cancelButton = event.target.closest("[data-cancel-booking]");
  if (editButton) {
    const booking = bookings.find((item) => item.id === Number(editButton.dataset.editBooking));
    if (booking) openBookingEditor(booking);
  }
  if (cancelButton) {
    if (!confirm("Ushbu bronni bekor qilmoqchimisiz?")) return;
    cancelButton.disabled = true;
    try {
      await api(`/admin/api/bookings/${cancelButton.dataset.cancelBooking}`, { method: "DELETE" });
      showNotice("Bron bekor qilindi.");
      await loadData();
    } catch (error) {
      cancelButton.disabled = false;
      showNotice(error.message, "error");
    }
  }
});

tableRows.addEventListener("click", async (event) => {
  const editButton = event.target.closest("[data-edit-table]");
  const deleteButton = event.target.closest("[data-delete-table]");
  if (editButton) {
    const table = tables.find((item) => item.id === Number(editButton.dataset.editTable));
    if (table) openTableEditor(table);
  }
  if (deleteButton) {
    if (!confirm("Ushbu stolni o‘chirmoqchimisiz? Bronlar tarixi bor stol o‘chirilmaydi.")) return;
    deleteButton.disabled = true;
    try {
      await api(`/admin/api/tables/${deleteButton.dataset.deleteTable}`, { method: "DELETE" });
      showNotice("Stol o‘chirildi.");
      await loadData();
    } catch (error) {
      deleteButton.disabled = false;
      showNotice(error.message, "error");
    }
  }
});

document.querySelector("#booking-edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const bookingId = document.querySelector("#edit-booking-id").value;
  const payload = {
    customer_name: document.querySelector("#edit-customer-name").value.trim(),
    phone: document.querySelector("#edit-phone").value.trim(),
    booking_date: document.querySelector("#edit-booking-date").value,
    start_time: document.querySelector("#edit-start-time").value,
    party_size: Number(document.querySelector("#edit-party-size").value),
    duration_minutes: Number(document.querySelector("#edit-duration").value),
    table_id: Number(document.querySelector("#edit-table-id").value)
  };
  const submitButton = event.submitter;
  submitButton.disabled = true;
  try {
    await api(`/admin/api/bookings/${bookingId}`, { method: "PATCH", body: JSON.stringify(payload) });
    bookingDialog.close();
    showNotice("Bron ma’lumotlari saqlandi.");
    await loadData();
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    submitButton.disabled = false;
  }
});

document.querySelector("#table-edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const tableId = document.querySelector("#edit-table-id").value;
  const payload = {
    name: document.querySelector("#edit-table-name").value.trim(),
    seats: Number(document.querySelector("#edit-table-seats").value)
  };
  const submitButton = event.submitter;
  submitButton.disabled = true;
  try {
    await api(tableId ? `/admin/api/tables/${tableId}` : "/admin/api/tables", {
      method: tableId ? "PATCH" : "POST",
      body: JSON.stringify(payload)
    });
    tableDialog.close();
    showNotice(tableId ? "Stol ma’lumotlari saqlandi." : "Yangi stol qo‘shildi.");
    await loadData();
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    submitButton.disabled = false;
  }
});

document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => document.querySelector(`#${button.dataset.close}`).close());
});

dateFilter.value = localDateString();
api("/admin/session").then((session) => {
  if (session.authenticated) {
    showDashboard();
    loadData();
  } else {
    showLogin();
  }
}).catch((error) => {
  showLogin(error.message);
});
