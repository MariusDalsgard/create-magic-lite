# Lokal start-agent

Agenten kører på servercomputeren med Python 3.11+ og bruger kun standardbiblioteket. Den lytter udelukkende på `127.0.0.1:8766`. En udgående HTTPS-tunnel forbinder GitHub-siden med agenten; Windows-firewallen skal ikke åbne en administrationsport.

## Første opsætning

Kør fra projektmappen. Erstat GitHub-brugernavnet med den rigtige konto:

```powershell
python agent/panel_agent.py --init --origin https://GITHUB-BRUGER.github.io --origin http://127.0.0.1:8765
```

Standardplaceringen for privat tilstand er `C:\Users\Marius\MinecraftServers\Create-Magic-Lite\panel-private`. Brug `--private-dir` og `--server-dir` ved en anden placering. Privat tilstand afvises, hvis mappen ligger inde i dette Git-repository. Første opsætning overskriver aldrig en eksisterende konfiguration eller adgangskode.

`friend-access-code.txt` indeholder den tilfældigt genererede vennekode. Del den privat med vennerne. Koden, `config.json`, databasen og logfilerne må aldrig lægges på GitHub. Konfigurationen indeholder en saltet scrypt-hash; klartekstkoden gemmes separat for ejerens skyld.

```powershell
python agent/panel_agent.py --private-dir "C:\Users\Marius\MinecraftServers\Create-Magic-Lite\panel-private"
```

Agenten starter **ikke** Minecraft ved sin egen opstart. Minecraft startes kun ved en godkendt startanmodning. Stop/genstart af selve agenten stopper heller ikke Minecraft. Ejerens eksisterende `Stop-Server.ps1` forbliver den lokale måde at gemme verden og stoppe spilserveren på.

## Adgang og drift

- `allowed_origins` indeholder præcise origins uden afsluttende skråstreg eller sti. GitHub Pages-origin er eksempelvis `https://navn.github.io`, uanset repository-stien.
- Brug HTTPS til den offentlige tunnel. Kun lokal udvikling tillader HTTP på `localhost` eller `127.0.0.1`.
- Hver ven logger ind med et valgfrit visningsnavn og den delte vennekode. Navne er **ikke verificerede konti**; afstemningen bruger navnet og er beregnet til en lille, betroet vennegruppe.
- Sessioner udløber efter 24 timer og glemmes ved genstart af agenten. Browseren skal derefter logge ind igen.
- Start er fast kodet til den lokale `Start-Server.ps1` uden argumenter fra klienten. Der findes ingen stop-, genstart-, konsol- eller fil-API.
- Status kontrollerer Minecraft-protokollen samt Java/managerens procesidentitet. Parallelle startklik bliver til højst én start. En 120 sekunders startpause gemmes i SQLite og overlever agentgenstart.
- Forslag og stemmer gemmes i `panel.sqlite3`. Sikkerhedskopiér den private mappe, mens agenten er stoppet, eller brug SQLites backupfunktion.
- Ved tilbagekaldelse af den delte kode: stop agenten, flyt den gamle `config.json` og `friend-access-code.txt` til en privat sikkerhedskopi, kør `--init` igen med de samme origins, og gendan eventuelle ekstra supervisorfelter i den nye konfiguration. Behold `panel.sqlite3`. Alle gamle sessioner ophører ved genstart.
- En Quick Tunnel er en testforbindelse med skiftende adresse. Supervisoren skal offentliggøre den nye API-adresse på GitHub. Hvis computeren er slukket, i dvale eller offline, kan vennerne ikke starte serveren.

## HTTP-kontrakt

Alle API-svar er JSON med `Cache-Control: no-store`. Fejl har formen `{"error":"kode","message":"Dansk besked"}`. Alle POST-anmodninger kræver en tilladt `Origin` og `Content-Type: application/json`; alle API'er undtagen login kræver `Authorization: Bearer <token>`.

| Metode og sti | Indhold | Svar |
| --- | --- | --- |
| `GET /health` | Intet, ingen login | `{ok:true}`; ingen systemoplysninger |
| `POST /api/login` | `{name,code}` | `{token,name,expires_at}`; udløbstid som Unix-sekunder |
| `GET /api/status` | Intet | `{state,players:{online,max},version,address,can_start,checked_at}` |
| `POST /api/start` | `{}` | `{state,started,message}` |
| `POST /api/preview` | `{url}` | `{url,title,description,image_url,source,preview_available}` |
| `GET /api/suggestions` | Intet | `{suggestions:[suggestion,...]}`; højst 200, flest stemmer først |
| `POST /api/suggestions` | `{url,reason?}` | `{suggestion,duplicate}` |
| `POST /api/suggestions/<id>/vote` | `{}` | `{suggestion}`; tilføjer/fjerner egen stemme |

En `suggestion` har felterne `id`, `url`, `title`, `description`, `image_url`, `source`, `reason`, `author`, `created_at`, `votes`, `voted`. Tider bortset fra sessionudløb er UTC ISO-strenge. `state` er `online`, `starting`, `stopping` eller `offline`. `image_url` kan være `null`.

