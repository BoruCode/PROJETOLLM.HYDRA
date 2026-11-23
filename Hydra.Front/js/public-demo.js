(function () {
    'use strict';

    var pageByView = {
        dashboard: 'dashboard.html',
        caixa: 'caixa.html',
        vendas: 'caixa.html',
        produtos: 'produtos.html',
        estoque: 'controle-estoque.html',
        financeiro: 'dashboard.html',
        equipe: 'gerenciar-usuarios.html',
        configuracoes: 'configuracoes-loja.html',
    };

    // Navegação livre entre as telas (sem bloqueio/modal de cadastro para visitantes).
    document.addEventListener('click', function (event) {
        var link = event.target.closest('a[data-view]');
        if (!link) return;

        if (link.dataset.view === 'sair') {
            event.preventDefault();
            event.stopImmediatePropagation();
            var goHome = function () { window.location.href = 'index.html'; };
            if (window.hydraApi) {
                window.hydraApi('/auth/logout', { method: 'POST' }).catch(function () { }).finally(goHome);
            } else {
                goHome();
            }
            return;
        }

        if (link.getAttribute('href') === '#' && pageByView[link.dataset.view]) {
            event.preventDefault();
            event.stopImmediatePropagation();
            window.location.href = pageByView[link.dataset.view];
        }
    }, true);
})();
