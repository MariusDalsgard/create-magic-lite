# Create & Magic Lite

Et lille dansk samlingssted for vennernes Minecraft-server. Hjemmesiden ligger på GitHub Pages. Et separat, lokalt Python-program giver vennerne mulighed for at **starte** Minecraft-serveren med en fælles vennekode.

## Det kan vennerne

- Se serverstatus og spillerantal, kopiere adressen og starte serveren.
- Foreslå mods med et Modrinth- eller CurseForge-link. Begrundelse er valgfri.
- Se automatisk hentet titel/billede, når udbyderen tillader det, og stemme på forslag.
- Læse installationsguide, modpakkeoversigt og ændringer.
- Hente modpakken direkte som en CurseForge-importfil, søge i dens komplette modliste og se tilføjede, opdaterede og fjernede mods for hver udgave.

Der findes ingen fjernkommando til stop, genstart, konsol, filer eller installation af mods. Et forslag installerer aldrig automatisk et mod. Stop foregår fortsat med ejerens lokale `Stop-Server.ps1`.

## Drift

Frontend: `docs/`, almindelig HTML/CSS/JavaScript uden byggetrin. GitHub Pages udgiver `main` → `/docs`.

Backend: `agent/panel_agent.py`, Python 3.11+ med standardbiblioteket. Den lytter kun på `127.0.0.1:8766`. `supervisor.py` starter backend og en udgående Cloudflare-testtunnel. Når tunnelens `/health` virker, opdaterer programmet kun `docs/runtime.json` i dette repository via GitHub CLI.

Dette er en **gratis testforbindelse**, ikke en tunnel med oppetidsgaranti. Adressen bagved ændres ved genstart, mens GitHub-sidens adresse er den samme. Der kan gå et par minutter, før GitHub Pages viser en ny forbindelse. Computeren skal være tændt, vågen, have internet og være logget ind, så baggrundsprogrammet kører. Det kan ikke tænde en slukket computer. En fast Cloudflare-tunnel er næste skridt til mere stabil drift.

## Lokal opsætning

1. Installér officiel Python, GitHub CLI og cloudflared. Brug en almindelig Python-installation til panelet. GitHub CLI skal have en fast konfigurationsmappe uden for AppData: Windows-apps kan ellers bruge en anden mappe end programmer startet ved Windows-login. GitHub-adgang opbevares aldrig i siden eller `runtime.json`.
2. Opret privat tilstand **uden for repositoryet**:

   ```powershell
   python agent/panel_agent.py --init --private-dir C:\MinecraftPanelPrivate --server-dir C:\MinecraftServer --origin https://DITNAVN.github.io
   ```

3. Privatmappen får `config.json`, `friend-access-code.txt` og senere databasen `panel.sqlite3`. Del kun koden privat med vennerne. Begræns mappens Windows-rettigheder til ejeren og SYSTEM. Tilføj eventuelt `http://127.0.0.1:8765` som origin til en lokal forhåndsvisning.
4. Opret mappen `C:\MinecraftPanelPrivate\gh-config`, sæt `$env:GH_CONFIG_DIR='C:\MinecraftPanelPrivate\gh-config'`, og log ind med `gh auth login` i samme PowerShell-vindue. Brug Windows' legitimationslager; læg aldrig et token i hjemmesiden. Opret derefter `supervisor.json` i privatmappen med absolutte lokale stier:

   ```json
   {
     "python_path": "C:\\Python311\\python.exe",
     "gh_path": "C:\\Tools\\gh.exe",
     "gh_config_dir": "C:\\MinecraftPanelPrivate\\gh-config",
     "cloudflared_path": "C:\\Tools\\cloudflared.exe",
     "github_repo": "DITNAVN/create-magic-lite"
   }
   ```

5. Kør `Start-Panel.ps1 -PrivateDirectory C:\MinecraftPanelPrivate`. En genvej i Windows' Start-mappe kan starte panelet ved login. Det starter ikke Minecraft før en startanmodning.

Ved fejl viser `panel-private/supervisor-status.json` seneste udgivelsesforsøg og en fejlkategori uden legitimationsdata. Hvis GitHub-login skal gentages, skal den samme `GH_CONFIG_DIR` bruges. Genstart panelets baggrundsprogram efter ændringer i `supervisor.json`.

Servermappen skal have den faste `Start-Server.ps1` og `server-status.json` fra den lokale servercontroller. Startscriptet må selv håndtere dubletter og normal serveropstart. Se `agent/README.md` for API-kontrakt og detaljer.

## Adgang og data

Vennekoden er tilfældig. Backend gemmer en scrypt-hash og udsteder kortlivede sessionstokens; browseren opbevarer token i sin session. Den offentlige kode indeholder ingen adgangskode, GitHub-token, database eller Minecraft-verden. API-kald kræver token, og ændringer kræver en tilladt browser-origin. Start er begrænset med lås og cooldown. Modmetadata hentes kun fra faste Modrinth/CurseForge-værter uden viderestillinger.

