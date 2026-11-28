# Pull1sec

Bir sosyal medya bağlantısı yapıştır, videoyu al. Kendi makinenizde çalışan,
**wifi üzerinden erişilebilen** bir video indirici. Motor
[yt-dlp](https://github.com/yt-dlp/yt-dlp) olduğu için YouTube, TikTok,
Instagram, X (Twitter), Facebook, Reddit, Vimeo, Twitch, Bilibili ve
[1800'den fazla site](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
desteklenir.

Ağa açık olduğu için **giriş zorunludur**. Kayıt ekranı yoktur: hesabı yalnızca
makinenin başındaki kişi, CLI veya TUI üzerinden oluşturur. Sunucu düz HTTP
yayın yaptığından parola hiçbir zaman ağdan geçmez — ayrıntısı
[Giriş ve güvenlik](#giriş-ve-güvenlik) bölümünde.

---

## Hızlı başlangıç

Gerekenler: **Python 3.11+** ve **ffmpeg**. Python bağımlılıkları kendi özel
ortamına otomatik kurulur; elle sanal ortam oluşturmanız ya da etkinleştirmeniz
gerekmez.

### npm

```bash
npm install -g pull1sec
pull1sec user set     # hesabı oluştur (şifreyi sen belirle)
pull1sec              # sunucuyu başlat
```

Paket ilk çalıştırmada `~/.local/share/pull1sec/venv` altında özel bir Python
ortamı kurar ve bağımlılıkları oraya yükler. Proje dizini, etkin bir venv ya da
`pip` gerekmez. Güncelleme: `npm update -g pull1sec`. Kurmadan denemek için:
`npx pull1sec`.

Sistemde `python3` yoksa `PULL1SEC_PYTHON=/yol/python3` ile yolu belirtin.
Kurulum kökünü değiştirmek için `PULL1SEC_HOME` kullanılır.

npm registry'deki sürüm henüz yayında değilse doğrudan repodan kurun:

```bash
npm install -g github:l1secx/pull1sec
```

### curl

```bash
curl -fsSL https://raw.githubusercontent.com/l1secx/pull1sec/main/install.sh | bash
pull1sec user set
pull1sec
```

Betik uygulamayı `~/.local/share/pull1sec/app` altına açar, bağımlılıkları
`~/.local/share/pull1sec/venv` içine kurar ve `~/.local/bin/pull1sec`
başlatıcısını yazar. `~/.local/bin` PATH'te değilse betik bunu söyler.

Kaldırmak için:

```bash
curl -fsSL https://raw.githubusercontent.com/l1secx/pull1sec/main/install.sh | bash -s -- --uninstall
```

> `curl | bash` uzaktan kod çalıştırır. Betiği çalıştırmadan önce
> [inceleyin](https://github.com/l1secx/pull1sec/blob/main/install.sh).

### Kaynaktan (geliştirme)

```bash
uv sync                         # bağımlılıkları kurar
uv run pull1sec user set        # hesabı oluştur
uv run pull1sec                 # sunucuyu başlat
```

Alternatifler:

```bash
./run.sh              # proje sanal ortamıyla başlatır (uv run kullanır)
uv run pull1sec       # proje sanal ortamındaki komut
```

Başlatınca adresleri yazar:

```
  Pull1sec 1.0.0
    yerel     http://127.0.0.1:8787
    ağ        http://192.168.1.26:8787
    kullanıcı kerem   ·   oturum ömrü 30 gün   ·   açık oturum 0
```

Telefondan ya da aynı wifi'deki başka bir cihazdan **ağ** satırındaki adresi aç,
kullanıcı adı ve şifreyle gir. Arayüz Türkçe/İngilizce ve açık/koyu tema
destekler. Dosyalar sunucuda kalır, dışarıya hiçbir şey gönderilmez; indirilen
dosyalar varsayılan olarak bir saat sonra silinir.

`uv` yoksa düz pip ile:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m pull1sec user set && python -m pull1sec
```

## Wifi'ye açmak

Sunucu zaten tüm arayüzlere bağlanır (`PULL1SEC_HOST` varsayılanı `0.0.0.0`),
yani ek bir ayar gerekmez. Erişimi engelleyen şey neredeyse her zaman güvenlik
duvarıdır.

**1. Portu yalnızca kendi alt ağınıza açın.** Bu makinede `ufw` etkin olduğu için
kural eklenmezse telefon bağlanamaz:

```bash
# Alt ağı bulun (örnek çıktı: 192.168.1.26/24 → alt ağ 192.168.1.0/24)
ip -4 -o addr show scope global | grep wl

# Sadece yerel ağa izin verin
sudo ufw allow from 192.168.1.0/24 to any port 8787 proto tcp comment 'Pull1sec'
sudo ufw status | grep 8787
```

**2. Adresi öğrenin ve telefondan açın:**

```bash
pull1sec url
# yerel  http://127.0.0.1:8787
# ağ     http://192.168.1.26:8787      ← telefonun wifi'deyken açacağı adres
```

**Açılmıyorsa sırayla kontrol edin:**

- Telefon **aynı** wifi ağında mı (misafir ağı ayrı bir ağdır)?
- Router'da "AP isolation" / "client isolation" / "izolasyon" kapalı mı? Açıksa
  cihazlar birbirini hiç göremez.
- Bilgisayarda VPN açık mı? Kapatın; trafiği tünele alır.
- Başka bir port kullanıyorsanız ufw kuralını da ona göre yazın.
- `ss -ltnp | grep 8787` çıktısı `0.0.0.0:8787` olmalı — `127.0.0.1:8787` ise
  `PULL1SEC_HOST=127.0.0.1` ayarlı demektir.

### Sürekli açık kalsın

`deploy/pull1sec.service` bir systemd kullanıcı servisidir; oturum açık olmasa da
sunucu ayakta kalır:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/pull1sec.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pull1sec
systemctl --user status pull1sec      # durum
journalctl --user -u pull1sec -f      # canlı günlük
loginctl enable-linger "$USER"        # oturum kapanınca da çalışsın
```

Port 8787 ayrıcalıksız olduğu için servis root gerektirmez. Kapatmak için
`systemctl --user disable --now pull1sec`.

## Nasıl kullanılır

1. Bağlantıyı yapıştır (**Yapıştır** butonu panodan okur) ve **Analiz et**.
2. Önizlemede başlık, platform, süre ve mevcut çözünürlükler görünür.
3. **Video** ya da **Ses** modunu seç; kalite listesinden bir çözünürlük seç.
4. **İndir**'e bas. Etkinlik panelinde ilerleme, hız ve kalan süre canlı akar.
5. İş bitince **Kaydet** dosyayı tarayıcıya indirir.

Özel hesaplara, yaş kısıtına veya "bot değilim" kontrolüne takılan gönderiler
için **Giriş gerektiren gönderiler** bölümünden "Çerezleri tarayıcıdan al"
seçeneğini kendi tarayıcınıza çevir. O tarayıcıda ilgili siteye giriş yapmış
olmanız gerekir.

## Giriş ve güvenlik

### Hesap yönetimi

Kayıt yoktur. Hesap yalnızca makinenin başından, iki arayüzle oluşturulur ve
değiştirilir:

```bash
# Şifreyi belirle / değiştir (mevcut şifre sorulur)
pull1sec user set

# Kullanıcı adını da değiştir
pull1sec user set --username kerem

# Tam ekran arayüz: menüden şifre/kullanıcı adı değiştir, oturumları yönet
pull1sec tui
```

TUI açılışta ağ adresini, kullanıcıyı, açık oturum sayısını ve şifre
parametrelerini gösterir; `1` şifre, `2` kullanıcı adı, `3` oturum listesi,
`4` tüm oturumları kapatır. Her değişiklikten önce **mevcut şifre** sorulur.

### Şifre neden ağdan geçmiyor

Sunucu LAN üzerinde düz HTTP ile yayın yapar, yani klasik bir "şifreyi POST
et" akışı kabloyu dinleyen biri tarafından okunabilirdi. Bunun yerine
tek kullanımlık `nonce` tabanlı bir challenge–response kullanılır:

1. Tarayıcı `POST /api/auth/challenge` ile **tek kullanımlık** bir nonce, tuz ve
   tur sayısı ister.
2. Tarayıcı paroladan yerel olarak `verifier = PBKDF2-SHA256(parola, tuz)`
   türetir ve nonce ile karıştırıp `proof = PBKDF2-SHA256(verifier, nonce)`
   üretir.
3. Sunucuya yalnızca `proof` gider. Parola cihazdan hiç çıkmaz.

Bunun pratik sonuçları:

| | |
| --- | --- |
| **Diskte** | Yalnızca tuzlu, tek yönlü `PBKDF2-SHA256` (210.000 tur) doğrulayıcısı var. Parola dosyada yok. |
| **Kabloda** | Parola yok; sadece o anki nonce'a bağlı bir kanıt var. |
| **Tekrar oynatma** | Nonce tek kullanımlık ve 120 saniyede düşer; aynı kanıt ikinci kez çalışmaz. |
| **Pass-the-hash** | Dosyadaki doğrulayıcı, olduğu gibi gönderilirse **reddedilir** (kanıt nonce ile karıştırılmadığı için). |
| **Kayıt dosyası izinleri** | `~/.local/state/pull1sec/auth.json`, `0600`; dizin `0700`. |
| **Oturum çerezi** | `HttpOnly`, `SameSite=Lax`, öntanımlı 30 gün (kalıcı giriş). Sunucu yalnızca çerezin SHA-256 özetini saklar. |
| **Kaba kuvvet** | 5 hatalı denemeden sonra adres kilitlenir; süre her denemeyle katlanarak en fazla 15 dakika olur. |
| **CSRF** | Yazma istekleri `SameSite=Lax` + `Origin` denetimiyle korunur. |

> **Neyi korumaz:** HTTP şifreli değildir. Aynı ağda paket dinleyen biri hangi
> videoyu indirdiğinizi, dosya içeriğini ve oturum çerezini görebilir; ama
> parolayı göremez ve çerezi kopyalasa bile yalnızca o oturumun süresi kadar
> geçerli olur. Güvenilmeyen bir ağdaysanız `PULL1SEC_HOST=127.0.0.1` ile
> yalnız bu makineye kısıtlayın ya da önüne TLS'li bir ters vekil koyun.

### Güvenlik varsayılanları

- Ağa açık bir adrese bağlanırken **hesap yoksa sunucu başlamaz**; önce
  `pull1sec user set` çalıştırmanızı söyler. Böylece "ilk gelen şifreyi belirler"
  durumu oluşamaz.
- `PULL1SEC_HOST=127.0.0.1` ile ağ erişimini tümden kapatabilirsiniz.
- İndirme API'si SSRF'e karşı korumalıdır: hedef adres özel/loopback bir ağa
  çözümleniyorsa reddedilir.

## Komut satırı

```
pull1sec [serve]                 sunucuyu başlat (varsayılan komut)
pull1sec url                     ağ adreslerini yazdır
pull1sec user set [seçenekler]   şifreyi belirle veya değiştir
pull1sec user show               hesap bilgisi (parola yok)
pull1sec user remove [--yes]     hesabı sil
pull1sec sessions list           açık oturumlar
pull1sec sessions revoke-all     bütün cihazları çıkar
pull1sec tui                     tam ekran arayüz
pull1sec version                 sürüm
```

`user set` seçenekleri:

| Seçenek | Açıklama |
| --- | --- |
| `--username AD` | Kullanıcı adını değiştir (varsayılan: mevcut) |
| `--password-stdin` | Şifreyi uçbirimden değil standart girdiden oku (betikler için) |
| `--keep-sessions` | Mevcut oturumları kapatma (kullanıcı adı değişirse yine kapanır) |
| `--force` | Mevcut şifreyi sormadan devam et |

## Yapılandırma

Tüm ayarlar ortam değişkeniyle verilir; hepsi isteğe bağlıdır.

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `PULL1SEC_HOST` | `0.0.0.0` | Dinlenecek adres (ağa açık). `127.0.0.1` yapınca yalnız bu makine |
| `PULL1SEC_PORT` | `8787` | Port |
| `PULL1SEC_STATE_DIR` | `~/.local/state/pull1sec` | Hesap ve oturumların tutulduğu dizin |
| `PULL1SEC_SESSION_TTL` | `2592000` (30 gün) | Oturum ömrü (saniye) |
| `PULL1SEC_REQUIRE_AUTH` | `1` | `0` yapılırsa ağa açıkken bile şifre sorulmaz (önerilmez) |
| `PULL1SEC_DOWNLOAD_DIR` | `~/.local/share/pull1sec/downloads` | Geçici dosya dizini |
| `PULL1SEC_MAX_CONCURRENT` | `3` | Aynı anda inen dosya sayısı |
| `PULL1SEC_JOB_TTL` | `3600` | Tamamlanan işlerin ömrü (saniye) |
| `PULL1SEC_MAX_FILESIZE_MB` | `0` (sınırsız) | Tek dosya üst sınırı |
| `PULL1SEC_PROBE_TIMEOUT` | `60` | Meta veri okuma zaman aşımı |
| `PULL1SEC_SOCKET_TIMEOUT` | `30` | Ağ hareketsizlik zaman aşımı |
| `PULL1SEC_ALLOW_PRIVATE_HOSTS` | `false` | Hedef URL'lerde özel ağ adreslerine izin ver |

## HTTP API

`/api/health`, `/api/auth/*` ve statik dosyalar dışındaki **her** uç nokta
oturum ister; oturum yoksa `401 unauthorized` döner.

| Metot | Yol | Açıklama |
| --- | --- | --- |
| `GET` | `/api/health` | Sürüm, ffmpeg ve hesap durumu (herkese açık) |
| `POST` | `/api/auth/challenge` | Tek kullanımlık nonce + tuz + tur sayısı |
| `POST` | `/api/auth/login` | `{username, nonce, proof, remember}` → oturum çerezi |
| `GET` | `/api/auth/me` | Oturum durumu ve cihaz listesi |
| `POST` | `/api/auth/logout` | Bu cihazı çıkar |
| `POST` | `/api/auth/logout-all` | Bütün cihazları çıkar |
| `GET` | `/api/meta` | Sınırlar, desteklenen çerez tarayıcıları |
| `POST` | `/api/probe` | `{ "url": "..." }` → meta veri ve kalite listesi |
| `POST` | `/api/download` | `{ "url", "mode", "height", "audio_format" }` → iş oluşturur |
| `GET` | `/api/jobs` | Son işler |
| `GET` | `/api/jobs/{id}` | Tek işin durumu |
| `GET` | `/api/jobs/{id}/events` | SSE ile canlı ilerleme |
| `POST` | `/api/jobs/{id}/cancel` | İndirmeyi iptal et |
| `DELETE` | `/api/jobs/{id}` | İşi ve dosyasını sil |
| `GET` | `/api/jobs/{id}/file` | Hazır dosyayı indir |

Girişi elle yapmak isteyen betikler için (nonce → kanıt):

```python
import hashlib, json, urllib.request
BASE = "http://192.168.1.26:8787"

def call(path, payload=None, cookie=None):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})},
        method="POST" if payload is not None else "GET",
    )
    return urllib.request.urlopen(request, timeout=60)

def pbkdf2(secret, salt, rounds):
    return hashlib.pbkdf2_hmac("sha256", secret, salt, rounds, dklen=32)

challenge = json.load(call("/api/auth/challenge", {"username": "kerem"}))
verifier = pbkdf2(b"supersecret1", bytes.fromhex(challenge["salt"]), challenge["iterations"])
proof = pbkdf2(verifier, bytes.fromhex(challenge["nonce"]), challenge["iterations"]).hex()

login = call("/api/auth/login", {
    "username": "kerem",
    "nonce": challenge["nonce"],
    "proof": proof,
    "remember": False,
})
cookie = login.headers["set-cookie"].split(";")[0]
print(json.load(call("/api/jobs", cookie=cookie)))
```

Hatalar her zaman aynı gövdeyle döner:

```json
{ "ok": false, "error": { "code": "unauthorized", "message": "…" } }
```

Kodlar: `unauthorized`, `auth_not_configured`, `bad_credentials`,
`too_many_attempts`, `invalid_url`, `unsupported_site`,
`authentication_required`, `cookies_unavailable`, `impersonation_unavailable`,
`media_unavailable`, `network_error`, `forbidden`, `not_found`, `timeout`,
`ffmpeg_missing`, `thumbnail_failed`, `no_output`, `job_not_found`,
`job_not_ready`, `too_many_jobs`, `download_failed`, `internal_error`.

İnteraktif doküman: **http://127.0.0.1:8787/api/docs**

## Geliştirme

```bash
uv sync --extra dev
uv run pytest                    # 177 test, ağ kullanmaz
node tests/js/pbkdf2.mjs         # tarayıcı kriptografisini node ile doğrular
node --check pull1sec/static/app.js
npm test                         # yukarıdaki JS kontrollerinin hepsi
npm pack --dry-run               # npm paketinin içeriğini denetler
```

Kriptografi testi özellikle önemli: tarayıcı tarafındaki `PBKDF2`/`SHA-256`,
`crypto.subtle` bulunmayan ortamlarda (yani LAN IP'si üzerinden HTTP'de) devreye
giren saf JS uygulamasıdır ve Python'un `hashlib` çıktısıyla bit bit aynı olması
test edilir.

Dizinler:

```
bin/pull1sec.js  npm başlatıcısı: özel Python ortamını kurar ve uygulamayı açar
install.sh       curl | bash kurulumu (aynı ortamı paylaşır)
requirements.txt çalışma zamanı bağımlılıkları (pyproject ile aynı)
pull1sec/
  cli.py         serve / user / sessions / tui komutları
  tui.py         curses tabanlı tam ekran arayüz
  auth.py        parola türetme, challenge-response, oturumlar, kilit
  main.py        HTTP katmanı, rotalar, oturum denetimi, SSE
  downloader.py  yt-dlp sarmalayıcı: probe + indirme + hata eşleme
  jobs.py        iş kaydı, eşzamanlılık sınırı, zaman aşımı temizliği
  models.py      pydantic şemaları
  utils.py       URL doğrulama, ağ adresleri, biçimlendirme
  static/        tek sayfa arayüz + auth.js (PBKDF2/SHA-256)
tests/
  js/pbkdf2.mjs  tarayıcı kriptografisi ile node karşılaştırması
```

## Sınırlar ve notlar

- İndirilen içeriğin telif hakkı size ait olmayabilir. Yalnızca indirme hakkına
  sahip olduğunuz içerik için kullanın; sitelerin hizmet şartlarına uyun.
- Playlist desteği bilinçli olarak kapalıdır (`noplaylist`): tek bağlantı, tek
  dosya.
- Canlı yayınlar kaydedilmez.
- Tek hesap vardır; çok kullanıcılı izolasyon ve kota yoktur. Hesabı olan herkes
  tüm indirmeleri görür ve tüm ayarları kullanır.
- Oturum verisi `PULL1SEC_STATE_DIR` altında tutulur. Yedeğini alacaksanız
  dosyayı `0600` izinleriyle saklayın; içinde parola yoktur ama oturum
  özetleri vardır.

## Lisans

MIT. Motor yt-dlp, kendi lisansı (Unlicense) altındadır.
