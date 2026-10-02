const statusLine = document.getElementById("status");

async function testConnection() {
  try {
    const response = await fetch("http://127.0.0.1:8765/health", { cache: "no-store" });
    if (!response.ok) throw new Error(`Bridge HTTP ${response.status}`);
    statusLine.textContent = "Conexión con el receptor correcta.";
  } catch (error) {
    statusLine.textContent = `No se pudo conectar: ${error}`;
  }
}

document.getElementById("test").addEventListener("click", testConnection);
document.getElementById("scan").addEventListener("click", async () => {
  const response = await chrome.runtime.sendMessage({ type: "scan_now" });
  statusLine.textContent = response?.ok ? "Escaneo iniciado; revisa el journal." : "No se pudo iniciar el escaneo.";
});
testConnection();
