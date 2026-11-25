# NAKS — No API Key System

**Yapay zekâ özelliklerini API token'ı için para ödemeden, Claude aboneliğinle geliştir.**

[English](README.md) · [Kurulum rehberi](INSTALL.tr.md)

## Sorun

Bir LLM çağıran bir şey geliştirirken çağrıların çoğu deneme amaçlıdır. Prompt'u değiştirip tekrar çalıştırırsın, bir hatayı düzeltip tekrar çalıştırırsın, arayüzü kontrol etmek için bir kez daha çalıştırırsın. Bunların her biri API token'ı harcar, oysa muhtemelen her gün kullandığın bir Claude aboneliğin zaten var.

## NAKS ne yapar?

NAKS **geliştirme sırasında** kodun ile model API'si arasına girer:

1. Kodun bir soru sorar: ya normal Anthropic/OpenAI SDK'sı üzerinden ya da NAKS'ın küçük `ask()` fonksiyonuyla.
2. NAKS aynı soruyu daha önce cevapladıysa cevap doğrudan diskteki bir dosyadan gelir. Hiçbir model çağrılmaz.
3. Cevaplamadıysa soru **Claude aboneliğinden** cevaplanır. Bunun için iki yoldan birini seçersin:
   - **Sohbet modu (varsayılan):** soru bir dosyaya kaydedilir. Hazır olduğunda bir Claude sohbetinde `/naks` yazarsın, Claude bekleyen bütün soruları tek seferde cevaplar ve cevapları geri yazar.
   - **CLI modu:** soru senin makinende Claude Code (`claude -p`) ile anında cevaplanır. Belirlediğin günlük bir sınır vardır.
4. Her cevap kaydedilir, kodu tekrar çalıştırmak hiçbir şeye mal olmaz.

Production'da tek bir ayarı değiştirirsin (`NAKS_MODE=api`) ve aynı kod gerçek API'yi kendi API anahtarınla, her zamanki gibi çağırır.

```
kodun ──ask() / SDK──▶ NAKS ──▶ daha önce cevaplandı mı? ── evet ──▶ diskten cevap
                                     │ hayır
                    ┌────────────────┼──────────────────┬───────────────┐
                    ▼                ▼                  ▼               ▼
                  chat              cli              record           api
           kuyruğa al; sohbette  `claude -p`,     gerçek API bir    gerçek API,
           /naks ile cevapla     anında            kez, sonra kayıt  önbellek yok
                                 (günlük sınır)                     (production)
                    └────────────────┴──────────────────┘
                                     ▼
                         .naks/responses/<id>.json
```

**Uygun olduğu yerler:** prototipler, prompt denemeleri, test verisi ve fixture üretmek, sık tekrar çalıştırdığın betikler ve iş akışları, yan projeler.
**Uygun olmadığı yerler:** production trafiği, başka kullanıcılara hizmet vermek, gerçek zamanlı sohbet arayüzleri (sohbet modunda cevaplar `/naks` dediğinde gelir) ve döngü içinde tool çağıran çok adımlı ajanlar.

> **"OpenAI uyumlu" ne demek?** NAKS, OpenAI SDK'sıyla yazılmış projeler değişiklik yapmadan çalışsın diye istekleri OpenAI'ın API formatında da kabul eder. Bu istekleri de yine **Claude** cevaplar, GPT modelleri değil.

## Neler gerekli?

