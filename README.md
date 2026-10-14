# Pull1sec

Bir sosyal medya bağlantısı yapıştır, videoyu al. Kendi makinenizde çalışan,
tek kullanıcılık bir video indirici. Motor [yt-dlp](https://github.com/yt-dlp/yt-dlp)
olduğu için YouTube, TikTok, Instagram, X (Twitter), Facebook, Reddit, Vimeo,
Twitch, Bilibili ve [1800'den fazla site](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
desteklenir.

Dosyalar sunucuda kalır, dışarıya hiçbir şey gönderilmez. İndirilen dosyalar
varsayılan olarak bir saat sonra otomatik silinir.

---

## Hızlı başlangıç

Gerekenler: **Python 3.11+**, **ffmpeg** ve **uv** (veya pip).

```bash
cd pull1sec
uv sync                 # bağımlılıkları kurar

./run.sh                # http://127.0.0.1:8787
# veya
uv run python -m pull1sec
```

Tarayıcıda **http://127.0.0.1:8787** adresini aç. Arayüz Türkçe ve İngilizce
arasında geçiş yapar, açık/koyu temayı sistem ayarından alır.

> 8787 portu dolduysa `PULL1SEC_PORT=9000 uv run python -m pull1sec` gibi başka bir
> port verin.

`uv` yerine düz pip ile:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m pull1sec
```

FFmpeg kontrolü:

```bash
ffmpeg -version
curl -s localhost:8787/api/health
```

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

## Yapılandırma

Tüm ayarlar ortam değişkeniyle verilir; hepsi isteğe bağlıdır.

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `PULL1SEC_HOST` | `127.0.0.1` | Dinlenecek adres |
| `PULL1SEC_PORT` | `8787` | Port |
| `PULL1SEC_DOWNLOAD_DIR` | `./.downloads` | Geçici dosya dizini |
| `PULL1SEC_MAX_CONCURRENT` | `3` | Aynı anda inen dosya sayısı |
| `PULL1SEC_JOB_TTL` | `3600` | Tamamlanan işlerin ömrü (saniye) |
| `PULL1SEC_MAX_FILESIZE_MB` | `0` (sınırsız) | Tek dosya üst sınırı |
| `PULL1SEC_PROBE_TIMEOUT` | `60` | Meta veri okuma zaman aşımı |
| `PULL1SEC_SOCKET_TIMEOUT` | `30` | Ağ hareketsizlik zaman aşımı |
| `PULL1SEC_ALLOW_PRIVATE_HOSTS` | `false` | `true` yapılırsa özel ağ adreslerine izin verilir |

Örnek:

```bash
PULL1SEC_PORT=9000 PULL1SEC_MAX_CONCURRENT=5 uv run python -m pull1sec
```

> `PULL1SEC_ALLOW_PRIVATE_HOSTS` varsayılan olarak kapalıdır: API'nin yerel ağa
> atlama tahtası olarak kullanılmasını (SSRF) engeller. Geliştirme sırasında
> gerekirse açın.

## HTTP API

| Metot | Yol | Açıklama |
| --- | --- | --- |
| `GET` | `/api/health` | Sürüm ve ffmpeg durumu |
| `GET` | `/api/meta` | Sınırlar, desteklenen çerez tarayıcıları |
| `POST` | `/api/probe` | `{ "url": "..." }` → meta veri ve kalite listesi |
| `POST` | `/api/download` | `{ "url", "mode", "height", "audio_format" }` → iş oluşturur |
| `GET` | `/api/jobs` | Son işler |
| `GET` | `/api/jobs/{id}` | Tek işin durumu |
| `GET` | `/api/jobs/{id}/events` | SSE ile canlı ilerleme |
| `POST` | `/api/jobs/{id}/cancel` | İndirmeyi iptal et |
| `DELETE` | `/api/jobs/{id}` | İşi ve dosyasını sil |
| `GET` | `/api/jobs/{id}/file` | Hazır dosyayı indir |

Örnek:

```bash
curl -s localhost:8787/api/probe \
  -H 'content-type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=aqz-KE-bpKQ"}' | jq '.media.title'

JOB=$(curl -s localhost:8787/api/download -H 'content-type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=aqz-KE-bpKQ","mode":"video","height":720}' \
  | jq -r '.job.id')

curl -N "localhost:8787/api/jobs/$JOB/events"        # canlı ilerleme
curl -OJ "localhost:8787/api/jobs/$JOB/file"         # dosyayı indir
```

Hatalar her zaman aynı gövdeyle döner:

```json
{ "ok": false, "error": { "code": "authentication_required", "message": "…" } }
```

Kodlar: `invalid_url`, `unsupported_site`, `authentication_required`,
`cookies_unavailable`, `impersonation_unavailable`, `media_unavailable`,
`network_error`, `forbidden`, `not_found`, `timeout`, `ffmpeg_missing`,
`thumbnail_failed`, `no_output`, `job_not_found`, `job_not_ready`,
`too_many_jobs`, `download_failed`, `internal_error`.

`authentication_required` alıyorsanız arayüzdeki **Giriş gerektiren gönderiler**
bölümünden çerezleri kendi tarayıcınızdan almayı deneyin.

## Geliştirme

```bash
uv sync --extra dev
uv run pytest                    # 82 test, ağ kullanmaz
node --check pull1sec/static/app.js   # arayüz sözdizimi
```

Dizinler:

```
pull1sec/
  main.py        HTTP katmanı, rotalar, SSE
  downloader.py  yt-dlp sarmalayıcı: probe + indirme + hata eşleme
  jobs.py        iş kaydı, eşzamanlılık sınırı, zaman aşımı temizliği
  models.py      pydantic şemaları
  utils.py       URL doğrulama, dosya adı, biçimlendirme
  static/        tek sayfa arayüz (HTML/CSS/JS, derleme yok)
tests/
```

## Sınırlar ve notlar

- Bu bir **tek kullanıcılık yerel araçtır**. Kimlik doğrulama, kota veya çok
  kullanıcı izolasyonu yoktur; internete açık bir sunucuya koymayın.
- İndirilen içeriğin telif hakkı size ait olmayabilir. Yalnızca indirme hakkına
  sahip olduğunuz içerik için kullanın; sitelerin hizmet şartlarına uyun.
- Playlist desteği bilinçli olarak kapalıdır (`noplaylist`): tek bağlantı, tek
  dosya.
- Canlı yayınlar kaydedilmez; başlatılırsa akışın bitmesi beklenir.

## Lisans

MIT. Motor yt-dlp, kendi lisansı (Unlicense) altındadır.
