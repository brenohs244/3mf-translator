Maker → ELEGOO para Windows

1. Instale e abra o ELEGOO Slicer uma vez, configurando sua Centauri Carbon 2.
2. Recomendado: execute o instalador MakerElegoo-Setup-vX.Y.Z.exe (instala sem pedir
   administrador em %LOCALAPPDATA%\Programs\MakerElegoo com atalhos e desinstalador).
3. Para uso portátil sem instalador: mantenha a pasta inteira MakerElegoo\ junta
   (não separe MakerElegoo.exe da subpasta _internal\) e execute MakerElegoo.exe.
4. Para instalar manualmente a pasta portátil no Menu Iniciar:
   powershell -ExecutionPolicy Bypass -File .\install.ps1
5. Atualizações via GitHub: use o menu Ferramentas -> Verificar atualizações...
   (ou Configure um repositório público de Releases / token GitHub em Configurar atualizações).
   O aplicativo valida o SHA-256 do instalador antes de atualizar.
6. Confira o projeto convertido no ELEGOO Slicer antes de imprimir.

O aplicativo não requer Bambu Studio. A IA Gemini e a atualização via GitHub são opcionais.
O pacote não inclui perfis de outro computador: ele lê os perfis do ELEGOO Slicer do PC atual.