Dette er fælles adgang for en lille vennegruppe: navnene er selvvalgte, ikke verificerede konti. En ven kan vælge et andet navn, så stemmer er uformelle. Del ikke vennekoden offentligt. Forslag og stemmer gemmes lokalt i SQLite; tag backup af privatmappen.

CurseForge kan blokere automatisk hentning. I så fald bliver linket stadig gemt med et pladsholderbillede. Modrinth-forhåndsvisningen hentes fra det officielle projekt-API. Feltet `packShareUrl` i `docs/runtime.json` på GitHub kan pege på enten et midlertidigt `/minecraft/share/`-link eller en fast `/minecraft/modpacks/<slug>`-side. Når pakken er udgivet, bruges den faste side til alle nye versioner. Venner installerer projektet én gang og vælger derefter opdateringer i CurseForge-appen; en gammel profil fra en delingskode kan kræve denne første installation. Supervisoren læser den aktuelle fil fra GitHub og bevarer modpakkelinket, når tunneladressen opdateres.

Mens et nyt CurseForge-projekt afventer godkendelse, kan dets faste URL gemmes med `packApprovalPending: true` i samme fil. Siden viser da en besked om godkendelsen. Den direkte ZIP-download fra hjemmesiden er stadig tilgængelig. Sæt feltet til `false` (eller fjern det), når projektet og en downloadbar udgave faktisk er offentligt tilgængelige.

## Modpakke, database og opdateringer

Den faktiske CurseForge-importfil ligger i `docs/downloads/`. ZIP-filen indeholder modreferencer og gennemgåede indstillinger; CurseForge henter selv de tilhørende mods ved import. Den lille filstørrelse er derfor forventet. Modpakken, modlisten og historikken kan hentes, selv når servercomputeren er slukket.

Udgaver og deres komplette modinventar gemmes i egne tabeller i den eksisterende private `panel.sqlite3`. Hver udgivelse sammenlignes automatisk med den foregående og registrerer tilføjede, opdaterede og fjernede filer. Første udgave sammenlignes med den dokumenterede profil fra før opdateringen: 25 nye mods, 58 mods i alt samt 2 ressourcepakker og 1 shader. Dette tidligere inventar er et sammenligningsgrundlag, ikke en tidligere offentlig udgave. Forslag og stemmer bevares.

`docs/releases.json` er en offentlig eksport fra databasen og indeholder kun udgivelser og offentlige modoplysninger. Hjemmesiden læser denne eksport uden login. Databasen, navne på venner, stemmer og private profiler lægges ikke på GitHub. SQLite-backup tages før første katalogmigration. Versionsnumre kan ikke overskrives med andet indhold.

Når en ny, afprøvet udgave er eksporteret og renset for private filer, kan ejeren forberede hjemmesidens opdatering med:

```powershell
.\Update-Modpack.ps1 -Archive 'C:\ModpackReleases\Create-Magic-Lite-1.1.0.zip' -Summary 'Nye bygninger og udstyr.'
```

Kommandoen kontrollerer eksporten mod den lokale CurseForge-profil, gemmer udgaven i databasen og genererer ZIP-download og ændringshistorik. Derefter committes og pushes de ændrede `docs/releases.json` og `docs/downloads/`-filer til GitHub, som udgiver siden. Samme udgave kan genkøres sikkert, hvis udgivelsen blev afbrudt. Den almindelige venneadgang giver ikke adgang til at ændre modpakken eller databasen.

Venner henter ZIP-filen og importerer den i CurseForge. En profil importeret fra ZIP skal også opdateres manuelt med næste ZIP. Når CurseForge-projektet er godkendt, kan venner installere pakken fra den faste projektside for at få fremtidige versioner via CurseForges opdateringsfunktion.

## Kontrol

```powershell
python -m unittest discover -s tests -v
node --check docs/app.js
node --test tests/test_frontend.cjs
```

Testene bruger isolerede midlertidige mapper og mocker serverstart. De må aldrig stoppe den rigtige server.
Frontendtestene kontrollerer indlæsning, søgning efter ældre forslag, gemt sortering og bevarelse af forslag ved forbindelsesfejl eller forsinkede svar.

## Mulige næste tilføjelser

- Afstemning om næste fælles byggeprojekt.
- Kalender med aftalte spilaftener.
- Skærmbilleder af spillernes byggerier.
- Status på modforslag: foreslået, godkendt, afprøves og tilføjet.
- Individuelle invitationer, hvis gruppen vokser.

Officielle referencer: [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages), [Cloudflare-testtunneler](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), [fast Cloudflare-tunnel](https://developers.cloudflare.com/tunnel/get-started/).
