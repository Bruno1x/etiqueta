# Atualizações pelo GitHub — instalação inicial 0.5.0

Repositório configurado: https://github.com/Bruno1x/etiqueta (público).

## Computador da impressão

Esta instalação completa é necessária uma vez para adicionar o novo iniciador e o botão. Feche o bot antigo, extraia o pacote e abra ABRIR_FATURAMENTO_BOT.cmd. Para manter a configuração e calibração da instalação anterior, copie as pastas config e runtime da instalação antiga para esta, com ambos os bots fechados. O histórico de impressão em LOCALAPPDATA permanece no mesmo lugar.

Depois, pare a ronda e aguarde seu encerramento. Clique Verificar atualizações. O bot consulta a última Release, baixa código e checksum, valida o pacote e pede confirmação para reiniciar. Use sempre o mesmo ABRIR_FATURAMENTO_BOT.cmd da instalação inicial: ele abre a versão ativa em .updates.

Imagens, calibração, configuração da Zebra e histórico não vêm do GitHub. Não são substituídos pelos padrões do pacote. O atualizador mantém versões anteriores. Para restaurar, feche o bot e execute RESTAURAR_VERSAO_ANTERIOR.cmd. Não exclua a pasta de instalação inicial ou .venv.

Não há atualização automática durante a ronda. A ronda não é retomada automaticamente após atualizar. Confira a versão e inicie-a manualmente.

## Publicação inicial — pelo proprietário

Nenhum arquivo foi enviado ao GitHub nesta entrega. Execute os comandos abaixo na pasta faturamento-bot deste pacote, após revisar o código. O Git solicitará sua autenticação normal; não coloque senhas ou tokens nos arquivos.

```powershell
git init
git branch -M main
git remote add origin https://github.com/Bruno1x/etiqueta.git
git add .gitignore .github faturamento_bot tools requirements.txt update_bootstrap.py ABRIR_FATURAMENTO_BOT.cmd RESTAURAR_VERSAO_ANTERIOR.cmd tests/test_updater.py ATUALIZACOES_GITHUB.md
git diff --cached --stat
git commit -m "Adiciona bot e atualizador por releases"
git push -u origin main
git tag v0.5.0
git push origin v0.5.0
```

O workflow publica apenas código Python, lista de dependências e manifesto, junto com SHA-256. Não inclua ZIPs de instalação, config, runtime, imagens ou vídeos no repositório público. O .gitignore os exclui, mas não protege arquivos que já tenham sido adicionados antes: revise sempre o git diff.

## Próximas versões

Altere o código e aumente __version__ em faturamento_bot/__init__.py, por exemplo para 0.5.1. Rode os testes locais, revise o diff, faça commit/push e publique uma tag nova:

```powershell
git add faturamento_bot tests/test_updater.py
git commit -m "Corrige fluxo do bot"
git push
git tag v0.5.1
git push origin v0.5.1
```

Após a ação do GitHub concluir, o botão do computador encontra essa versão. Commit sem tag não publica atualização. O teste da atualização ponta a ponta requer uma release superior à instalada.

## Limites desta primeira versão

O formato atual distribui código, não migra configurações nem atualiza imagens ou o iniciador. Alterações de dependências são bloqueadas e exigem instalação completa. Arquivos novos de referência ou mudanças incompatíveis na configuração também exigem um pacote completo. SHA-256 detecta corrupção do download; a confiança na origem depende do acesso à conta/repositório GitHub. Ative autenticação em duas etapas.

O repositório estava vazio e sem Releases na consulta desta entrega. O fluxo real de publicação/download ainda precisa ser validado após publicar uma versão nova. Os testes locais cobrem validação do pacote, caminhos indevidos, checksum, dados preservados e comparação de versões.
