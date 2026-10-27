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
