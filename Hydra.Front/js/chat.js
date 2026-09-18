// Em produção (Render), ajuste este caminho conforme onde o serviço do
// agente for publicado (ex: segundo Web Service com sua própria URL).
const AGENT_URL = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
  ? "http://localhost:8082/chat"
  : "/agent/chat";

const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const botaoEnviar = document.getElementById("chat-enviar");
const mensagensEl = document.getElementById("chat-mensagens");
const sugestoesEl = document.getElementById("chat-sugestoes");

let historico = [];

function adicionarMensagem(texto, autor, extra = "") {
  const div = document.createElement("div");
  div.className = `hydro-chat-msg hydro-chat-msg-${autor} ${extra}`.trim();
  div.textContent = texto;
  mensagensEl.appendChild(div);
  mensagensEl.scrollTop = mensagensEl.scrollHeight;
  return div;
}

async function enviar(mensagem) {
  adicionarMensagem(mensagem, "usuario");
  input.value = "";
  botaoEnviar.disabled = true;
  const pensando = adicionarMensagem("Consultando o estoque...", "agente", "hydro-chat-msg-pensando");

  try {
    const res = await fetch(AGENT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensagem, historico }),
    });
    if (!res.ok) throw new Error("falha na resposta");
    const data = await res.json();
    pensando.remove();
    adicionarMensagem(data.resposta, "agente");
    historico.push({ role: "user", content: mensagem });
    historico.push({ role: "assistant", content: data.resposta });
  } catch (err) {
    pensando.remove();
    adicionarMensagem("Não consegui responder agora. Tente de novo em instantes.", "agente", "hydro-chat-msg-erro");
  } finally {
    botaoEnviar.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const mensagem = input.value.trim();
  if (mensagem) enviar(mensagem);
});

sugestoesEl.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-pergunta]");
  if (btn) enviar(btn.dataset.pergunta);
});

adicionarMensagem("Olá! Sou o assistente de estoque. Pergunte sobre produtos mais vendidos, estoque baixo ou validade.", "agente");

/* Menu lateral mobile e visibilidade do menu Admin (mesmo comportamento das demais telas) */
const sidebar = document.getElementById("hydroSidebar");
const overlay = document.getElementById("hydroSidebarOverlay");
document.getElementById("hydroMobileToggle").addEventListener("click", () => {
  sidebar.classList.add("hydro-open");
  overlay.classList.add("hydro-show");
});
overlay.addEventListener("click", () => {
  sidebar.classList.remove("hydro-open");
  overlay.classList.remove("hydro-show");
});

(async function checkAuth() {
  if (!window.hydraApi) return;
  try {
    const { usuario } = await window.hydraApi("/auth/me");
    const nameEl = document.getElementById("hydroUserName");
    if (nameEl) nameEl.textContent = (usuario.nome || "").split(" ")[0];
    if (usuario.perfil !== "administrador") {
      document.getElementById("hydroMenuAdminLabel").style.display = "none";
      document.getElementById("hydroLiEquipe").style.display = "none";
      document.getElementById("hydroLiConfig").style.display = "none";
    }
  } catch (err) {
    // Visitante não autenticado (demo pública): mantém os itens visíveis.
  }
})();
