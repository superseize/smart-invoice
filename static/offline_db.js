// SAFE OFFLINE INVOICE STORAGE (IndexedDB)

let db;

function openOfflineDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("SmartInvoiceDB", 1);

    request.onupgradeneeded = function (e) {
      db = e.target.result;
      if (!db.objectStoreNames.contains("invoices")) {
        db.createObjectStore("invoices", { keyPath: "id" });
      }
    };

    request.onsuccess = function (e) {
      db = e.target.result;
      resolve(db);
    };

    request.onerror = function () {
      reject("IndexedDB open failed");
    };
  });
}

function saveOfflineInvoice(invoice) {
  return openOfflineDB().then(db => {
    const tx = db.transaction("invoices", "readwrite");
    tx.objectStore("invoices").put(invoice);
  });
}

function getAllOfflineInvoices() {
  return openOfflineDB().then(db => {
    return new Promise(resolve => {
      const tx = db.transaction("invoices", "readonly");
      const req = tx.objectStore("invoices").getAll();
      req.onsuccess = () => resolve(req.result);
    });
  });
}

function deleteOfflineInvoice(id) {
  return openOfflineDB().then(db => {
    const tx = db.transaction("invoices", "readwrite");
    tx.objectStore("invoices").delete(id);
  });
}
