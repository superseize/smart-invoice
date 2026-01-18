function saveOfflineInvoice(invoice) {
  let list = JSON.parse(localStorage.getItem("offline_invoices") || "[]");
  list.push(invoice);
  localStorage.setItem("offline_invoices", JSON.stringify(list));
}

function getOfflineInvoices() {
  return JSON.parse(localStorage.getItem("offline_invoices") || "[]");
}

function clearOfflineInvoices() {
  localStorage.removeItem("offline_invoices");
}
