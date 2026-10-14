# MQTTChart — MQTT-vastaanotto ja selainkäyttöliittymä

Tämä erillinen käyttöönotto sisältää kaksi konttia: MySQL 8.4 ja sovelluksen,
joka kuuntelee ulkoista MQTT-palvelinta ja tarjoaa selainkäyttöliittymän.
MQTT-palvelinta ei käynnistetä tällä kokoonpanolla.
Projekti toimii itsenäisesti eikä tarvitse han-backend-projektia.

## Käynnistys

Aja projektin juuresta:

```sh
cp .env.mqtt.example .env.mqtt
```

Muokkaa `.env.mqtt`: aseta palvelimen osoite `MQTT_HOST`, portti, topic,
mahdolliset tunnukset sekä kaksi erillistä tietokantasalasanaa.
Osoitteen tulee olla kontista saavutettava DNS-nimi tai IP-osoite, ilman
`mqtt://`-etuliitettä. `localhost` tarkoittaa sovelluskonttia itseään.
Docker Desktopin isäntäkoneeseen voi viitata nimellä `host.docker.internal`.
TLS-yhteydessä aseta `MQTT_TLS=true` ja palvelimen TLS-portti (yleensä 8883).
TLS käyttää järjestelmän luotettuja varmenteita ja tarkistaa palvelimen nimen.
Yksityinen CA tai asiakasvarmenne edellyttää erillistä varmennemääritystä.

```sh
docker compose --env-file .env.mqtt -f docker-compose.mqtt.yml up -d --build
docker compose --env-file .env.mqtt -f docker-compose.mqtt.yml logs -f app
```

Avaa <http://localhost:8082> (tai asettamasi MQTT_WEB_PORT). Etusivulla ovat
Shelly 3EM -kuvaajat. Raakaviestit löytyvät `/messages`-sivulta: JSON esitetään
sisennettynä, teksti sellaisenaan ja muu binääridata base64-muodossa.

Oletuksena selainportti on käytettävissä vain isäntäkoneella. Etäpalvelimelle
voi tehdä SSH-tunnelin `ssh -L 8082:localhost:8082 käyttäjä@palvelin`.
`MQTT_WEB_BIND=0.0.0.0` avaa portin myös muille verkkoliittymille;
käyttöliittymässä ei ole kirjautumista. MySQL-porttia ei julkaista isäntäkoneelle.
Älä lisää `.env.mqtt`-tiedostoa versionhallintaan.

## Tallennus

Sovellus luo käynnistyessään `mqtt_data.mqtt_messages`-taulun, jos sitä ei ole:

| Sarake | Sisältö |
| --- | --- |
| id | Kasvava rivitunniste |
| received_at | Vastaanottohetki UTC-ajassa, ei mittarin mittausaika |
| topic | Viestin alkuperäinen topic |
| payload | Alkuperäiset tavut, myös tyhjä viesti sallitaan |
| qos | Vastaanotetun viestin QoS |
| retained | MQTT retained -lippu |

Tietokanta säilyy nimetyssä `mqtt_db_data`-volyymissa konttien uudelleenluonnin
yli. `down` säilyttää datan, mutta `down -v` poistaa volyymin ja datan.
Viestejä ei poisteta automaattisesti; levytilaa ja varmuuskopioita on ylläpidettävä.
Tietokantasalasanat alustetaan tyhjään volyymiin: niiden muuttaminen
env-tiedostossa ei vaihda jo luodun tietokannan salasanoja.

