/* ===================================================================
   HydroSync — espelha o HydroStore (localStorage) no MySQL via
   PUT /api/sincronizar, para que o Agente de IA consulte dados reais.
   Carregar DEPOIS de hydro-store.js e api.js. Falhas (ex.: usuário não
   logado, API fora do ar) são silenciosas: o sistema segue funcionando
   só com o localStorage.
   =================================================================== */
(function (global) {
    'use strict';

    var Store = global.HydroStore;
    if (!Store || typeof global.hydraApi !== 'function') return;

    var DEBOUNCE_MS = 1500;
    var timer = null;
    var enviando = false;
    var pendente = false;

    function enviar() {
        if (enviando) {
            pendente = true;
            return;
        }
        enviando = true;
        global.hydraApi('/sincronizar', {
            method: 'PUT',
            body: {
                products: Store.getProducts(),
                sales: Store.getSales(),
                movements: Store.getMovements(),
            },
        })
            .catch(function () { /* silencioso */ })
            .then(function () {
                enviando = false;
                if (pendente) {
                    pendente = false;
                    agendar();
                }
            });
    }

    function agendar() {
        clearTimeout(timer);
        timer = setTimeout(enviar, DEBOUNCE_MS);
    }

    // Toda função que altera dados dispara uma sincronização (com debounce).
    ['saveProducts', 'addProduct', 'updateProduct', 'adjustStock',
     'removeProduct', 'addSale', 'addMovement', 'seedHistoryIfNeeded'].forEach(function (nome) {
        var original = Store[nome];
        Store[nome] = function () {
            var resultado = original.apply(Store, arguments);
            agendar();
            return resultado;
        };
    });

    global.HydroSync = { agora: enviar };
    agendar(); // sincroniza o estado atual ao abrir a página
})(window);