| | Ne için |
|---|---|
| Bir Claude planı (Pro, Max, …) | Her şey: cevaplar aboneliğinden gelir |
| Python 3.9+ | Her şey (NAKS'ın başka bir bağımlılığı yok) |
| Projeler klasörü eklenmiş [Claude masaüstü uygulaması](https://claude.ai/download) ve `/naks` skill'i | Sohbet modu: Claude bekleyen soruları diskten okur |
| Claude hesabınla giriş yapılmış [Claude Code](https://code.claude.com/docs/en/setup) | CLI modu |
| Node 18+ | Sadece JavaScript istemcisini kullanacaksan |
| Bir API anahtarı | Sadece `record` ve `api` modları için |

[Kurulum rehberi](INSTALL.tr.md) bunların hepsini adım adım anlatıyor.

## Hızlı başlangıç

```bash
git clone https://github.com/genceumut/naks ~/Projects/naks
export PATH="$HOME/Projects/naks/bin:$PATH"   # isteğe bağlı: `naks-dev`'i her yerden yazabilmek için
python3 ~/Projects/naks/examples/demo.py       # "2 request(s) queued" yazar
```

Sonra bir Claude sohbetinde `/naks naks` yaz, demoyu tekrar çalıştır, cevaplar görünür. Bunun için `/naks` skill'i ve projeler klasörü eklenmiş Claude masaüstü uygulaması gerekiyor. İkisi de [kurulum rehberinde](INSTALL.tr.md) anlatılıyor. Sohbet yerine Claude Code ile de cevaplatabilirsin: `NAKS_MODE=cli python3 -c "import sys; sys.path.insert(0, '$HOME/Projects/naks/python'); from naks_client import ask; print(ask('Say hello in 3 words'))"`.

## Bir projeyi bağlamak

### Yol 1: kod değişikliği olmadan (`naks-dev`)

Projen resmi **Anthropic** ya da **OpenAI** SDK'sını kullanıyorsa, zaten kullandığın komutun başına `naks-dev` ekle:

```bash
cd projen
naks-dev npm run dev                         # sohbet modu: /naks ile cevapla
NAKS_MODE=cli naks-dev python3 generate.py   # cli modu: claude -p anında cevaplar
```

`naks-dev`, Anthropic ve OpenAI API'lerini konuşan küçük bir yerel sunucu başlatır (`naks serve`, port 4141). SDK'nı `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` ile ve sahte bir API anahtarıyla bu sunucuya yönlendirir. Komutun bitince sunucuyu kapatır. Kodun aradaki farkı anlamaz.

Sunucu normal istekleri, streaming'i, görselleri ve PDF'leri, JSON şemalı çıktıyı ve tek bir tool ile yapılandırılmış çıktıyı destekler.

### Yol 2: koddan çağırmak (`ask()`)

Yeni kod yazıyorsan ya da proje resmi bir SDK kullanmıyorsa tek bir dosyayı projene kopyala. Bağımlılığı yok.

```python
from naks_client import ask   # python/naks_client.py

title = ask("Suggest a 5-word title for this note:\n" + note, task="note-title")
tags = ask("Extract 2-4 tags.", inputs={"note": note},
           schema={"type": "array", "items": {"type": "string"}}, task="tags")
summary = ask("Summarize this slide in one sentence.", files=["slides/p3.png"], task="slide-summary")
```

```js
import { ask } from "./naks-client.mjs";   // js/naks-client.mjs (+ naks-client.d.mts tipleri)
const tags = await ask("Extract 2-4 tags.", { inputs: { note }, schema: { type: "array", items: { type: "string" } }, task: "tags" });
```

Sohbet modunda cevabı olmayan bir `ask()`, `/naks` çalıştırmanı söyleyen bir `NaksPending` hatası fırlatır. Kodu çalıştırırsın, `/naks` dersin, tekrar çalıştırırsın. Prompt'u, sistem mesajını, girdileri, şemayı ya da ekli bir dosyayı değiştirirsen yeni bir soru oluşur. Değişmeyen hiçbir şey iki kez sorulmaz.

### Yol 3: Claude'a yaptırmak (`/naksify`)

`/naksify` skill'i kuruluysa Claude'da `/naksify projem` yaz. Skill önce Yol 1'in yetip yetmediğine bakar ve yetiyorsa sana komutu verir. Yetmiyorsa `naks-at-your-service/projem/` altında dönüştürülmüş bir kopya oluşturur. Orijinale dokunmaz.

## Modlar

`NAKS_MODE` ortam değişkeniyle seçilir. `api` dışındaki her mod önce kayıtlı bir cevap arar.

| Mod | Kayıtlı cevap yoksa | Ne için |
|---|---|---|
| `chat` (varsayılan) | Soruyu kaydeder ve `/naks`'ı bekler | Toplu işler, görsel içeren sorular, kontrol etmek istediğin her şey |
| `cli` | `claude -p` ile anında cevaplar | Çalışırken gelen küçük, tek tek sorular |
| `record` | Gerçek API'yi bir kez çağırır ve cevabı kaydeder | Gerçek model çıktısını fixture olarak saklamak |
| `replay` | `NaksMissing` hatası verir, yeni bir şey sormaz | Testler ve CI |
| `api` | Önbelleğe bakmadan doğrudan gerçek API'yi çağırır | Production |

### `cli` modunun güvenlik önlemleri

- **Sadece metin.** `claude -p` bütün araçları kapalı, boş bir geçici klasörde, MCP sunucusu olmadan ve oturum kaydetmeden çalışır.
- **API faturası yok.** `ANTHROPIC_API_KEY` ortamından silinir, böylece Claude Code planın yerine sessizce API hesabına fatura çıkaramaz.
- **Günlük sınır.** Günde en fazla `NAKS_CLI_DAILY_LIMIT` çağrı yapılır (varsayılan 20). Her çağrı `.naks/cli-log.jsonl` dosyasına loglanır.
- **Sohbet moduna geri düşme.** Sınır dolunca, soruda ek varsa, Claude Code kurulu değilse ya da bir çağrı iki kez başarısız olursa soru sohbet moduna kalır.

### Ayarlar

| Değişken | Varsayılan | Ne yapar |
|---|---|---|
| `NAKS_MODE` | `chat` | Yukarıya bak |
| `NAKS_DIR` | proje kökündeki `.naks` (`.git` ya da `.naks` içeren en yakın klasör) | Soruların ve cevapların durduğu yer |
| `NAKS_WAIT` | `0` | `ask()`'in sohbet modunda `NaksPending` fırlatmadan önce cevap bekleyeceği saniye |
| `NAKS_MODEL` | `claude-sonnet-5-5` | `api` / `record` için model |
| `NAKS_CLI_DAILY_LIMIT` | `20` | Günlük en fazla `claude -p` çağrısı |
| `NAKS_CLI_TIMEOUT` | `180` | Tek bir `claude -p` çağrısı için saniye |
| `NAKS_CLI_MODEL` | Claude Code'un varsayılanı | `cli` için model |
| `NAKS_PORT` | `4141` | `naks serve` / `naks-dev` portu |
| `NAKS_SERVE_WAIT` | `540` | Sunucunun sohbet modunda bir isteği açık tutacağı saniye. Süre dolunca HTTP 424 döner, SDK'lar bunu otomatik tekrar denemez. |

## Claude skill'leri

[`skill/`](skill/) klasöründe iki skill var. Claude'a nasıl ekleneceklerini [kurulum rehberi](INSTALL.tr.md#4-claude-skilllerini-kur) anlatıyor.

- **`/naks`**, projelerindeki bekleyen soruları bulur (Claude masaüstü uygulamasının klasör erişimiyle ya da bir GitHub reposundan). Her birini sade bir API çağrısı nasıl cevaplarsa öyle cevaplar ve cevap dosyalarını yazar.
- **`/naksify <proje>`**, mevcut bir projeyi [Yol 3](#yol-3-claudea-yaptırmak-naksify)'te anlatıldığı gibi bağlar.

Protokol sade JSON dosyalarından oluşuyor. `.naks/` klasörünü okuyup yazabilen her şey soruları cevaplayabilir.

## Sık sorulanlar

**Bu kullanım serbest mi?** NAKS temkinli tarafta kalacak şekilde tasarlandı. Aşağıdaki [Sorumlu kullanım](#sorumlu-kullanım) bölümüne bak. Kısaca: sadece kişisel geliştirme, kimlik bilgisi kopyalamak yok, sadece resmi Claude uygulamaları.

**Cevaplar API'nin vereceğiyle aynı mı olur?** Birebir aynı olmaz ve `temperature` gibi API ayarları geçerli olmaz. Geliştirme ve test için çok uygundur. Son prompt ayarları için `record` ya da `api` modunu kullan.

**`.naks/` klasörünü commit'lemeli miyim?** `.naks/responses/` içindeki cevaplar test fixture'ı olarak işe yarar. Prompt'larında gizli bir şey varsa `.naks/requests/` klasörünü commit'leme. `.naks/cli-usage.json` ve `.naks/cli-log.jsonl` dosyalarını her zaman yoksay.

**Bilgisayarım yerine GitHub'dan cevaplayabilir miyim?** Evet. `.naks/requests/` klasörünü push'la, Claude'da `/naks github repon` de, Claude cevapları commit'ler. Sonra `git pull` yaparsın.

**ChatGPT aboneliğimle çalışır mı?** Şimdilik hayır. NAKS cevapları Claude ile verir.

## Sorumlu kullanım

- **Kimlik bilgisi yeniden kullanılmaz.** NAKS hiçbir zaman OAuth token'ı ya da web oturumu kopyalamaz veya taşımaz. Bir sohbet sitesini de otomatikleştirmez. Cevaplar iki yoldan gelir: senin resmi bir Claude uygulamasında çalışman (`chat` modu) ya da kendi makinendeki resmi Claude Code CLI (`cli` modu).
- **Sadece kişisel geliştirme için.** Son kullanıcılara açma, bir aboneliği birden fazla kişiyle paylaşma ve NAKS'ı bir servis olarak çalıştırma. Production trafiği kendi API anahtarınla `NAKS_MODE=api` kullanmalı.
- **`cli` modunu ölçülü kullan.** Anthropic'in yardım merkezine göre Kasım 2026 itibarıyla Claude planındaki `claude -p` kullanımı planın kullanım limitlerinden düşüyor ([kaynak](https://support.claude.com/en/articles/15036540)). Aboneliklerin programatik kullanımına dair kurallar 2026'da birkaç kez değişti. Güncel [Tüketici Şartları](https://www.anthropic.com/legal/consumer-terms)'nı kendin kontrol et. Günlük sınırı düşük tut ve `cli` modunu zamanlanmış ya da gözetimsiz işler için kullanma.

NAKS'ı kendi hesaplarınla nasıl kullandığından sen sorumlusun. NAKS, Anthropic ya da OpenAI ile bağlantılı değildir ve onlar tarafından desteklenmemektedir.

## Sınırlar

- Sohbet modu gerçek zamanlı değildir: cevaplar `/naks` çalıştırdığında gelir.
- `naks serve` yapılandırılmış çıktı için istek başına tek bir tool destekler, çok adımlı tool döngülerini desteklemez. Embedding, ses ve görsel üretme desteklenmez.
- CLI modu, kodunu çalıştıran makinede Claude Code'un kurulu ve giriş yapılmış olmasını gerektirir.

## Nasıl çalışır (protokol)

Her soru, içeriğinin özetiyle (hash) adlandırılmış bir JSON dosyasıdır:

```json
// .naks/requests/tags-3f2a9c1b7d4e.json
{
  "naks": 1,
  "id": "tags-3f2a9c1b7d4e",
  "project": "my-app",
  "task": "tags",
  "created_at": "2026-11-24T10:45:00+00:00",
  "system": "Optional system prompt",
  "prompt": "Extract 2-4 tags.",
  "inputs": { "note": "..." },
  "output": { "format": "json", "schema": { "type": "array", "items": { "type": "string" } } },
  "files": [{ "path": "slides/p3.png", "sha256": "…" }]
}
```

```json
// .naks/responses/tags-3f2a9c1b7d4e.json
{ "naks": 1, "id": "tags-3f2a9c1b7d4e", "answered_at": "…", "answered_by": "claude-chat", "output": ["work", "meeting"] }
```

- **Id:** `<task>-<SHA-256'nın ilk 12 hex karakteri>`. Özet `system`, `prompt`, `inputs`, `output` ve `files` alanlarından hesaplanır. Python ve JS istemcileri aynı id'yi üretir, yani cevapları paylaşırlar.
- **`output.format`:** `text`, `markdown` ya da `json`. Şema verilmişse varsayılan `json`'dur.
- **`answered_by`:** `claude-chat`, `claude-cli` ya da `api:<model>`.
- **Hatalar:** cevaplanamayan bir soruda `output` yerine `"error": "…"` yazılır.
- **Sunucu istekleri:** `naks serve` üzerinden gelen soruların id'leri `serve-anthropic-…` / `serve-openai-…` şeklindedir. İsim vermek için `X-NAKS-Task` başlığını gönder. Base64 olarak gönderilen görseller `.naks/files/` altına kaydedilir.

## Proje yapısı

```
bin/naks-dev            herhangi bir komutu SDK çağrıları NAKS'tan geçecek şekilde çalıştırır
python/naks_client.py   Python istemcisi: ask, submit, get, pending
python/naks_serve.py    yerel Anthropic/OpenAI uyumlu sunucu
js/naks-client.mjs      JavaScript istemcisi (+ naks-client.d.mts tipleri)
skill/                  Claude skill'leri: /naks ve /naksify
examples/demo.py        iki soruluk demo
INSTALL.md              adım adım kurulum
```

## Lisans

[MIT](LICENSE)
