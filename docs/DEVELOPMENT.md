# Desenvolvimento e manutenção

## Executar

No Windows com Python 3.11 ou superior:

```powershell
$env:PYTHONPATH = 'src'
python -m maker_elegoo
python -m unittest discover -s tests -v
```

O ELEGOO Slicer deve estar instalado e ter os perfis da Centauri Carbon 2. É possível definir `ELEGOO_SLICER_EXE` para um caminho personalizado. Para preferências portáteis, defina `MAKER_ELEGOO_CONFIG_DIR`.

Os perfis são descobertos automaticamente em `%APPDATA%\ElegooSlicer\system` e `%APPDATA%\ElegooSlicer\user\<conta>\{machine,process,filament}` no computador em que o programa roda. A lista de bicos vem dos perfis de máquina da Centauri Carbon 2 instalados. Os perfis personalizados são filtrados pela herança e pelos dados de compatibilidade resolvidos; o nome do perfil não determina o diâmetro do bico. O programa não importa perfis de outro computador nem altera os perfis do fatiador.

## Distribuir

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install pyinstaller
winget install JRSoftware.InnoSetup
.\scripts\build.ps1
python .\scripts\smoke_exe.py
powershell -ExecutionPolicy Bypass -File .\scripts\publish_release.ps1 -DryRun
```

- `dist/MakerElegoo-Setup-v<versao>.exe` (compilado com Inno Setup 6 via `scripts/installer.iss`) instala o pacote rápido `--onedir` em `%LOCALAPPDATA%\Programs\MakerElegoo` (sem exigir administrador, com desinstalador, atalhos e suporte a atualização silenciosa `/VERYSILENT`).
- `dist/MakerElegoo-Windows-Portable.zip` contém a pasta portátil `--onedir` (`MakerElegoo\`), `install.ps1` e `LEIA-ME.txt`. Passe `-OneFile` ao `build.ps1` apenas se precisar gerar um `.exe` único avulso.
- `dist/checksums-v<versao>.txt` registra os hashes SHA-256 validados pelo atualizador automático (`updater.py` + `Ferramentas → Verificar atualizações...`). Como `brenohs244/3mf-translator` é privado no GitHub, o atualizador aceita tanto Token GitHub read-only salvo com DPAPI quanto apontar `update_repo` (ou `MAKER_ELEGOO_UPDATE_REPO`) para um repositório público dedicado apenas às Releases.
- O executável procura o ELEGOO Slicer no computador de destino; o fatiador e perfis personalizados não são incluídos no pacote.

## Superpowers, Graphify, Understand Anything e Find Skills

- Superpowers: seguir a especificação em `docs/superpowers/specs/` e o plano em `docs/superpowers/plans/`; usar TDD, verificação e revisão antes de declarar compatibilidade.
- Módulos de decisão e didática: `material_selection.py` resolve identidade e confirmação por slot pelos metadados reais; `advice_policy.py` impõe regras conservadoras únicas sobre Professor, IA e comparador; `teaching.py` gera explicações estruturadas ("o que observei / por que importa / proposta / custo / como conferir") reutilizando os dados do perfil ECC2 (câmara passiva `support_chamber_temp_control = 0`) e mecanismos térmicos de polímeros sem percentuais universais nem promessas de resistência mecânica.
- Graphify Local oficial: pacote Python `graphifyy`, comando `graphify`. O projeto contém a habilidade em `.codex/skills/graphify/`; para atualizar o grafo após mudanças, execute `graphify update .`. O resultado local fica em `graphify-out/` e não entra no Git.
- Understand Anything: execute a habilidade `/understand --language pt-BR` depois de mudanças relevantes. Seu grafo local fica em `.ua/knowledge-graph.json` e pode ser aberto com `/understand-dashboard`. Artefatos gerados não entram no Git.
- Find Skills: avaliar novas habilidades pela fonte, manutenção e relevância antes de instalar. A primeira busca encontrou o Graphify oficial; não adotamos habilidades genéricas de CAD para substituir a validação no fatiador.

- Mantenha sempre os utilitários de ciclo de vida da UI (`_POLL_HANDLE_ATTRS`, `_schedule_poll`, `_begin_poll`, `_continue_poll_if_active`, `_should_stop_polling` e `destroy()` com `_closing = True` em `ui.py`) ao adicionar novas filas/pollers, e feche explicitamente exceções `urllib.error.HTTPError` (`exc.close()`) em `ai.py`, `ai_client.py` e `updater.py` para evitar `ResourceWarning` e callbacks Tcl inválidos após fechamento da janela.
- Perfis em `profiles.py` usam cache em memória validado por assinatura `(mtime_ns, size)`; ao manipular JSONs diretamente em testes ou após alterações externas, use `clear_profile_cache()` quando necessário.
- Registro de aceitação técnica e pendências humanas/físicas do marco Tradutor + Professor: `docs/validation/tradutor-professor-acceptance.md`.
- Registro das otimizações de desempenho, instalador Inno Setup (`--onedir`) e auto-update: `docs/validation/performance-installer-updater.md`.

## Limites técnicos

## Regressão local e variantes

Para repetir a conversão e o fatiamento de exemplos locais após atualizar o ELEGOO Slicer:

```powershell
python scripts/regression_local.py --output "$env:TEMP\maker-elegoo-regression" caminho\exemplo.3mf
```

O script escolhe o primeiro perfil de máquina e processo compatível com o bico e um perfil de cada material. Confira os perfis selecionados antes de usar os resultados como comparação definitiva. A pasta de saída contém cópias convertidas e `regression.json`; escolha uma pasta fora do repositório. A interface oferece uma prévia de compatibilidade e variantes locais para qualidade, velocidade, economia e resistência. Os objetivos só alteram parâmetros presentes no perfil e cada variante precisa passar pelo fatiamento. Estimativas não comprovam acabamento nem resistência real.

- A opção Codex usa o CLI instalado e autenticado no próprio computador. O app mostra um resumo de campos permitidos e medições locais antes do consentimento, chama `codex exec` em diretório temporário vazio com sessão efêmera, sandbox de leitura e esquema JSON, e valida a resposta localmente. O 3MF, a malha, as vistas, o G-code e caminhos do projeto não entram no resumo. Recomendações de suporte são refatiadas antes de serem aplicáveis; orientação só aceita candidatas locais já fatiadas. A qualidade visual final ainda exige revisão no ELEGOO Slicer.

- O assistente opcional de orientação lê a malha localmente, mostra quatro vistas para escolher a frente e compara a posição atual com eixos principais e pequenas inclinações. A triagem mede apoio na mesa e risco frontal aproximado; recomenda mudança apenas após validação pelo ELEGOO Slicer e ganho frontal claro. A primeira versão aceita uma placa e uma instância de malha. A aplicação pede confirmação, salva uma nova cópia e fatia novamente. O 3MF, as vistas e o G-code não são enviados à IA. Confira visualmente o rosto e os suportes no fatiador; as medidas geométricas não provam qualidade estética.
- No exemplo local `Our+Lady+of+Guadalupe+Chibi.3mf`, com PLA, bico de 0,4 mm e processo 0,16 mm Optimal, a posição original passou na conversão e no fatiamento (2h18min03s; 28,69 g estimados). Uma rotação lateral também passou no fatiador (2h49min10s; 32,13 g), porém sua estimativa de apoio caiu de 1.216 para 5,4 mm². O assistente a rejeita e recomenda manter a figura em pé. Os valores são estimativas do fatiador instalado neste computador; a análise não prova acabamento melhor no rosto.

- `--allow-newer-file` permite que a CLI ELEGOO 2.4.2 leia projetos Bambu 2.6, mas alguns valores novos (`raft_first_layer_expansion` e `tree_support_wall_count` iguais a `-1`) precisam ser normalizados em uma cópia temporária. Os originais não são alterados.
- O perfil ELEGOO define temperatura, limites da máquina e velocidades. Transferimos apenas uma lista explícita de parâmetros de intenção do projeto.
- A malha é comparada por vértices e triângulos, com tolerância numérica de 0,0001 mm para arredondamentos do fatiador; mudanças maiores bloqueiam o estado de sucesso. O fatiador pode alterar a posição na mesa para caber na Centauri Carbon 2. Confira visualmente cores, suportes e posição antes da impressão.
- A API Gemini é opcional. Não se envia arquivo, malha ou G-code. O usuário aprova cada sugestão antes da nova exportação, e o fatiamento automático valida o resultado.