Tilaus käyttää QoS 1:tä ja pysyvää MQTT 3.1.1 -istuntoa. Anna jokaiselle
asennukselle oma pysyvä `MQTT_CLIENT_ID`. QoS 1 -viesti kuitataan vasta
tietokantatransaktion valmistuttua. Tallennusvirhe käynnistää sovelluskontin
uudelleen. Välittäjän on säilytettävä istunto ja julkaisijan käytettävä vähintään
QoS 1:tä, jotta viestejä voidaan toimittaa katkon jälkeen.
QoS 0 -viestejä voi kadota. Uudelleentoimitus tai retained-viestin uusi tilaus
voi tallentaa saman sisällön uudelleen: täsmälleen kerran -tallennusta ei luvata.
Katso myös [Paho-asiakkaan dokumentaatio](https://eclipse.dev/paho/clients/python/docs/).

## Tarkistaminen

Julkaise omaan määritettyyn topiciin esimerkiksi `{"energy_kwh":12345.67}`
MQTT-asiakkaalla. Varmista, että se ilmestyy selaimeen ja säilyy tämän jälkeen:

```sh
docker compose --env-file .env.mqtt -f docker-compose.mqtt.yml restart app
curl http://localhost:8082/api/messages
```

`GET /api/messages?limit=100` palauttaa uusimmat viestit (enintään 500).
`GET /health` tarkistaa tietokannan ja raportoi MQTT-tilan; kontin terveystarkistus
ei edellytä MQTT-yhteyttä, jotta tallennettuja tietoja voi lukea myös katkon aikana.


## Shelly 3EM: aurinkosähkön kuvaajat

Etusivu näyttää vaiheiden L1–L3 tehot (W), virrat (A) ja jännitteet (V)
kolmessa kuvaajassa. Vaiheindeksit MQTT-topiceissa ovat 0, 1 ja 2.
Näytettävän laitteen oletus on `shellies/shellyem3-C8C9A316D627`.
Asetukset `.env.mqtt`-tiedostossa:

```dotenv
MQTT_TOPIC=shellies/shellyem3-C8C9A316D627/emeter/#
SHELLY_TOPIC_PREFIX=shellies/shellyem3-C8C9A316D627
```

`MQTT_TOPIC` ohjaa vastaanottoa; `SHELLY_TOPIC_PREFIX` valitsee kuvaajissa
näytettävän laitteen. Myös laajempi tilaus, kuten `shellies/#`, käy.
Käytetyt topicin loppuosat ovat `/emeter/<vaihe>/power`, `/current`, `/voltage`,
`/total` ja `/total_returned`. **Teho tulee `/power`-topicista, ei `/current`-topicista.**
[Shellyn Gen1 API](https://shelly-api-docs.shelly.cloud/gen1/#shelly-3em-mqtt)
määrittelee yksiköiksi W, A, V ja energialaskureille Wh.

- Aikavälit: viimeinen tunti, 6 tuntia ja 24 tuntia.
- Kuvaajissa näytekeskiarvot vastaavasti 10, 60 ja 300 sekunnin jaksoissa.
- Päivitys 15 sekunnin välein. Pisteen kohdalla hiirellä näkyvät arvo ja aika.
- Lukuarvot ovat viimeisimmät valitulla aikavälillä vastaanotetut mittaukset.
- Yli kaksi minuuttia vanhat lukemat merkitään vanhoiksi.
- Puuttuva mittaus näkyy viivana (—), ei nollana; tyhjät jaksot katkaisevat käyrän.
- Energialaskurit näytetään erikseen kWh-muodossa (Wh / 1000), vastaanottoaikoineen.
  Ne ovat kumulatiivisia lukemia, eivät valitun aikavälin energiamääriä.
- Tehon etumerkkiä ei muuteta. Tuotantosuunta riippuu mittarin kytkennästä;
  `total_returned` ei yksin todista kohteen koko aurinkosähkötuotantoa.

Kuvaajat käyttävät olemassa olevaa `mqtt_messages`-taulua vastaanottoajan mukaan.
Uutta taulua tai datan siirtoa ei tarvita. Energialukemia haetaan samalta valitulta
aikaväliltä kuin kuvaajia. Näkymä toimii ilman ulkoisia JavaScript-CDN-palveluita.
`GET /api/solar?hours=6` palauttaa kuvaajadatan ja viimeisimmät lukemat.

Päivitys palvelimella, kun muutokset on lähetetty GitHubiin:

```sh
git pull --ff-only
sudo docker compose --env-file .env.mqtt -f docker-compose.mqtt.yml up -d --build
```

Porttiasetus `.env.mqtt`-tiedostossa säilyy, esimerkiksi `MQTT_WEB_PORT=8083`.
Tietokantavolyymia ei pidä poistaa päivityksessä.

Kehitystestit:

```sh
python -m pip install -r mqtt/requirements.txt
python -m unittest discover -s tests -p 'test_*.py'
```

## Julkaisu polussa /mqttchart/ nykyisten palvelujen rinnalla

Sovellus tukee sekä suoraa osoitetta `http://localhost:8083/` että osoitetta
`https://hanmeter.duckdns.org/mqttchart/`. Nginx poistaa pyynnöstä `/mqttchart`-
etuliitteen ja lähettää `X-Forwarded-Prefix: /mqttchart`-otsikon.
Sovellus käyttää sitä sivujen, staattisten tiedostojen ja API-pyyntöjen osoitteissa.
Ilman otsikkoa sovellus toimii edelleen domainin juuressa.

Mallimääritys on `nginx/hanmqtt.conf`. Palvelimella:

```sh
sudo cp nginx/hanmqtt.conf /etc/nginx/sites-available/hanmqtt.conf
```

Lisää **olemassa olevan** `hanmeter.duckdns.org`-domainin HTTPS-`server`-lohkon
sisään seuraava rivi (vain kerran):

```nginx
include /etc/nginx/sites-available/hanmqtt.conf;
```

Älä luo uutta samannimistä HTTPS-server-lohkoa. Älä linkitä `hanmqtt.conf`-tiedostoa
`sites-enabled`-kansioon: se sisältää vain `location`-lohkot ja kuuluu serverin
sisälle. Säilytä nykyiset `/`, `/api/` ja `/sankey` -ohjaukset ennallaan.
`location ^~ /mqttchart/` käsittelee ainoastaan uuden sovelluksen pyynnöt.
Jos MQTTChart käyttää eri porttia, muuta mallin `proxy_pass` vastaamaan sitä.

Säilytä `MQTT_WEB_BIND=127.0.0.1`, jotta sovellusportti on vain paikallisesti
käytettävissä ja ulkoiset pyynnöt tulevat otsikon asettavan Nginxin kautta.
Sovellus luottaa yhteen `X-Forwarded-Prefix`-otsikon asettavaan välityspalvelimeen.
Raakaviestien JavaScript on erillisessä tiedostossa, joten myös se toimii
`script-src 'self'` -suojausasetuksella.

Päivitä kontti ja lataa Nginxin asetukset:

```sh
sudo docker compose --env-file .env.mqtt -f docker-compose.mqtt.yml up -d --build
sudo nginx -t && sudo systemctl reload nginx
```

Tarkista palvelimella:

```sh
curl -fsS http://127.0.0.1:8083/health
curl -fsS -H 'X-Forwarded-Prefix: /mqttchart' http://127.0.0.1:8083/ | grep /mqttchart/
curl -fsS https://hanmeter.duckdns.org/mqttchart/health
```

Kuvaajat: `/mqttchart/`. Raakaviestit: `/mqttchart/messages`.
Tarkista myös nykyinen `/sankey` selaimessa päivityksen jälkeen.
