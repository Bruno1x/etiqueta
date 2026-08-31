# Etiquetas Bot — SYSEMP

## Versão atual 0.5.6 — clique confirmado na loja

Esta versão reconhece os layouts compacto e expandido conhecidos, em tema claro ou escuro, limpa todas as lojas ML antes da ronda e envia obrigatoriamente um clique para marcar a loja atual. A seleção é conferida depois do clique e a loja é desmarcada mesmo quando a operação é interrompida. A ordem semântica das colunas ainda é obrigatória.

## Versão atual 0.4.0 — ronda de impressão

Leia **RONDA_0.4.0.md** para iniciar a impressão de múltiplos pedidos e a repetição a cada 15 minutos após o término. A ronda física está habilitada nesta versão, mediante confirmação na interface. Abaixo permanece o histórico das versões anteriores; suas limitações de impressão não descrevem a versão atual.

## Atualização 0.3.0: teste físico de um pedido

O novo botão IMPRIMIR 1 PEDIDO NA ZEBRA — TESTE REAL envia um pedido pelo fluxo direto da gravação. Leia TESTE_IMPRESSAO_REAL.md antes de usar. As limitações de impressão abaixo descrevem a versão anterior; a ronda em lote continua bloqueada.

Automação local dedicada exclusivamente à impressão de etiquetas do Mercado Livre no gerenciador de e-commerce do SYSEMP.

**Versão 0.2.0-navigation-test: teste de navegação, sem impressão.**
Impressora configurada: ZDesigner GC420t (EPL), identificada pelo nome
da fila do Windows. Não há fallback para outra impressora.
Isso não instala o driver nem habilita a implementação de impressão automática.
Leia REVISAO.md para as correções, limitações e instruções de instalação em outro computador.

O fluxo não fatura pedidos e não transmite NF-e. Se iniciado na tela de notas,
somente sai dela para chegar ao e-commerce.

## Lojas processadas

1. ML CENTRAL
2. ML DISTRIBUIDOR
3. ML FABRICA
4. ML HERO BAND
5. ML POOLSY
6. ML SHOPPING
7. ML STORE
8. ML UNIVERSO

Canais FULL, NUVEM e SHOPEE não fazem parte desta automação.

## Regras do fluxo

- Abrir e-Commerce → Impressões de Etiquetas e Notas Fiscais.
- Limpar o código numérico da Empresa no e-commerce, sair do campo e verificar código e descrição vazios, como na gravação. Não procurar a empresa em checklist nessa tela.
- Marcar apenas uma loja ML por vez.
- Processar somente linhas com Lib Etiqueta verde e Etiq Impressa desmarcada, uma por uma.
- Reavaliar as não liberadas em cada ronda, sem descartá-las permanentemente.
- Estado desconhecido não autoriza impressão.
- Deixar as datas de Nota Fiscal vazias e filtrar Limite Entrega de hoje até amanhã.
- Em cada linha, usar Etiqueta + Documentos.
- Desmarcar a loja concluída antes de selecionar a próxima.
- Encerrar somente depois de percorrer as oito lojas.
- Imprimir exclusivamente em uma fila configurada para Zebra.
- Se nenhuma Zebra for encontrada, interromper antes da primeira impressão; Epson e impressora padrão nunca são alternativas.

## Ordem obrigatória das colunas da grade

Na versão `0.5.6`, mantenha as colunas visíveis nesta ordem:

1. Lib Etiqueta
2. ID
3. Marketplace / Apelido
4. Canal de Vendas
5. Nota Fiscal
6. Status NFe
7. NF Impressa
8. Sep Impressa
9. Etiq Impressa
10. Série
11. Emissão
12. CFOP
13. Data Pedido
14. Pedido
15. Pedido Marketplace

O tema claro ou escuro pode ser escolhido livremente. Não reorganize, oculte nem redimensione essas colunas durante uma ronda. Se a estrutura estiver diferente ou alguma informação não puder ser confirmada, o bot deve interromper antes de imprimir.

Essa limitação será removida quando a calibração semântica por computador estiver implementada e validada.

## Abrir o programa

Execute:

```powershell
cd C:\Users\bruno\Documents\Codex\2026-08-24\pre\outputs\faturamento-bot
.\ABRIR_FATURAMENTO_BOT.cmd
```

Ou dê duplo clique em `ABRIR_FATURAMENTO_BOT.cmd`.

## Teste sem impressão

1. Abra o SYSEMP.
2. Clique em Auto calibrar.
3. Clique em Testar etiquetas no SYSEMP (sem imprimir).

O teste abre o e-commerce, limpa Empresa e percorre as oito lojas, marcando,
pesquisando e desmarcando cada uma. Comece com Canal de Vendas em <TODOS>,
sem caixas marcadas de execução anterior. Nenhuma etiqueta é impressa.

O teste também preenche as datas de entrega. O período pode ser alterado em
config/faturamento.toml, sem mudar o código:

```toml
[processing.delivery_window]
start_offset_days = 0
end_offset_days = 1
```

Os valores são dias relativos à data local de início da ronda.

## Estado da implementação

A ronda percorre as oito lojas, processa somente linhas liberadas e ainda não impressas, e exige confirmação do SYSEMP antes de seguir. A operação real deve continuar sendo supervisionada até que cada combinação de versão do SYSEMP, layout e impressora Zebra utilizada pela empresa seja homologada.

## Segurança da impressão

As permissões locais em `config/faturamento.toml` estão habilitadas a pedido do usuário:

```toml
[safety]
allow_live = true
```

No computador de operação, confirme a existência da fila `ZDesigner GC420t (EPL)`, execute a autocalibração e confira a ordem obrigatória das colunas antes de iniciar a primeira ronda real.
