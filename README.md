# Create & Magic Lite

Et lille dansk samlingssted for vennernes Minecraft-server. Hjemmesiden ligger på GitHub Pages. Et separat, lokalt Python-program giver vennerne mulighed for at **starte** Minecraft-serveren med en fælles vennekode.

## Det kan vennerne

- Se serverstatus og spillerantal, kopiere adressen og starte serveren.
- Foreslå mods med et Modrinth- eller CurseForge-link. Begrundelse er valgfri.
- Se automatisk hentet titel/billede, når udbyderen tillader det, og stemme på forslag.
- Læse installationsguide, modpakkeoversigt og ændringer.

Der findes ingen fjernkommando til stop, genstart, konsol, filer eller installation af mods. Et forslag installerer aldrig automatisk et mod. Stop foregår fortsat med ejerens lokale `Stop-Server.ps1`.

## Drift

Frontend: `docs/`, almindelig HTML/CSS/JavaScript uden byggetrin. GitHub Pages udgiver `main` → `/docs`.

Backend: `agent/panel_agent.py`, Python 3.11+ med standardbiblioteket. Den lytter kun på `127.0.0.1:8766`. `supervisor.py` starter backend og en udgående Cloudflare-testtunnel. Når tunnelens `/health` virker, opdaterer programmet kun `docs/runtime.json` i dette repository via GitHub CLI.

Dette er en **gratis testforbindelse**, ikke en tunnel med oppetidsgaranti. Adressen bagved ændres ved genstart, mens GitHub-sidens adresse er den samme. Der kan gå et par minutter, før GitHub Pages viser en ny forbindelse. Computeren skal være tændt, vågen, have internet og være logget ind, så baggrundsprogrammet kører. Det kan ikke tænde en slukket computer. En fast Cloudflare-tunnel er næste skridt til mere stabil drift.

## Lokal opsætning

1. Installér officiel Python, GitHub CLI og cloudflared. Brug en almindelig Python-installation til panelet: Microsoft Store-udgaven kan isolere GitHub CLI fra Windows' legitimationslager. Log ind med `gh auth login`; brug Windows' legitimationslager. GitHub-adgang opbevares aldrig i siden eller `runtime.json`.
2. Opret privat tilstand **uden for repositoryet**:

   ```powershell
   python agent/panel_agent.py --init --private-dir C:\MinecraftPanelPrivate --server-dir C:\MinecraftServer --origin https://DITNAVN.github.io
   ```

3. Privatmappen får `config.json`, `friend-access-code.txt` og senere databasen `panel.sqlite3`. Del kun koden privat med vennerne. Begræns mappens Windows-rettigheder til ejeren og SYSTEM. Tilføj eventuelt `http://127.0.0.1:8765` som origin til en lokal forhåndsvisning.
4. Opret `supervisor.json` i privatmappen med absolutte lokale stier:

   ```json
   {
     "python_path": "C:\\Python311\\python.exe",
     "gh_path": "C:\\Tools\\gh.exe",
     "cloudflared_path": "C:\\Tools\\cloudflared.exe",
     "github_repo": "DITNAVN/create-magic-lite"
   }
   ```

5. Kør `Start-Panel.ps1 -PrivateDirectory C:\MinecraftPanelPrivate`. En genvej i Windows' Start-mappe kan starte panelet ved login. Det starter ikke Minecraft før en startanmodning.

Servermappen skal have den faste `Start-Server.ps1` og `server-status.json` fra den lokale servercontroller. Startscriptet må selv håndtere dubletter og normal serveropstart. Se `agent/README.md` for API-kontrakt og detaljer.

## Adgang og data

Vennekoden er tilfældig. Backend gemmer en scrypt-hash og udsteder kortlivede sessionstokens; browseren opbevarer token i sin session. Den offentlige kode indeholder ingen adgangskode, GitHub-token, database eller Minecraft-verden. API-kald kræver token, og ændringer kræver en tilladt browser-origin. Start er begrænset med lås og cooldown. Modmetadata hentes kun fra faste Modrinth/CurseForge-værter uden viderestillinger.

Dette er fælles adgang for en lille vennegruppe: navnene er selvvalgte, ikke verificerede konti. En ven kan vælge et andet navn, så stemmer er uformelle. Del ikke vennekoden offentligt. Forslag og stemmer gemmes lokalt i SQLite; tag backup af privatmappen.

CurseForge kan blokere automatisk hentning. I så fald bliver linket stadig gemt med et pladsholderbillede. Modrinth-forhåndsvisningen hentes fra det officielle projekt-API. Modpakkens delingslink skal opdateres i `runtime.json`, når et nyt CurseForge-link er genereret; gamle tidsbegrænsede links bruges ikke automatisk.

## Kontrol

```powershell
python -m unittest discover -s tests -v
node --check docs/app.js
```

Testene bruger isolerede midlertidige mapper og mocker serverstart. De må aldrig stoppe den rigtige server.

## Mulige næste tilføjelser

- Afstemning om næste fælles byggeprojekt.
- Kalender med aftalte spilaftener.
- Skærmbilleder af spillernes byggerier.
- Status på modforslag: foreslået, godkendt, afprøves og tilføjet.
- Individuelle invitationer, hvis gruppen vokser.

Officielle referencer: [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages), [Cloudflare-testtunneler](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), [fast Cloudflare-tunnel](https://developers.cloudflare.com/tunnel/get-started/).
