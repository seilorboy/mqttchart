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

Avaa <http://localhost:8082>. Sivulla näkyvät 100 uusinta tietokantaan
tallennettua viestiä ja MQTT-yhteyden tila. JSON esitetään sisennettynä,
teksti sellaisenaan ja muu binääridata base64-muodossa.
Tämä on raakaviestien taulukkonäkymä: kulutuskuvaajan laskenta edellyttää
mittarin viestimuodon ja yksiköiden määrittelyä.

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