Modlinks accepteres kun som `https://modrinth.com/mod/<slug>` eller `https://www.curseforge.com/minecraft/mc-mods/<slug>`. Sporingsparametre fjernes. Metadata hentes fra Modrinths officielle API eller CurseForges Open Graph-tags. Eksterne omdirigeringer følges ikke, svarstørrelser er begrænsede, og billeder begrænses til udvalgte udbyder-CDN'er. Hvis metadataudbyderen er utilgængelig, bevares det gyldige forslag med et afledt navn og uden billede. Et forslag installerer aldrig et mod automatisk.

Frontend skal bruge `textContent` til tekst, ikke `innerHTML`. Vis en reserveillustration, når `image_url` mangler. Undgå at gemme vennekoden i browserlager; et kortlivet sessiontoken er tilstrækkeligt.

## Kontrol

```powershell
python -m unittest discover -s tests -p test_agent.py -v
```

Testene bruger midlertidige private mapper og en lokal HTTP-testserver. Minecraft-start og metadatahentning er erstattet af teststubs. De kontrollerer adgang, CORS, URL- og billedbegrænsninger, fravær af stop/genstart, argumentafvisning, parallel start, vedvarende startpause, dubletter og stemmer.

## Offentligt modkatalog og udgivelser

`pack_catalog.py` gemmer modpack-udgivelser i egne `pack_catalog_meta`- og `pack_catalog_releases`-tabeller i den samme private `panel.sqlite3`. Forslag, stemmer og agentens øvrige tabeller ændres ikke. Før den første migration oprettes en konsistent SQLite-sikkerhedskopi i `pack-catalog-backups/` under den private mappe. Denne mappe og databasen skal fortsat holdes uden for Git-repositoryet.

En lokal kommando importerer en gennemgået CurseForge-ZIP og en offentlig metadata-liste:

```powershell
python -B scripts/publish_pack.py --private-dir "C:\Users\Marius\MinecraftServers\Create-Magic-Lite\panel-private" --archive "C:\udgivelser\Create-Magic-Lite-1.0.0.zip" --metadata "C:\udgivelser\metadata.json" --baseline "C:\udgivelser\foer-opdatering.json" --summary "Nye dyr, bygninger og udstyr."
```

`--baseline` er valgfri og bruges kun ved den første reelle udgivelse. Den beskriver pakken før opdateringen og bliver ikke til en opdigtet udgivelse. Senere udgaver sammenlignes med den senest importerede udgave. Brug `--docs-dir` til en anden offentlig outputmappe end repositoryets `docs/`.

Metadata og baseline er JSON-lister med `project_id`, `file_id`, `name`, `version`, `kind` og `url`. `kind` er `mod`, `resourcepack` eller `shader`. `image_url` er valgfrit og kan være `null`; `environment` er valgfrit og kan være `client`, `server`, `client-and-server` eller `unknown`. Kun disse offentlige felter accepteres. Projektlinks skal være HTTPS-links til den tilsvarende kategori på CurseForge eller Modrinth, og billeder skal være på ForgeCDN eller Modrinths CDN.

Importen kontrollerer, at manifestets filreferencer præcis matcher metadata. Rå JAR-filer, private mapper, symlinks, dubletter og usikre ZIP-stier afvises. De tilladte ekstra filer er `modlist.html`, `overrides/README.txt`, de tre configs `DistantHorizons.toml`, `alexscaves-client.toml`, `oculus.properties` og MakeUp-UltraFasts versionsbestemte `.zip.txt`-shaderindstillinger. Flere overrides kræver en bevidst ændring af allowlisten.

Versionsnummeret kommer fra `manifest.version`; Minecraft-version og Forge-loader kommer også fra manifestet. Hver udgave gemmer hele listen samt `added`, `updated` og `removed`; opdaterede elementer har `previous_version`. Ændringer i billeder eller miljøangivelser alene tælles ikke som en modopdatering. En eksisterende udgave er uforanderlig: samme ZIP og metadata er en idempotent genimport med det oprindelige tidspunkt, mens ændrede bytes, metadata eller en angivet ny beskrivelse afvises.

Kommandoen kopierer ZIP'en til `docs/downloads/Create-Magic-Lite-<version>.zip` og udskifter `docs/releases.json` atomisk. Snapshotformatet er `{schema_version:1, latest_version, releases:[...]}`, nyeste import først. Hver udgave indeholder `version`, `published_at` i UTC, `minecraft_version`, `loader` såsom `forge-47.4.28`, `download_url`, `sha256`, de tre kategoritællinger, `summary`, `changes` og `items`. Snapshot og downloads kan offentliggøres på GitHub Pages og fungerer, når servercomputeren er slukket; der kræves hverken login, en ny API eller en genstart af agenten. Kommandoen uploader eller committer ikke automatisk.

Hvis en eksport fejler efter databasecommit, kan den samme import køres igen for at genskabe snapshot og download uden en dubletudgivelse. Fejloverskrifter viser ikke databaseindhold eller private filer.

```powershell
python -B -m unittest discover -s tests -p test_pack_catalog.py -v
```

Disse tests bruger udelukkende midlertidige databaser, ZIP-filer og dokumentmapper. De ændrer ikke den faktiske server, modpack eller produktionsdatabase.
